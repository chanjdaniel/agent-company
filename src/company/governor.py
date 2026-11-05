"""The governor: whether a session may start, checked in the design's order, stopping at the first refusal.

Only a refusal writes: `launch-refused`, with the reason, the share and the reading behind it.
Whatever cannot be read refuses, and never assumes room.
It cannot tell a stub from a real `claude`, so every launch it admits needs a `go-given` word, or the open schedule.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction

from company import (
    contract,
    honesty,
    kill_state,
    reading,
    schedule,
    settings,
    times,
    treasurer,
    usage,
)
from company.ledger import AppendRefused, Ledger, LedgerBroken

ROLES = ("probe", "cell", "strategy", "auditor", "retro")
GO_SCOPE = "real-sessions"
FIX_GO = f"company go {GO_SCOPE} --message <Discord id> --sessions <n>"
FIX_LEDGER = "company ledger verify"
FIX_NAME_BET = "name the cell's bet with --bet"
FIX_KILL = kill_state.RESUME
SCHEDULE_GATE = "schedule"


@dataclass(frozen=True)
class Admitted:
    """Room for one launch. `gate` is what `session-started` cites, and the numbers are the seven-day window's.

    `launches_left` is None for a scheduled session, which uses no word.
    """

    role: str
    bet: str | None
    gate: str
    launches_left: int | None
    account_used: float
    company_used: float
    reading_seq: int
    windows: tuple[treasurer.WindowShare, ...]


@dataclass(frozen=True)
class Refused:
    """No launch. `seq` is the `launch-refused` event, or None if the ledger could not take it."""

    role: str
    bet: str | None
    check: str
    reason: str
    fix: str
    seq: int | None


class _Stop(Exception):
    def __init__(self, check: str, reason: str, fix: str, numbers: dict | None = None):
        super().__init__(reason)
        self.check, self.reason, self.fix, self.numbers = check, reason, fix, numbers or {}


def _events(ledger: Ledger) -> list[dict]:
    try:
        verification = ledger.verify()
        if not verification.ok:
            raise _Stop("ledger", "broken: " + "; ".join(verification.problems), FIX_LEDGER)
        return ledger.read()
    except (LedgerBroken, OSError) as error:
        raise _Stop("ledger", f"broken: {error}", FIX_LEDGER) from None


def _not_killed(events: list[dict]) -> None:
    held = kill_state.refusal(events)
    if held:
        raise _Stop("kill", f"killed: {held}", FIX_KILL)


def _settings(log_tamper: bool = True) -> tuple[dict, Fraction, Fraction]:
    """The file, with the share as a percent and the floor; every number the later checks read is checked here."""
    try:
        loaded = settings.load(log_tamper)
        share = Fraction(str(settings.fraction(loaded, "company_share"))) * 100
        floor = Fraction(str(settings.percent(loaded, "team_floor")))
        settings.positive_number(loaded, "monthly_price")
        settings.positive_number(loaded, "reading_max_age_minutes")
        settings.day_dirs(loaded)
    except settings.SettingsRefused as refused:
        raise _Stop("settings", f"{refused.code}: {refused}", refused.fix) from None
    except (LedgerBroken, OSError) as error:
        raise _Stop("settings", f"unusable: the digest cannot be compared: {error}", FIX_LEDGER) from None
    return loaded, share, floor


def go_words(events: list[dict]) -> list[dict]:
    """Daniel's words for real launches, oldest first."""
    return [e for e in events if e["kind"] == "go-given" and e["scope"] == GO_SCOPE]


def open_word(events: list[dict]) -> tuple[str, int] | None:
    """The oldest word with launches left, and how many; a launch uses one by citing it in `session-started`."""
    used = Counter(e["gate"] for e in events if e["kind"] == "session-started")
    for word in go_words(events):
        gate = f"go:{word['seq']}"
        left = word["sessions"] - used[gate]
        if left > 0:
            return gate, left
    return None


def _go(events: list[dict]) -> tuple[str, int]:
    if not go_words(events):
        raise _Stop("go", "no-go: no go-given word is on record", FIX_GO)
    found = open_word(events)
    if found is None:
        raise _Stop("go", "go-used-up: every go-given word's launches are used", FIX_GO)
    return found


def _schedule_open(events: list[dict]) -> tuple[str, None]:
    """A scheduled session uses no word, and needs the schedule on."""
    if not schedule.enabled(events):
        raise _Stop("go", "schedule-off: a scheduled session needs the schedule on, and it is off", schedule.ENABLE)
    return SCHEDULE_GATE, None


