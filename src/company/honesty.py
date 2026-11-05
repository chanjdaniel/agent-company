"""The honesty loop's code: each promise checked when due, the complaint threshold, and Daniel's word lifting a pause.

A cell's promise is kept only by Daniel's word, since a cell's own report never counts, and one with no such word by the
end of its due date is broken, which is a finding code confirms and a pause of that cell. A runner's promise is the code's:
`paper-closed` by its date keeps it, and otherwise it was not run, which goes against no cell.
Each step looks for what an earlier check wrote, so a check stopped part way is finished by the next with nothing twice.
"""

import contextlib
import fcntl
import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from fractions import Fraction

from company import contract, paths, settings, times
from company.ledger import Ledger

KEPT, BROKEN, NOT_RUN = "kept", "broken", "not-run"
CELL_SCOPE = "cell"
OUTSIDE_SCOPE = contract.OUTSIDE_ACTIONS_SCOPE
RESUME_OUTSIDE = "company cell resume --outside-actions"
_RUBRIC = "broken-promise"
_FLAGS = ("complaint", "spam-flag")
_OUTSIDE_ACTION_DONE = "send-confirmed"


def resume_command(bet: str) -> str:
    return f"company cell resume --bet {bet}"


class Refused(Exception):
    """Daniel's word could not stand; nothing was recorded, and event `seq` records why."""

    def __init__(self, words: str, seq: int):
        super().__init__(words)
        self.seq = seq


@dataclass(frozen=True)
class Checked:
    """One promise's result, as it was logged; `finding` is the seq of a broken promise's finding."""

    promise: dict
    result: str
    finding: int | None = None


@dataclass(frozen=True)
class Review:
    """The flags since Daniel's last review against what pauses new outside actions; `pause` is the pause this wrote, if it wrote one."""

    flagged: int
    needed: Fraction
    days: int | float
    pause: dict | None
    held: bool


