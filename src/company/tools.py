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

from company import contract
from company.ledger import AppendRefused, Ledger, LedgerBroken

_PARSE_ERROR = -32700
_NO_METHOD = -32601
_DEFAULT_PROTOCOL = "2025-06-18"


class _BadArguments(Exception):
    """A call's arguments cannot make the event."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: dict
    kind: str
    fields: Callable[[dict, str], dict]


def _note_fields(arguments: dict, session: str) -> dict:
    text = arguments.get("text")
    if not isinstance(text, str) or not text:
        raise _BadArguments
    return {"session": session, "text": text}


_NOTE = Tool(
    "note",
    "Write a note in the company's ledger, under this session.",
    {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    "session-note",
    _note_fields,
)
TOOLS = {tool.name: tool for tool in (_NOTE,)}
ROLE_TOOLS = {"probe": ("note",), "cell": ("note",), "strategy": (), "auditor": (), "retro": ()}
_UNKNOWN_KIND = "unknown-tool"


def writer_of(role: str, bet: str | None) -> str:
    """The writer a session's tools write as."""
    return f"{contract.CELL_PREFIX}{bet}" if role == "cell" else role


class Server:
    """The tools one session may call, with its writer fixed."""

    def __init__(self, role: str, bet: str | None, session: str, ledger: Ledger | None = None):
        self.role, self.session = role, session
        self.writer = writer_of(role, bet)
        self.ledger = ledger or Ledger()

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
            fields = tool.fields(arguments if isinstance(arguments, dict) else {}, self.session)
        except _BadArguments:
            return self._refused(tool.kind, name, "bad-arguments")
        try:
            event = self.ledger.append(tool.kind, fields, self.writer, {"session": self.session, "tool": name})
        except AppendRefused as refused:
            return _result(f"Refused: {refused}", failed=True)
        except (LedgerBroken, OSError) as error:
            return _result(f"The ledger could not take this: {error}. Nothing was written.", failed=True)
        return _result(f"Recorded as event {event['seq']}.")

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
        except ValueError:
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
    args = parser.parse_args()
    serve(Server(args.role, args.bet, args.session), sys.stdin, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
