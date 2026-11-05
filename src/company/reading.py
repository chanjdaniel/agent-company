"""The account's window use: readings kept in the ledger, and `current(window)`, which says what can be relied on.

Whatever cannot be read returns nothing, and never room: the governor refuses a launch on it.
"""

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from fractions import Fraction

from company import paths, settings, times, usage
from company.ledger import AppendRefused, Ledger, LedgerBroken

WINDOWS = {"seven_day": timedelta(days=7), "five_hour": timedelta(hours=5)}
_SHORT = {"seven_day": "7d", "five_hour": "5h"}
HAND = "hand"
STATUSLINE = "statusline"
FIX = "company reading record"
# Claude Code runs a status line after each reply, so a reading is kept far less often than it arrives.
_KEEP_EVERY = timedelta(minutes=5)


@dataclass(frozen=True)
class Current:
    """A usable reading, with the use since it added: `used_percent` is `read_percent` plus `added_percent`."""

    window: str
    used_percent: Fraction
    read_percent: Fraction
    added_percent: Fraction
    window_start: datetime
    resets_at: datetime
    taken_at: datetime
    source: str
    seq: int


@dataclass(frozen=True)
class Unreadable:
    """Why a window's use cannot be read: a code for each reason, with a sentence for Daniel, and the reading's event if there is one."""

    window: str
    reason: str
    detail: str
    seq: int | None = None


def _percent_problem(value) -> bool:
    return isinstance(value, bool) or not isinstance(value, int | float) or not 0 <= value <= 100


def problem(window: str, used_percent, resets_at: datetime | None, taken_at: datetime | None, now: datetime) -> str | None:
    """What makes these a reading that cannot be true, as a phrase; or None."""
    if _percent_problem(used_percent):
        return "its used percent is not a number from 0 to 100"
    if taken_at is None or taken_at > now:
        return "its time taken is unreadable or has not come"
    if resets_at is None or resets_at <= taken_at:
        return "it resets no later than it was taken, or its reset is unreadable"
    if resets_at - taken_at > WINDOWS[window]:
        return "it resets further off than the window is long"
    return None


def assess(window: str, events: list[dict], records: usage.Records, max_age_minutes, now: datetime) -> Current | Unreadable:
    """What the newest reading of `window` in `events` says at `now`, given the usage records."""
    length = WINDOWS[window]
    newest = next((e for e in reversed(events) if e.get("kind") == "usage-reading" and e.get("window") == window), None)
    if newest is None:
        return Unreadable(window, "no-reading", f"there is no {window} reading")

    seq = newest["seq"]
    resets_at, taken_at = times.parse_stamp(newest.get("resets_at")), times.parse_stamp(newest.get("taken_at"))
    wrong = problem(window, newest.get("used_percent"), resets_at, taken_at, now)
    if wrong is None and newest.get("source") not in (HAND, STATUSLINE):
        wrong = "its source is not one the company knows"
    if wrong or resets_at is None or taken_at is None:
        return Unreadable(window, "malformed", f"the newest {window} reading, event {seq}, is malformed: {wrong}", seq)
    if resets_at <= now:
        return Unreadable(window, "window-reset", f"the window of the newest {window} reading, event {seq}, has reset", seq)
    if now - taken_at > timedelta(minutes=max_age_minutes):
        detail = f"the newest {window} reading, event {seq}, is older than {max_age_minutes} minutes"
        return Unreadable(window, "stale", detail, seq)

    window_start = resets_at - length
    read_percent = Fraction(str(newest["used_percent"]))
    up_to = sum(records.weights(window_start, taken_at).values(), Fraction(0))
    since = sum(records.weights(taken_at, now).values(), Fraction(0))
    if since and not read_percent:
        detail = f"use has followed the newest {window} reading, event {seq}, which read zero percent"
        return Unreadable(window, "zero-percent", detail, seq)
    if since and not up_to:
        detail = f"use has followed the newest {window} reading, event {seq}, with no weight in the records up to it"
        return Unreadable(window, "no-weight", detail, seq)
    added = since * read_percent / up_to if since else Fraction(0)
    return Current(
        window, read_percent + added, read_percent, added, window_start, resets_at, taken_at, newest["source"], seq
    )


