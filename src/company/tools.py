"""The company tools: one local stdio MCP server per session, and an agent's only way to the ledger.

The launcher fixes the role, bet and session on this command line, so the writer is settled before the agent starts.
A tool's arguments never choose a writer, a kind or a session, whatever they name.
Run as `python -P -m company.tools`, since an agent can write in the directory this starts in.
"""

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from company import audit, contract, paper, quant, times
from company.ledger import AppendRefused, Ledger, LedgerBroken

_PARSE_ERROR = -32700
_NO_METHOD = -32601
_DEFAULT_PROTOCOL = "2025-06-18"


class _BadArguments(Exception):
    """A call's arguments cannot make the event; `reason` is the code its refusal logs."""

    def __init__(self, reason: str = "bad-arguments"):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: dict
    kind: str
    act: Callable[["Server", dict], dict]


def _note(server: "Server", arguments: dict) -> dict:
    text = arguments.get("text")
    if not isinstance(text, str) or not text:
        raise _BadArguments
    event = server.ledger.append("session-note", {"session": server.session, "text": text}, server.writer, {"session": server.session, "tool": "note"})
    return _result(f"Recorded as event {event['seq']}.")


def _record_promise(server: "Server", arguments: dict) -> dict:
    promise, due_date, counterparty = arguments.get("promise"), arguments.get("due_date"), arguments.get("counterparty")
    if not isinstance(promise, str) or not promise or not isinstance(due_date, str) or not contract.is_date(due_date) or (counterparty is not None and not isinstance(counterparty, str)):
        raise _BadArguments
    # It would be broken as it is made.
    if due_date < times.now().date().isoformat():
        raise _BadArguments("due-date-past")
    fields = {"promise": promise, "due_date": due_date} | ({"counterparty": counterparty} if counterparty else {})
    event = server.ledger.append("promise-recorded", fields, server.writer, {"session": server.session, "tool": "record_promise"})
    return _result(f"Recorded as event {event['seq']}, due {due_date}.")


def _register_strategy(server: "Server", arguments: dict) -> dict:
    event = quant.register(arguments, server.writer, server.market_data)
    return _result(f"Registered as event {event['seq']}, with the data's hash {event['data_hash']}.")


def _run_backtest(server: "Server", arguments: dict) -> dict:
    return _result(json.dumps(quant.run(arguments, server.writer, server.backtest_seconds)))


def _request_verdict(server: "Server", arguments: dict) -> dict:
    return _result(json.dumps(quant.verdict(arguments, server.writer, server.backtest_seconds)))


def _record_finding(server: "Server", arguments: dict) -> dict:
    rubric, summary, evidence, session, claim = (arguments.get(name) for name in ("rubric", "summary", "evidence", "audited_session", "claim"))
    if rubric not in audit.RUBRICS or not isinstance(summary, str) or not summary or not isinstance(evidence, str) or not evidence:
        raise _BadArguments
    if claim is not None and (rubric != audit.UNSHOWN_RESULT or not audit.is_claim(claim)):
        raise _BadArguments
    if session not in server.audited_sessions:
        raise _BadArguments("not-audited")
    # The audited session's bet is the ledger's word, so that no finding can pause any other cell.
    bet = audit.bet_of_session(server.ledger.read(), session)
    fields = {"rubric": rubric, "summary": summary, "evidence": evidence, "session": session} | ({"bet": bet} if bet else {}) | ({"claim": claim} if claim else {})
    event = server.ledger.append("finding", fields, server.writer, {"session": server.session, "tool": "record_finding"})
    return _result(f"Recorded as event {event['seq']}. It goes to Daniel and the ledger, and no cell can read it.")


