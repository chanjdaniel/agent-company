"""The honesty loop's code: each promise checked when due, the complaint threshold, and Daniel's word lifting a pause.

A cell's promise is kept only by Daniel's word, since a cell's own report never counts, and one with no such word at the
first check after its due date has ended is broken, which is a finding code confirms and a pause of that cell. A runner's promise is the code's:
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

from company import audit, contract, paths, settings, times, treasurer
from company.ledger import Ledger

KEPT, BROKEN, NOT_RUN = "kept", "broken", "not-run"
CELL_SCOPE = "cell"
RESUME_OUTSIDE = "company cell resume --outside-actions"
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
    """The flags since Daniel's last review against what pauses new outside actions.

    `pause` is the pause this wrote, if it wrote one, and `holding` is whether new outside actions are refused now.
    """

    flagged: int
    needed: Fraction
    days: int | float
    pause: dict | None
    holding: bool


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


def pause_in_effect(events: list[dict], scope: str, bet: str | None = None) -> dict | None:
    """The `cell-paused` holding this scope now, if any; the newest word on it stands."""
    for event in reversed(events):
        if event["kind"] in ("cell-paused", "cell-resumed") and event["scope"] == scope and (scope != CELL_SCOPE or event.get("bet", bet) == bet):
            return event if event["kind"] == "cell-paused" else None
    return None


def _runner_result(events: list[dict], promise: dict, today: str) -> tuple[str, list[int]] | None:
    """A runner's promise: closed by its date is kept, and past it with no such close it was not run."""
    periods = {event["seq"] for event in treasurer.of_kind(events, "paper-opened") if event.get("promise_seq") == promise["seq"]}
    closed = next((event for event in treasurer.of_kind(events, "paper-closed") if event["period_seq"] in periods), None)
    if closed is not None and closed["ts"][:10] <= promise["due_date"]:
        return KEPT, [closed["seq"]]
    if today > promise["due_date"]:
        return NOT_RUN, [closed["seq"]] if closed is not None else []
    return None


def _finding_of(events: list[dict], seq: int) -> int | None:
    """The finding a check wrote on this promise, which is its reading as broken, even if the check stopped there."""
    return next((event["seq"] for event in treasurer.of_kind(events, "finding") if event.get("promise_seq") == seq), None)


def _cell_result(events: list[dict], promise: dict, today: str) -> tuple[str, list[int]] | None:
    """A cell's promise: Daniel's word keeps it, and past its date with none it is broken, which a word after that reading does not change."""
    if _finding_of(events, promise["seq"]) is not None:
        return BROKEN, []
    word = next((event for event in treasurer.of_kind(events, "promise-kept") if event["promise_seq"] == promise["seq"]), None)
    if word is not None and word["kept_date"] <= promise["due_date"]:
        return KEPT, [word["seq"]]
    return (BROKEN, []) if today > promise["due_date"] else None


def _is_the_cells(promise: dict) -> bool:
    return promise["writer"].startswith(contract.CELL_PREFIX)


def _is_confirmed(events: list[dict], seq: int) -> bool:
    return any(event["finding_seq"] == seq for event in treasurer.of_kind(events, "finding-confirmed"))


def _is_paused_for(events: list[dict], seq: int) -> bool:
    return any(event["cause_seq"] == seq for event in treasurer.of_kind(events, "cell-paused"))


def _is_settled(events: list[dict], seq: int, bet: str | None) -> bool:
    """Whether a finding has all a confirmation brings: its word, and on a bet its pause."""
    return _is_confirmed(events, seq) and (not bet or _is_paused_for(events, seq))


def _confirm_and_pause(ledger: Ledger, events: list[dict], seq: int, bet: str | None, reason: str, writer: str, message: str | None = None) -> None:
    """The confirmation and its cell's pause, each only if an earlier step did not write it, so that one stopped part way is finished by the next.

    A resume lifts a pause and leaves its cause, so a finding pauses its cell once.
    """
    if not _is_confirmed(events, seq):
        ledger.append("finding-confirmed", {"finding_seq": seq} | ({"message": message} if message else {}), writer)
    if bet and not _is_paused_for(events, seq):
        ledger.append("cell-paused", {"scope": CELL_SCOPE, "reason": reason, "cause_seq": seq, "bet": bet}, "treasurer")