def _not_paused(events: list[dict], role: str, bet: str | None) -> None:
    if bet is None:
        if role == "cell":
            raise _Stop("pause", "no-bet: a cell runs one bet, and with none named its pause cannot be read", FIX_NAME_BET)
        return
    if not contract.is_bet(bet):
        raise _Stop("pause", "bad-bet: the bet named is no bet's id, so its pause cannot be read", FIX_NAME_BET)
    pause = honesty.pause_in_effect(events, honesty.CELL_SCOPE, bet)
    if pause is not None:
        raise _Stop("pause", f"paused: the bet {bet} was paused by event {pause['seq']}", honesty.resume_command(bet))


def _unreadable(found: reading.Unreadable) -> _Stop:
    numbers = {} if found.seq is None else {"reading_seq": found.seq}
    return _Stop("reading", f"{found.reason}: {found.detail}", reading.FIX, numbers)


def _windows(events: list[dict], loaded: dict, now: datetime) -> tuple[treasurer.WindowShare, ...]:
    """The share of each window with a reading; anything wrong in reading them refuses, whatever it is."""
    try:
        max_age = settings.positive_number(loaded, "reading_max_age_minutes")
        records = usage.load(now - treasurer.WEEK, settings.day_dirs(loaded))
        result = treasurer.share(events, records, settings.positive_number(loaded, "monthly_price"), max_age, now)
    except Exception as error:  # noqa: BLE001 - a failure of any kind is a window that cannot be read, never room.
        raise _Stop("reading", f"read-error: the window's use cannot be read: {error}", reading.FIX) from None
    found = []
    for window in (result.seven_day, result.five_hour):
        if isinstance(window, reading.Unreadable):
            raise _unreadable(window)
        if window is not None:
            found.append(window)
    return tuple(found)


def _numbers(window: treasurer.WindowShare) -> dict:
    return {
        "account_used": float(window.reading.used_percent),
        "company_used": float(window.company_used),
        "reading_seq": window.reading.seq,
    }


def _under_floor(windows: tuple[treasurer.WindowShare, ...], floor: Fraction) -> None:
    for window in windows:
        seen = window.reading
        if seen.used_percent >= floor:
            reason = f"above-floor: the account has used {float(seen.used_percent):.2f}% of {seen.window}, at or past the floor of {float(floor):g}%"
            fix = f"wait for the reset at {times.stamp(seen.resets_at)}; only `{settings.SET} team_floor` moves the floor"
            raise _Stop("floor", reason, fix, _numbers(window))


def _under_share(windows: tuple[treasurer.WindowShare, ...], share: Fraction) -> None:
    for window in windows:
        seen = window.reading
        if window.company_used >= share:
            reason = f"share-used: the company has used {float(window.company_used):.2f}% of {seen.window}, at or past its share of {float(share):g}%"
            fix = f"wait for the reset at {times.stamp(seen.resets_at)}; only `{settings.SET} company_share` moves the share"
            raise _Stop("share", reason, fix, _numbers(window))


@dataclass(frozen=True)
class Blocked:
    """What would refuse a launch, for a report that promises to write nothing."""

    reason: str
    fix: str


def settings_blocked() -> Blocked | None:
    """What step 3 would say of the settings, with nothing logged."""
    try:
        _settings(log_tamper=False)
    except _Stop as stop:
        return Blocked(stop.reason, stop.fix)
    return None


def room_blocked(events: list[dict]) -> Blocked | None:
    """What steps 6 to 8 would say of the reading, the floor and the share, with nothing logged."""
    try:
        loaded, share, floor = _settings(log_tamper=False)
        windows = _windows(events, loaded, times.now().replace(microsecond=0))
        _under_floor(windows, floor)
        _under_share(windows, share)
    except _Stop as stop:
        return Blocked(stop.reason, stop.fix)
    return None


def _log(role: str, bet: str | None, stop: _Stop) -> int | None:
    fields = {"role": role, "check": stop.check, "reason": stop.reason, "fix": stop.fix, **stop.numbers}
    if contract.is_bet(bet):
        fields["bet"] = bet
    try:
        return Ledger().append("launch-refused", fields, "governor")["seq"]
    except (AppendRefused, LedgerBroken, OSError):
        return None


def admit(role: str, bet: str | None = None, scheduled: bool = False) -> Admitted | Refused:
    """Whether `role` may start now, for `bet`; this uses up nothing, since a launch does that by citing the `gate`."""
    if role not in ROLES:
        raise ValueError(f"no such role: {role}")
    now = times.now().replace(microsecond=0)
    try:
        events = _events(Ledger())
        _not_killed(events)
        loaded, share, floor = _settings()
        gate, left = _schedule_open(events) if scheduled else _go(events)
        _not_paused(events, role, bet)
        windows = _windows(events, loaded, now)
        _under_floor(windows, floor)
        _under_share(windows, share)
    except _Stop as stop:
        return Refused(role, bet, stop.check, stop.reason, stop.fix, _log(role, bet, stop))
    week = _numbers(windows[0])
    return Admitted(role, bet, gate, left, week["account_used"], week["company_used"], week["reading_seq"], windows)