_NOTE = Tool(
    "note",
    "Write a note in the company's ledger, under this session.",
    {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    "session-note",
    _note,
)
_PROMISE = Tool(
    "record_promise",
    "Record a promise you have made, with its due date. Daniel alone says it was kept, and with no such word at the first check after that day ends, UTC, "
    "it is broken: a finding that pauses this bet until Daniel resumes it.",
    {
        "type": "object",
        "properties": {
            "promise": {"type": "string", "description": "What was promised, plainly enough for Daniel to tell whether it was kept."},
            "due_date": {"type": "string", "description": "The last day it may be kept on, as YYYY-MM-DD, UTC; not a day already past."},
            "counterparty": {"type": "string", "description": "Whom it was made to, if anyone outside."},
        },
        "required": ["promise", "due_date"],
    },
    "promise-recorded",
    _record_promise,
)
_PERIOD = {
    "type": "object",
    "description": "First and last days, as YYYY-MM-DD.",
    "properties": {"start": {"type": "string"}, "end": {"type": "string"}},
    "required": ["start", "end"],
}
_COST = {
    "type": "object",
    "description": "Basis points charged per unit of turnover.",
    "properties": {"bps_per_turnover": {"type": "number"}},
    "required": ["bps_per_turnover"],
}
_REGISTER = Tool(
    "register_strategy",
    "Pre-register a strategy before any backtest. It may be replaced until its first run, and never after. "
    "Its holdout must come after its in-sample period, and no other registration on the data may hold it. You are never shown it.",
    {
        "type": "object",
        "properties": {
            "strategy": {"type": "string", "description": "Lower-case letters, digits, hyphens and underscores."},
            "universe": {"type": "array", "items": {"type": "string"}},
            "data_source": {"type": "string", "description": f"`{paper.BARS_SOURCE}` for the paper broker's free daily bars, fetched now and kept, or `fixture:<name>`."},
            "in_sample": _PERIOD,
            "holdout": _PERIOD,
            "cost_model": _COST,
            "slippage_model": _COST,
            "max_configurations": {"type": "integer", "description": "The search budget: how many configurations may ever run."},
            "acceptance": {
                "type": "object",
                "properties": {
                    "min_deflated_sharpe": {"type": "number"},
                    "min_holdout_return": {"type": "number"},
                    "max_drawdown": {"type": "number"},
                },
                "required": ["min_deflated_sharpe", "min_holdout_return", "max_drawdown"],
            },
            "paper_days": {"type": "integer", "description": "The paper period's length; 90 if left out."},
        },
        "required": ["strategy", "universe", "data_source", "in_sample", "holdout", "cost_model", "slippage_model", "max_configurations", "acceptance"],
    },
    "strategy-registered",
    _register_strategy,
)
_BACKTEST = Tool(
    "run_backtest",
    "Backtest one configuration on the registered in-sample bars, outside this session, and record what ran. "
    "`code` is Python defining `decide(bar, parameters)`, given one bar at a time as `{date, symbols: {<symbol>: {close, ...}}}`, "
    "and returning target weights by symbol that together hold at most the account's whole value. "
    "It prints nothing, and runs alone, with no network, no writes and a time limit. "
    "Each new code and parameters counts against the budget, even if it fails; a repeat returns its stored result at no cost.",
    {
        "type": "object",
        "properties": {"strategy": {"type": "string"}, "code": {"type": "string"}, "parameters": {"type": "object"}},
        "required": ["strategy", "code"],
    },
    "config-run",
    _run_backtest,
)
_VERDICT = Tool(
    "request_verdict",
    "Ask the Treasurer for the verdict on one configuration you have run: once per registration, whatever it says. "
    "It runs that configuration, outside this session, on the in-sample bars and then the holdout, as one run under the same time limit. "
    "You are told the verdict's fields, and never the holdout's bars or returns, or anything the strategy said there. "
    "Passing takes the deflated Sharpe ratio over every trial you ran on these days, under any registration, the holdout's return, and the worse of the two maximum drawdowns; "
    "a strategy that takes no position on the holdout fails it.",
    {
        "type": "object",
        "properties": {
            "strategy": {"type": "string"},
            "configuration": {"type": "string", "description": "The `config_hash` of a run of this registration that did not fail."},
        },
        "required": ["strategy", "configuration"],
    },
    "verdict",
    _request_verdict,
)
_FINDING = Tool(
    "record_finding",
    "Record what you found against the rubric, for Daniel's digest and the ledger, and nobody else. "
    "It waits for Daniel's word, unless it is an `unshown-result` with a `claim` that code confirms.",
    {
        "type": "object",
        "properties": {
            "rubric": {"type": "string", "enum": list(audit.RUBRICS)},
            "summary": {"type": "string", "description": "What you found, plainly enough for Daniel to decide on it."},
            "evidence": {"type": "string", "description": "Where it shows: the ledger's events by seq, and the transcript's words."},
            "audited_session": {"type": "string", "description": "The session it is about, from those you were given to audit."},
            "claim": {
                "type": "object",
                "description": "Only for an `unshown-result`: a reply's words that state a figure no record shows.",
                "properties": {"quote": {"type": "string", "description": "The reply's own words, whole, exactly as it wrote them."}, "value": {"type": "number", "description": "The figure, as those words write it."}},
                "required": ["quote", "value"],
            },
        },
        "required": ["rubric", "summary", "evidence", "audited_session"],
    },
    "finding",
    _record_finding,
)
TOOLS = {tool.name: tool for tool in (_NOTE, _PROMISE, _REGISTER, _BACKTEST, _VERDICT, _FINDING)}
ROLE_TOOLS = {"probe": ("note",), "cell": ("note", "record_promise", "register_strategy", "run_backtest", "request_verdict"), "strategy": (), "auditor": ("record_finding",), "retro": ()}
_UNKNOWN_KIND = "unknown-tool"


def writer_of(role: str, bet: str | None) -> str:
    """The writer a session's tools write as."""
    return contract.cell_writer(bet) if role == "cell" and bet else role


class Server:
    """The tools one session may call, with its writer fixed."""

    def __init__(self, role: str, bet: str | None, session: str, backtest_seconds: float = 0, market_data: paper.MarketData | None = None, audited_sessions: tuple[str, ...] = ()):
        self.role, self.session, self.backtest_seconds, self.market_data, self.audited_sessions = role, session, backtest_seconds, market_data, audited_sessions
        self.writer = writer_of(role, bet)
        self.ledger = Ledger()

    def _refused(self, kind: str, name, reason: str) -> dict:
        context = {"session": self.session, "tool": name}
        try:
            seq = self.ledger.refuse(kind, self.writer, reason, context)["seq"]
        except (LedgerBroken, OSError) as error:
            return _result(f"Refused: {reason}, and the ledger could not record it: {error}.", failed=True)
        return _result(f"Refused: {reason}. Nothing was written; event {seq} in the ledger records the refusal.", failed=True)

    def call(self, name, arguments) -> dict:
        tool = TOOLS.get(name) if isinstance(name, str) else None
        if tool is None:
            return self._refused(_UNKNOWN_KIND, name, "unknown-tool")
        if name not in ROLE_TOOLS[self.role]:
            return self._refused(tool.kind, name, "tool-not-in-role")
        try:
            return tool.act(self, arguments if isinstance(arguments, dict) else {})
        except _BadArguments as bad:
            return self._refused(tool.kind, name, bad.reason)
        except quant.Refused as refused:
            return self._refused(tool.kind, name, refused.reason)
        except quant.Logged as logged:
            return _result(f"Refused: {logged.reason}. It did not run; event {logged.seq} in the ledger records why.", failed=True)
        except AppendRefused as refused:
            return _result(f"Refused: {refused}", failed=True)
        except (LedgerBroken, OSError) as error:
            return _result(f"The company's records could not take this: {error}. It does not count, and nothing it asked for was recorded.", failed=True)

    def listing(self) -> list[dict]:
        tools = (TOOLS[name] for name in ROLE_TOOLS[self.role])
        return [{"name": tool.name, "description": tool.description, "inputSchema": tool.schema} for tool in tools]

    def answer(self, message: dict) -> dict | None:
        """The reply to one JSON-RPC message, or None for a notification."""
        if "id" not in message:
            return None
        identifier, method, params = message["id"], message.get("method"), message.get("params")
        params = params if isinstance(params, dict) else {}
        result: dict
        if method == "initialize":
            result = {
                "protocolVersion": params.get("protocolVersion") or _DEFAULT_PROTOCOL,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "company", "version": "1"},
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": self.listing()}
        elif method == "tools/call":
            result = self.call(params.get("name"), params.get("arguments"))
        else:
            return {"jsonrpc": "2.0", "id": identifier, "error": {"code": _NO_METHOD, "message": "no such method"}}
        return {"jsonrpc": "2.0", "id": identifier, "result": result}


def _result(text: str, failed: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": failed}


def serve(server: Server, lines, out) -> None:
    for line in lines:
        if not line.strip():
            continue
        reply: dict | None
        try:
            message = json.loads(line)
        except (ValueError, RecursionError):
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": _PARSE_ERROR, "message": "not JSON"}}
        else:
            reply = server.answer(message) if isinstance(message, dict) else None
        if reply is not None:
            out.write(json.dumps(reply) + "\n")
            out.flush()


def main() -> int:
    parser = argparse.ArgumentParser(prog="company.tools", description="One session's company tools, over stdio.")
    parser.add_argument("--role", required=True, choices=sorted(ROLE_TOOLS))
    parser.add_argument("--session", required=True)
    parser.add_argument("--bet")
    parser.add_argument("--backtest-seconds", type=float, default=0, help="A strategy's time limit, from Daniel's settings.")
    parser.add_argument("--paper-key", help="Where the paper key is, for the broker's bars at a registration; no tool reads it otherwise.")
    parser.add_argument("--audited-session", action="append", default=[], help="A session this Auditor was given; a finding may name no other.")
    args = parser.parse_args()
    if args.role == "cell" and not args.backtest_seconds > 0:
        parser.error("a cell's server needs its strategy time limit, --backtest-seconds")
    market_data = paper.MarketData(paper.transport(), Path(args.paper_key)) if args.paper_key else None
    serve(Server(args.role, args.bet, args.session, args.backtest_seconds, market_data, tuple(args.audited_session)), sys.stdin, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