def assess_now(window: str, now: datetime | None = None) -> Current | Unreadable:
    """`assess` over the ledger, settings and usage records as they stand; a failure to read any of them raises."""
    if window not in WINDOWS:
        raise ValueError(f"no such window: {window}")
    moment = now or times.now()
    loaded = settings.load()
    max_age = settings.positive_number(loaded, "reading_max_age_minutes")
    records = usage.load(moment - WINDOWS[window], settings.day_dirs(loaded))
    return assess(window, Ledger().read(), records, max_age, moment)


def current(window: str, now: datetime | None = None) -> Current | None:
    """The account's use of `window` now, or nothing if it cannot be relied on."""
    found = assess_now(window, now)
    return found if isinstance(found, Current) else None


def record(window: str, used_percent: float, resets_at: datetime, now: datetime | None = None) -> dict:
    """Keep Daniel's reading from the usage page; raise `ValueError` for one that cannot be true, and keep nothing."""
    moment = (now or times.now()).replace(microsecond=0)
    wrong = problem(window, used_percent, resets_at, moment, moment)
    if wrong:
        raise ValueError(wrong)
    return _keep(window, used_percent, resets_at, moment, HAND, "board")


def _keep(window: str, used_percent, resets_at: datetime, taken_at: datetime, source: str, writer: str) -> dict:
    fields = {
        "window": window,
        "used_percent": used_percent,
        "resets_at": times.stamp(resets_at),
        "taken_at": times.stamp(taken_at),
        "source": source,
    }
    return Ledger().append("usage-reading", fields, writer)


def keep_statusline(text: str, now: datetime | None = None) -> str:
    """Keep the readings in a status line's input, and return the status text; a bad input never raises."""
    moment = (now or times.now()).replace(microsecond=0)
    shown, kept_all = [], True
    for window in ("seven_day", "five_hour"):
        found = _statusline_window(text, window, moment)
        if found is None:
            continue
        percent, resets_at = found
        shown.append(f"{_SHORT[window]} {round(percent)}%")
        try:
            _keep_unless_recent(window, percent, resets_at, moment)
        except (AppendRefused, LedgerBroken, OSError):
            kept_all = False
    if not shown:
        return "company: no window reading"
    return "company: " + " ".join(shown) + ("" if kept_all else " (not kept)")


def _statusline_window(text: str, window: str, now: datetime) -> tuple[int | float, datetime] | None:
    try:
        entry = json.loads(text)["rate_limits"][window]
        percent, epoch = entry["used_percentage"], entry["resets_at"]
        if isinstance(epoch, bool) or not isinstance(epoch, int | float):
            return None
        resets_at = datetime.fromtimestamp(epoch, UTC).replace(microsecond=0)
    except (ValueError, KeyError, TypeError, OverflowError, OSError, RecursionError):
        return None
    return None if problem(window, percent, resets_at, now, now) else (percent, resets_at)


def _read_state() -> dict:
    try:
        state = json.loads(_state_path().read_text())
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def _state_path():
    return paths.home() / "statusline.state"


def _kept_recently(last, resets_at: datetime, now: datetime) -> bool:
    if not isinstance(last, dict) or last.get("resets_at") != times.stamp(resets_at):
        return False
    taken_at = times.parse_stamp(last.get("taken_at"))
    return taken_at is not None and timedelta(0) <= now - taken_at < _KEEP_EVERY


def _keep_unless_recent(window: str, percent, resets_at: datetime, now: datetime) -> None:
    """Keep a reading once in `_KEEP_EVERY` per window, or at once for a new window; the state saves reading the ledger."""
    state = _read_state()
    if _kept_recently(state.get(window), resets_at, now):
        return
    _keep(window, percent, resets_at, now, STATUSLINE, "governor")
    state[window] = {"taken_at": times.stamp(now), "resets_at": times.stamp(resets_at)}
    path = _state_path()
    temporary = path.with_name(f"{path.name}.{os.getpid()}")
    temporary.write_text(json.dumps(state))
    temporary.replace(path)