def _finding_reason(finding: dict) -> str:
    return f"{finding['rubric']}: finding {finding['seq']}"


def confirm_finding(seq: int, message: str | None = None) -> dict:
    """Daniel's word on a finding code could not check, which pauses its cell; returns the finding."""
    with _one_at_a_time():
        ledger = Ledger()
        events = ledger.read()
        finding = next((event for event in treasurer.of_kind(events, "finding") if event["seq"] == seq), None)
        if finding is None:
            raise _refusal(ledger, "finding-confirmed", "no-such-finding", f"event {seq} is no finding")
        bet = finding.get("bet")
        if _is_settled(events, seq, bet):
            raise _refusal(ledger, "finding-confirmed", "already-confirmed", f"finding {seq} is already confirmed")
        _confirm_and_pause(ledger, events, seq, bet, _finding_reason(finding), "board", message)
        return finding


def confirm_by_code() -> list[dict]:
    """Confirm each finding whose claim code agrees with, and finish what a stopped run left; returns those confirmed by code, not by Daniel."""
    with _one_at_a_time():
        ledger = Ledger()
        events = ledger.read()
        confirmed = []
        for finding in treasurer.of_kind(events, "finding"):
            seq, bet = finding["seq"], finding.get("bet")
            if "claim" not in finding or _is_settled(events, seq, bet):
                continue
            word = next((event for event in treasurer.of_kind(events, "finding-confirmed") if event["finding_seq"] == seq), None)
            if word is None and not audit.code_confirms(events, finding):
                continue
            _confirm_and_pause(ledger, events, seq, bet, _finding_reason(finding), "treasurer")
            if word is None or word["writer"] == "treasurer":
                confirmed.append(finding)
        return confirmed


def _record_broken(ledger: Ledger, events: list[dict], promise: dict) -> int:
    """The finding, its confirmation and the pause, each only if an earlier check did not write it; returns the finding's seq."""
    bet = treasurer.bet_of(promise)
    seq = promise["seq"]
    finding = _finding_of(events, seq)
    if finding is None:
        summary = f"The cell's promise in event {seq} fell due on {promise['due_date']} with no word that it was kept."
        fields = {"rubric": audit.BROKEN_PROMISE, "summary": summary, "evidence": f"event {seq}", "bet": bet, "promise_seq": seq}
        finding = ledger.append("finding", fields, "treasurer")["seq"]
    reason = f"{audit.BROKEN_PROMISE}: the promise in event {seq} fell due on {promise['due_date']}"
    _confirm_and_pause(ledger, events, finding, bet, reason, "treasurer")
    return finding


def check_promises() -> list[Checked]:
    """Log `promise-checked` once for each promise now settled, and what a broken one brings; what it wrote stands if it raises."""
    with _one_at_a_time():
        ledger = Ledger()
        events = ledger.read()
        today = times.now().date().isoformat()
        done = {event["promise_seq"] for event in treasurer.of_kind(events, "promise-checked")}
        results = []
        for promise in treasurer.of_kind(events, "promise-recorded"):
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


def _refusal(ledger: Ledger, kind: str, reason: str, words: str) -> Refused:
    """Log the refusal, and give the exception to raise."""
    return Refused(words, ledger.refuse(kind, "board", reason)["seq"])


@dataclass(frozen=True)
class Kept:
    """Daniel's word on a promise; `finding`, if any, is the check's reading of it as broken, which stands beside the word."""

    event: dict
    finding: int | None
    bet: str


