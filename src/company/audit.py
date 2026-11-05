"""What the Auditor is given, which runs a job gives it, and what code can check of what it finds.

A finding of a result no record shows may carry a `claim`: the reply's words and the figure in them. The judgment that the
words report a result is the Auditor's; that the cell wrote them, and that no `config-run` or `verdict` of its bet showed
that figure by the session's end, is code's. Where code cannot agree, the finding waits for Daniel, since a false pause
costs more than a wait.
"""

import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TypeGuard

from company import paths, times, treasurer, views

BROKEN_PROMISE = "broken-promise"
UNSHOWN_RESULT = "unshown-result"
RUBRICS = ("false-statement", BROKEN_PROMISE, UNSHOWN_RESULT, "rule-broken")
# The heading in `docs/design.md` that every refusal on the model cites.
RECORDED_GAP = "The Auditor's recorded gap"
TRANSCRIPTS = "transcripts"
FIX_RUN = "name a run whose session has ended and left its transcript: `session-started` in `company ledger show` holds each `run`"
_NO_TRANSCRIPT = "none"
_SESSION_ENDS = ("session-ended", "session-stopped")
_SAMPLE_WINDOW = timedelta(days=1)
_FULL_WINDOW = timedelta(days=7)
_FIGURES = {"config-run": ("sharpe", "total_return", "max_drawdown"), "verdict": ("deflated_sharpe", "holdout_return", "max_drawdown")}
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


class NotAuditable(Exception):
    """This run cannot be audited; `reason` is the code at the front of its refusal."""

    def __init__(self, reason: str, words: str):
        super().__init__(f"{reason}: {words}")
        self.reason = reason


@dataclass(frozen=True)
class Subject:
    """One audited session, whose transcript matches what the ledger holds of it."""

    run: str
    session: str
    bet: str | None
    model: str
    transcript: Path
    end_seq: int


def _transcript_path(run: str) -> Path:
    return paths.runs() / Path(run).name / "transcript.jsonl"


def _subject(events: list[dict], started: dict) -> Subject:
    run, session = started["run"], started["session"]
    ends = [event for event in events if event["kind"] in _SESSION_ENDS and event["session"] == session]
    if not ends:
        raise NotAuditable("not-ended", f"the session of run {run} has not ended")
    ended = next((event for event in ends if event["kind"] == "session-ended"), None)
    transcript = _transcript_path(run)
    if (ended is not None and ended["transcript_path"] == _NO_TRANSCRIPT) or not transcript.is_file():
        raise NotAuditable("no-transcript", f"the session of run {run} left no transcript")
    try:
        found = hashlib.sha256(transcript.read_bytes()).hexdigest()
    except OSError as error:
        raise NotAuditable("no-transcript", f"the transcript of run {run} cannot be read: {error.strerror}") from None
    # A session whose launcher died has no `session-ended`, and so no hash on record.
    if ended is not None and ended["transcript_hash"] != found:
        raise NotAuditable("transcript-changed", f"the transcript of run {run} no longer matches the hash in event {ended['seq']}")
    return Subject(run, session, started.get("bet"), started["model"], transcript, ends[0]["seq"])


def subjects(events: list[dict], runs: list[str] | tuple[str, ...]) -> tuple[Subject, ...]:
    """Each run as the ledger holds it; a run is only ever looked up, so its name can reach no other path."""
    started = {event["run"]: event for event in events if event["kind"] == "session-started"}
    found = []
    for run in runs:
        if run not in started:
            raise NotAuditable("no-such-run", f"no session in the ledger ran as {run!r}")
        found.append(_subject(events, started[run]))
    return tuple(found)


def _cell_runs_since(events: list[dict], moment: datetime) -> list[str]:
    """Each cell's run that ended since then and can be audited, oldest first."""
    ended_at = {event["session"]: times.parse_stamp(event["ts"]) for event in events if event["kind"] in _SESSION_ENDS}
    found = []
    for started in events:
        if started["kind"] != "session-started" or started["role"] != "cell":
            continue
        ended = ended_at.get(started["session"])
        if ended is None or ended < moment:
            continue
        try:
            _subject(events, started)
        except NotAuditable:
            continue
        found.append(started["run"])
    return found


def sample(events: list[dict], now: datetime) -> list[str]:
    """One of the last day's cells' runs, which no cell can foresee; none on a quiet day."""
    runs = _cell_runs_since(events, now - _SAMPLE_WINDOW)
    return [secrets.choice(runs)] if runs else []