@contextlib.contextmanager
def _one_at_a_time() -> Iterator[None]:
    """A check, Daniel's word and a review each read and then write, so that two at once cannot both write what is due."""
    paths.home().mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(paths.home() / "honesty.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _of_kind(events: list[dict], kind: str) -> list[dict]:
    return [event for event in events if event["kind"] == kind]


def pause_in_effect(events: list[dict], scope: str, bet: str | None = None) -> dict | None:
    """The `cell-paused` holding this scope now, if any; the newest word on it stands."""
    for event in reversed(events):
        if event["kind"] in ("cell-paused", "cell-resumed") and event["scope"] == scope and (scope != CELL_SCOPE or event.get("bet", bet) == bet):
            return event if event["kind"] == "cell-paused" else None
    return None


def _runner_result(events: list[dict], promise: dict, today: str) -> tuple[str, list[int]] | None:
    """A runner's promise: closed by its date is kept, and past it with no such close it was not run."""
    periods = {event["seq"] for event in _of_kind(events, "paper-opened") if event.get("promise_seq") == promise["seq"]}
    closed = next((event for event in _of_kind(events, "paper-closed") if event["period_seq"] in periods), None)
    if closed is not None and closed["ts"][:10] <= promise["due_date"]:
        return KEPT, [closed["seq"]]
    if today > promise["due_date"]:
        return NOT_RUN, [closed["seq"]] if closed is not None else []
    return None


def _cell_result(events: list[dict], promise: dict, today: str) -> tuple[str, list[int]] | None:
    """A cell's promise: Daniel's word keeps it, and past its date with none it is broken."""
    word = next((event for event in _of_kind(events, "promise-kept") if event["promise_seq"] == promise["seq"]), None)
    if word is not None and word["kept_date"] <= promise["due_date"]:
        return KEPT, [word["seq"]]
    return (BROKEN, []) if today > promise["due_date"] else None


def _is_the_cells(promise: dict) -> bool:
    return promise["writer"].startswith(contract.CELL_PREFIX)


def _record_broken(ledger: Ledger, events: list[dict], promise: dict) -> int:
    """The finding, its confirmation and the pause, each only if an earlier check did not write it; returns the finding's seq."""
    bet = promise["writer"].removeprefix(contract.CELL_PREFIX)
    seq = promise["seq"]
    finding = next((event["seq"] for event in _of_kind(events, "finding") if event.get("promise_seq") == seq), None)
    if finding is None:
        summary = f"The cell's promise in event {seq} fell due on {promise['due_date']} with no word that it was kept."
        fields = {"rubric": _RUBRIC, "summary": summary, "evidence": f"event {seq}", "bet": bet, "promise_seq": seq}
        finding = ledger.append("finding", fields, "treasurer")["seq"]
    if not any(event["finding_seq"] == finding for event in _of_kind(events, "finding-confirmed")):
        ledger.append("finding-confirmed", {"finding_seq": finding}, "treasurer")
    if not any(event["cause_seq"] == finding for event in _of_kind(events, "cell-paused")):
        reason = f"{_RUBRIC}: the promise in event {seq} fell due on {promise['due_date']}"
        ledger.append("cell-paused", {"scope": CELL_SCOPE, "reason": reason, "cause_seq": finding, "bet": bet}, "treasurer")
    return finding


def check_promises() -> list[Checked]:
    """Log `promise-checked` once for each promise now settled, and what a broken one brings; what it wrote stands if it raises."""
    with _one_at_a_time():
        ledger = Ledger()
        events = ledger.read()
        today = times.now().date().isoformat()
        done = {event["promise_seq"] for event in _of_kind(events, "promise-checked")}
        results = []
        for promise in _of_kind(events, "promise-recorded"):
            if promise["seq"] in done:
                continue
            found = (_cell_result if _is_the_cells(promise) else _runner_result)(events, promise, today)
            if found is None:
                continue
            result, evidence = found
            finding = _record_broken(ledger, events, promise) if result == BROKEN else None
            if finding is not None:
                evidence = [finding]
            ledger.append("promise-checked", {"promise_seq": promise["seq"], "result": result, "evidence_seqs": evidence}, "treasurer")
            results.append(Checked(promise, result, finding))
        return results


def _refuse(ledger: Ledger, kind: str, reason: str, words: str) -> Refused:
    return Refused(words, ledger.refuse(kind, "board", reason)["seq"])


def keep_promise(seq: int, on: date, note: str | None = None) -> dict:
    """Daniel's word that a cell's promise was kept on this day, which must be by its due date and before any check read it."""
    with _one_at_a_time():
        ledger = Ledger()
        events = ledger.read()
        promise = next((event for event in _of_kind(events, "promise-recorded") if event["seq"] == seq), None)
        if promise is None:
            raise _refuse(ledger, "promise-kept", "no-such-promise", f"event {seq} is no promise")
        if not _is_the_cells(promise):
            raise _refuse(ledger, "promise-kept", "not-a-cells-promise", f"event {seq} is the code's own promise, which only its paper period's close keeps")
        checked = next((event for event in _of_kind(events, "promise-checked") if event["promise_seq"] == seq), None)
        if checked is not None:
            raise _refuse(ledger, "promise-kept", "already-checked", f"the check already read event {seq} as {checked['result']}, and a promise gets one result")
        if any(event["promise_seq"] == seq for event in _of_kind(events, "promise-kept")):
            raise _refuse(ledger, "promise-kept", "already-kept", f"event {seq} already has your word that it was kept")
        if on.isoformat() > promise["due_date"]:
            words = f"event {seq} fell due on {promise['due_date']}, so kept on {on.isoformat()} it is broken; if it was kept by then, say the day with --on"
            raise _refuse(ledger, "promise-kept", "after-its-due-date", words)
        fields = {"promise_seq": seq, "kept_date": on.isoformat()}
        return ledger.append("promise-kept", fields | ({"note": note} if note else {}), "board")


def resume(scope: str, bet: str | None = None, message: str | None = None) -> dict:
    """Daniel's word lifting a pause, which nothing else lifts."""
    with _one_at_a_time():
        ledger = Ledger()
        if pause_in_effect(ledger.read(), scope, bet) is None:
            what = f"the cell {bet} is" if scope == CELL_SCOPE else "new outside actions are"
            raise _refuse(ledger, "cell-resumed", "not-paused", f"{what} not paused")
        fields = {"scope": scope} | ({"bet": bet} if bet else {}) | ({"message": message} if message else {})
        return ledger.append("cell-resumed", fields, "board")


def _since(event: dict, moment: datetime) -> bool:
    when = times.parse_stamp(event["ts"])
    return when is not None and when >= moment


def _flags_since_the_review(events: list[dict], moment: datetime) -> list[dict]:
    """Daniel's review answers for what came before it, or a resume would be undone by the next check while those stay in the month."""
    reviewed = max((event["seq"] for event in _of_kind(events, "cell-resumed") if event["scope"] == OUTSIDE_SCOPE), default=0)
    return [event for event in events if event["kind"] in _FLAGS and event["seq"] > reviewed and _since(event, moment)]


def review_complaints() -> Review | None:
    """Pause new outside actions if the flags have reached the threshold; None with no flag to weigh, for which no setting is read.

    Raises `settings.SettingsRefused` when the threshold cannot be read.
    """
    with _one_at_a_time():
        ledger = Ledger()
        events = ledger.read()
        if not any(event["kind"] in _FLAGS for event in events):
            return None
        limit = settings.complaint_threshold(settings.load())
        moment = times.now() - timedelta(days=limit["days"])
        flags = _flags_since_the_review(events, moment)
        if not flags:
            return None
        actions = sum(_since(event, moment) for event in _of_kind(events, _OUTSIDE_ACTION_DONE))
        needed = max(Fraction(str(limit["count"])), Fraction(str(limit["outside_action_fraction"])) * actions)
        if len(flags) < needed:
            return Review(len(flags), needed, limit["days"], None, False)
        if pause_in_effect(events, OUTSIDE_SCOPE) is not None:
            return Review(len(flags), needed, limit["days"], None, True)
        reason = f"complaint-threshold: {len(flags)} complaints and spam flags in {limit['days']:g} days, against {float(needed):g}"
        pause = ledger.append("cell-paused", {"scope": OUTSIDE_SCOPE, "reason": reason, "cause_seq": flags[-1]["seq"]}, "treasurer")
        return Review(len(flags), needed, limit["days"], pause, True)