def keep_promise(seq: int, on: date, note: str | None = None) -> Kept:
    """Daniel's word that a cell's promise was kept on this day, which must be by its due date.

    Before any check reads the promise, the word is what keeps it. After one read it as broken, the word corrects the record without rewriting it: the one result, its finding and any pause stay, and the digest counts the promise apart.
    """
    with _one_at_a_time():
        ledger = Ledger()
        events = ledger.read()
        promise = next((event for event in treasurer.of_kind(events, "promise-recorded") if event["seq"] == seq), None)
        if promise is None:
            raise _refusal(ledger, "promise-kept", "no-such-promise", f"event {seq} is no promise")
        if not _is_the_cells(promise):
            raise _refusal(ledger, "promise-kept", "not-a-cells-promise", f"event {seq} is the code's own promise, which only its paper period's close keeps")
        if any(event["promise_seq"] == seq for event in treasurer.of_kind(events, "promise-kept")):
            raise _refusal(ledger, "promise-kept", "already-kept", f"event {seq} already has your word that it was kept")
        if on.isoformat() > promise["due_date"]:
            words = f"event {seq} fell due on {promise['due_date']}, so kept on {on.isoformat()} it is broken; if it was kept by then, say the day with --on"
            raise _refusal(ledger, "promise-kept", "after-its-due-date", words)
        made = promise["ts"][:10]
        if on.isoformat() < made:
            raise _refusal(ledger, "promise-kept", "before-it-was-made", f"event {seq} was made on {made}, so it cannot have been kept on {on.isoformat()}")
        fields = {"promise_seq": seq, "kept_date": on.isoformat()}
        event = ledger.append("promise-kept", fields | ({"note": note} if note else {}), "board")
        return Kept(event, _finding_of(events, seq), treasurer.bet_of(promise))


def resume(scope: str, bet: str | None = None, message: str | None = None) -> dict:
    """Daniel's word lifting a pause, which nothing else lifts."""
    with _one_at_a_time():
        ledger = Ledger()
        if pause_in_effect(ledger.read(), scope, bet) is None:
            what = f"the cell {bet} is" if scope == CELL_SCOPE else "new outside actions are"
            raise _refusal(ledger, "cell-resumed", "not-paused", f"{what} not paused")
        fields = {"scope": scope} | ({"bet": bet} if bet else {}) | ({"message": message} if message else {})
        return ledger.append("cell-resumed", fields, "board")


def _since(event: dict, moment: datetime) -> bool:
    when = times.parse_stamp(event["ts"])
    return when is not None and when >= moment


def _flags_since_the_review(events: list[dict], moment: datetime) -> list[dict]:
    """Daniel's review answers for what came before it, or a resume would be undone by the next check while those stay in the month."""
    reviewed = max((event["seq"] for event in treasurer.of_kind(events, "cell-resumed") if event["scope"] == contract.OUTSIDE_ACTIONS_SCOPE), default=0)
    return [event for event in events if event["kind"] in _FLAGS and event["seq"] > reviewed and _since(event, moment)]


def review_complaints() -> Review | None:
    """Pause new outside actions if the flags have reached the threshold, and say whether they are refused now.

    None if there is nothing to say: no flag counts and no hold stands. A ledger that never had a flag reads no setting.
    Raises `settings.SettingsRefused` when the threshold cannot be read.
    """
    with _one_at_a_time():
        ledger = Ledger()
        events = ledger.read()
        if not any(event["kind"] in _FLAGS for event in events):
            return None
        limit = settings.complaint_threshold(settings.load())
        hold = pause_in_effect(events, contract.OUTSIDE_ACTIONS_SCOPE)
        moment = times.now() - timedelta(days=limit["days"])
        flags = _flags_since_the_review(events, moment)
        if hold is None and not flags:
            return None
        actions = sum(_since(event, moment) for event in treasurer.of_kind(events, _OUTSIDE_ACTION_DONE))
        needed = max(Fraction(str(limit["count"])), Fraction(str(limit["outside_action_fraction"])) * actions)
        if hold is not None or len(flags) < needed:
            return Review(len(flags), needed, limit["days"], None, hold is not None)
        reason = f"complaint-threshold: {len(flags)} complaints and spam flags in {limit['days']:g} days, against {float(needed):g}"
        fields = {"scope": contract.OUTSIDE_ACTIONS_SCOPE, "reason": reason, "cause_seq": flags[-1]["seq"]}
        return Review(len(flags), needed, limit["days"], ledger.append("cell-paused", fields, "treasurer"), True)