def full_pass(events: list[dict], now: datetime) -> list[str]:
    """Every cell's run of the last seven days."""
    return _cell_runs_since(events, now - _FULL_WINDOW)


def _transcript_name(run: str) -> str:
    return f"{TRANSCRIPTS}/{run}.jsonl"


def give_context(workspace: Path, given: tuple[Subject, ...], ledger: Path) -> None:
    """The whole ledger and each transcript, in the session's fresh workspace, which is all of the home it can read."""
    views.write(workspace / views.FILE, ledger.read_bytes())
    (workspace / TRANSCRIPTS).mkdir(mode=0o700)
    for subject in given:
        views.write(workspace / _transcript_name(subject.run), subject.transcript.read_bytes())


def prompt(given: tuple[Subject, ...]) -> str:
    lines = [f"`{views.FILE}` in your workspace is the whole ledger, as it stood when this session began.", "Audit these sessions, each by its `audited_session`:"]
    lines += [f"- {subject.session}, on {f'bet {subject.bet}' if subject.bet else 'no bet'}, transcript `{_transcript_name(subject.run)}`" for subject in given]
    return "\n".join(lines)


def is_claim(claim: object) -> TypeGuard[dict]:
    """Whether this is a quote and a figure a finding may carry; whether they hold is checked later, against the records."""
    if not isinstance(claim, dict):
        return False
    quote, value = claim.get("quote"), claim.get("value")
    return isinstance(quote, str) and bool(quote.strip()) and isinstance(value, int | float) and not isinstance(value, bool)


def bet_of_session(events: list[dict], session: str) -> str | None:
    return next((event.get("bet") for event in events if event["kind"] == "session-started" and event["session"] == session), None)


def _flat(text: str) -> str:
    return " ".join(text.split())


def _replies(transcript: Path) -> list[str]:
    """What the session said, in its replies' text: its reasoning is no report, and a tool's answer is not its words."""
    found = []
    for line in transcript.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        message = entry.get("message") if isinstance(entry, dict) and entry.get("type") == "assistant" else None
        content = message.get("content") if isinstance(message, dict) else None
        for block in content if isinstance(content, list) else ():
            if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
                found.append(_flat(block["text"]))
    return found


def _figure_in(quote: str, value: float) -> Decimal | None:
    """The number in the quote that is this value, as the quote wrote it, since that says how exactly it was reported."""
    wanted = abs(Decimal(str(value)))
    for match in _NUMBER.findall(quote):
        with_no_commas = match.replace(",", "")
        try:
            if Decimal(with_no_commas) == wanted:
                return Decimal(with_no_commas)
        except InvalidOperation:
            continue
    return None


def _shows(recorded: object, reported: Decimal) -> bool:
    """Whether a recorded figure could be read as this one, rounded or cut to its digits, as itself or as a percent; a near miss goes to Daniel."""
    if not isinstance(recorded, int | float) or isinstance(recorded, bool):
        return False
    within = Decimal(1).scaleb(reported.as_tuple().exponent)  # type: ignore[arg-type]
    figure = abs(Decimal(str(recorded)))
    return abs(figure - reported) <= within or abs(figure * 100 - reported) <= within


def _record_shows(events: list[dict], subject: Subject, reported: Decimal) -> bool:
    """Whether a record of this bet made by the session's end shows the figure: a later one cannot excuse what was said before it."""
    writer = f"{treasurer.CELL_PREFIX}{subject.bet}"
    registered = {event["seq"] for event in events if event["kind"] == "strategy-registered" and event["writer"] == writer}
    for event in events:
        if event["seq"] > subject.end_seq or event["kind"] not in _FIGURES or event["registration_seq"] not in registered:
            continue
        if any(_shows(event.get(name), reported) for name in _FIGURES[event["kind"]]):
            return True
    return False


def code_confirms(events: list[dict], finding: dict) -> bool:
    """Whether code agrees that the audited cell said what the finding's claim quotes, and that no record of its bet showed it."""
    claim, session = finding.get("claim"), finding.get("session")
    if not is_claim(claim) or finding["rubric"] != UNSHOWN_RESULT or session is None or finding.get("bet") is None:
        return False
    started = next((event for event in events if event["kind"] == "session-started" and event["session"] == session), None)
    if started is None:
        return False
    try:
        subject = _subject(events, started)
        replies = _replies(subject.transcript)
    except (NotAuditable, OSError):
        return False
    quote = _flat(claim["quote"])
    reported = _figure_in(quote, claim["value"])
    if reported is None or not any(quote in reply for reply in replies):
        return False
    return not _record_shows(events, subject, reported)
