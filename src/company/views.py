"""What a session may read of the ledger: a cell's view is its own bet's records, and no finding.

Each kind is named with what ties it to a bet, so a new kind is left out until someone decides a cell may read it.
A cell cannot argue with what it cannot read, so the honesty loop's own kinds are named nowhere here: `finding`,
`finding-confirmed`, `cell-paused`, `cell-resumed`, `complaint`, `spam-flag` and `incident`.
"""

import contextlib
import json
import os
from pathlib import Path

from company import contract

FILE = "ledger.jsonl"
_THE_CELLS_OWN = ("session-note", "strategy-registered", "promise-recorded")
_ON_THE_BET = ("session-started", "promise-recorded", "revenue", "refund", "fee", "spend", "minutes-charged")
_OF_ITS_SESSION = ("session-ended", "session-stopped", "append-refused")
_OF_A_REGISTRATION = ("config-run", "config-refused", "verdict-opened", "verdict", "paper-opened")
_OF_A_PERIOD = ("paper-order", "paper-reading", "paper-closed")
_OF_A_PROMISE = ("promise-kept", "promise-checked")
# A broken promise's result cites its finding, and the result is all a cell needs.
_HIDDEN_FIELDS = ("evidence_seqs",)


def cell_view(events: list[dict], bet: str) -> list[dict]:
    """The events a cell of this bet may read, in order; each cites only earlier ones, so one pass finds them all."""
    writer = contract.cell_writer(bet)
    sessions: set[str] = set()
    registrations: set[int] = set()
    periods: set[int] = set()
    promises: set[int] = set()
    shown = []

    def holds(event: dict) -> bool:
        kind = event["kind"]
        return (
            (kind in _THE_CELLS_OWN and event["writer"] == writer)
            or (kind in _ON_THE_BET and event.get("bet") == bet)
            or (kind in _OF_ITS_SESSION and event.get("session") in sessions)
            or (kind in _OF_A_REGISTRATION and event.get("registration_seq") in registrations)
            or (kind in _OF_A_PERIOD and event.get("period_seq") in periods)
            or (kind in _OF_A_PROMISE and event.get("promise_seq") in promises)
        )

    for event in events:
        if not holds(event):
            continue
        shown.append({name: value for name, value in event.items() if name not in _HIDDEN_FIELDS})
        kind = event["kind"]
        if kind == "session-started":
            sessions.add(event["session"])
        elif kind == "strategy-registered":
            registrations.add(event["seq"])
        elif kind == "paper-opened":
            periods.add(event["seq"])
        elif kind == "promise-recorded":
            promises.add(event["seq"])
    return shown


def write(path: Path, content: bytes) -> None:
    """Put this in a workspace, which an agent could write in: what it left at the path goes, and a link it left is never followed."""
    with contextlib.suppress(FileNotFoundError):
        path.unlink()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as file:
        file.write(content)


def lines(events: list[dict]) -> bytes:
    return "".join(json.dumps(event, separators=(",", ":")) + "\n" for event in events).encode()
