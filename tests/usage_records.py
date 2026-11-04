"""Builders for the records the Treasurer reads: Claude Code's transcripts, the team's day files, and the ledger's events.

The weights below use two list prices from the package's table, per million tokens of output:
`claude-opus-5-5` at 20 and `claude-sonnet-5-5` at 10. So a reply of 5,000,000 output tokens on Opus weighs 100.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from company.ledger import Ledger

OPUS = "claude-opus-5-5"
SONNET = "claude-sonnet-5-5"
SETTINGS = {"monthly_price": 120, "reading_max_age_minutes": 120, "usage_day_dirs": []}

TEAM = "aaaaaaaa-0000-4000-8000-000000000000"
ALPHA = "bbbbbbbb-0000-4000-8000-000000000000"
BETA = "cccccccc-0000-4000-8000-000000000000"
PROBE = "dddddddd-0000-4000-8000-000000000000"


def at(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def transcript_line(session, request, ts, *, model=OPUS, output=0, input_tokens=0, cache_read=0, write=0, lifetimes=None, agent=None):
    """One line of a transcript, as Claude Code writes it for an assistant reply."""
    usage = {
        "input_tokens": input_tokens,
        "output_tokens": output,
        "cache_read_input_tokens": cache_read,
        "cache_creation_input_tokens": write,
    }
    if lifetimes is not None:
        usage["cache_creation"] = {"ephemeral_1h_input_tokens": lifetimes[0], "ephemeral_5m_input_tokens": lifetimes[1]}
    line = {
        "type": "assistant",
        "sessionId": session,
        "requestId": request,
        "timestamp": ts,
        "message": {"model": model, "usage": usage, "content": [{"type": "text", "text": "words"}]},
    }
    if agent:
        line.update(isSidechain=True, agentId=agent)
    return line


class Transcripts:
    """Writes transcript files where Claude Code keeps them."""

    def __init__(self, projects: Path):
        self.projects = projects

    def session(self, session, *lines, project="-some-project", name=None):
        path = self.projects / project / f"{name or session}.jsonl"
        self._write(path, lines)
        return path

    def subagent(self, parent, *lines, project="-some-project", agent="agent-one"):
        path = self.projects / project / parent / "subagents" / f"{agent}.jsonl"
        self._write(path, lines)
        return path

    def raw(self, session, text, project="-some-project"):
        path = self.projects / project / f"{session}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def _write(self, path, lines):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(line) + "\n" for line in lines))


def day_file(usage_dir: Path, machine: str, day: str, *rows):
    """A day file of the team's export: `usage/<machine>/<day>.jsonl`."""
    path = usage_dir / machine / f"{day}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def day_row(session, request, ts, *, model=OPUS, output=0, write_1h=0, write_5m=0):
    return {
        "ts": ts,
        "machine": "other-pc",
        "session": session,
        "project_dir": "-some-project",
        "model": model,
        "request": request,
        "input": 0,
        "cache_write_1h": write_1h,
        "cache_write_5m": write_5m,
        "cache_read": 0,
        "output": output,
    }


def record_reading(window, used_percent, resets_at, taken_at, source="hand", writer="board"):
    """Put a reading in the ledger as it stands, even a malformed one; returns its seq."""
    fields = {"window": window, "used_percent": used_percent, "resets_at": resets_at, "taken_at": taken_at, "source": source}
    return Ledger().append("usage-reading", fields, writer)["seq"]


def start_session(session, role, reading_seq, bet=None, ledger=None):
    """A `session-started` event, which is what makes a session the company's."""
    fields = {
        "session": session,
        "role": role,
        "model": OPUS,
        "run": "run-1",
        "gate": "schedule",
        "account_used": 0,
        "company_used": 0,
        "reading_seq": reading_seq,
    }
    if bet:
        fields["bet"] = bet
    (ledger or Ledger()).append("session-started", fields, "launcher")
