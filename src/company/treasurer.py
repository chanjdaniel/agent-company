"""The Treasurer's numbers: pure functions over the ledger's events, the usage records and Daniel's settings."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from fractions import Fraction

from company import reading, settings, times, usage

OVERHEAD = "overhead"
CURRENCY = "USD"
BARS = {0: "Running", 1: "Own share", 2: "Self-funding", 3: "Whole subscription"}
TOP_BAR = 3
SEND_ACTION = "message-send"
WEEK = timedelta(days=7)
_MONTH_WEEKS = 4
_WEEKS_PER_YEAR = 52
_MONTHS_PER_YEAR = 12
CELL_PREFIX = "cell:"
_MONEY_FIELDS = {"revenue": "revenue", "refund": "refunds", "fee": "fees", "spend": "spent"}
_SESSION_ENDS = ("session-ended", "session-stopped")


@dataclass(frozen=True)
class WindowShare:
    """The company's part of one window, whose `reading` gives the account's use."""

    reading: reading.Current
    company_weight: Fraction
    all_weight: Fraction
    fraction: Fraction
    company_used: Fraction


@dataclass(frozen=True)
class Share:
    """The share at a time. `seven_day` and `five_hour` are each a window's share, or why it cannot be read;
    `five_hour` is None when no such reading exists, since a window may be absent. `company_cost`, `cost_lines` and
    `line_weights` are None when the seven-day window cannot be read, since the cost comes from that window alone."""

    now: datetime
    seven_day: WindowShare | reading.Unreadable
    five_hour: WindowShare | reading.Unreadable | None
    weekly_price: Fraction
    company_cost: Fraction | None
    cost_lines: dict[str, Fraction] | None
    line_weights: dict[str, Fraction] | None


def weekly_price(monthly_price) -> Fraction:
    return Fraction(str(monthly_price)) * _MONTHS_PER_YEAR / _WEEKS_PER_YEAR


def company_sessions(events: list[dict]) -> dict[str, str]:
    """The company's sessions, those in a `session-started` event, each with its bet's id or the overhead line."""
    return {e["session"]: e.get("bet", OVERHEAD) for e in events if e.get("kind") == "session-started"}


def _window_share(found: reading.Current, records: usage.Records, sessions: dict, now: datetime) -> WindowShare:
    weights = records.weights(found.window_start, now)
    all_weight = sum(weights.values(), Fraction(0))
    company_weight = sum((weight for session, weight in weights.items() if session in sessions), Fraction(0))
    fraction = company_weight / all_weight if all_weight else Fraction(0)
    return WindowShare(found, company_weight, all_weight, fraction, fraction * found.used_percent)


def _line_weights(week: WindowShare, records: usage.Records, sessions: dict, now: datetime) -> dict[str, Fraction]:
    """Each bet's weight in the window, with the sessions of no bet on the overhead line."""
    lines = {OVERHEAD: Fraction(0)}
    for session, weight in records.weights(week.reading.window_start, now).items():
        if session in sessions:
            line = sessions[session]
            lines[line] = lines.get(line, Fraction(0)) + weight
    return lines


def share(events: list[dict], records: usage.Records, monthly_price, max_age_minutes, now: datetime) -> Share:
    sessions = company_sessions(events)

    def window(name: str) -> WindowShare | reading.Unreadable:
        found = reading.assess(name, events, records, max_age_minutes, now)
        return _window_share(found, records, sessions, now) if isinstance(found, reading.Current) else found

    week = window("seven_day")
    five_hour: WindowShare | reading.Unreadable | None = window("five_hour")
    if isinstance(five_hour, reading.Unreadable) and five_hour.reason == "no-reading":
        five_hour = None
    price = weekly_price(monthly_price)
    if isinstance(week, reading.Unreadable):
        return Share(now, week, five_hour, price, None, None, None)
    cost = week.company_used / 100 * price
    weights = _line_weights(week, records, sessions, now)
    lines = {line: cost * weight / week.company_weight if week.company_weight else Fraction(0) for line, weight in weights.items()}
    return Share(now, week, five_hour, price, cost, lines, weights)


def _report_window(name: str, found: WindowShare | reading.Unreadable | None) -> list[str]:
    if found is None:
        return [f"{name}: no reading"]
    if isinstance(found, reading.Unreadable):
        return [f"{name}: unreadable: {found.reason}: {found.detail}. Fix: `{reading.FIX}`."]
    seen = found.reading
    account = (
        f"{name}: account used {float(seen.used_percent):.2f}%: {float(seen.read_percent):.2f}% read at "
        f"{times.stamp(seen.taken_at)} by {seen.source} (event {seen.seq}), and {float(seen.added_percent):.2f}% since"
    )
    company = (
        f"{name}: list-price weight {float(found.company_weight):.6f} of {float(found.all_weight):.6f}, "
        f"fraction {float(found.fraction):.6f}, company used {float(found.company_used):.2f}%"
    )
    return [account, company]


def report(result: Share) -> str:
    """The share as Daniel reads it: no line calls a weight a cost, and the dollars are the share of the weekly price."""
    lines = [
        f"The company's share at {times.stamp(result.now)}",
        *_report_window("seven_day", result.seven_day),
        *_report_window("five_hour", result.five_hour),
    ]
    costs = result.cost_lines
    if result.company_cost is not None and costs is not None:
        lines += [
            f"Weekly price: ${float(result.weekly_price):.2f}",
            f"Company cost this week: ${float(result.company_cost):.2f}",
        ]
        lines += [f"  bet {bet}: ${float(costs[bet]):.2f}" for bet in sorted(costs) if bet != OVERHEAD]
        lines.append(f"  {OVERHEAD}: ${float(costs[OVERHEAD]):.2f}")
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class Terms:
    """What Daniel's settings say the ladder and the budgets are measured against; no value is compiled in."""

    monthly_price: Fraction
    company_share: Fraction
    new_bet_token_share: Fraction
    new_bet_dollars: Fraction
    daily_minutes: Fraction

    @classmethod
    def from_settings(cls, loaded: dict) -> "Terms":
        return cls(
            _exact(settings.positive_number(loaded, "monthly_price")),
            _exact(settings.fraction(loaded, "company_share")),
            _exact(settings.portfolio_fraction(loaded, "new_bet_token_share")),
            _exact(settings.portfolio_number(loaded, "new_bet_dollars")),
            _exact(settings.positive_number(loaded, "daily_minutes")),
        )

    @property
    def weekly_minutes(self) -> Fraction:
        return self.daily_minutes * 7


@dataclass(frozen=True)
class Span:
    """A stretch of time, holding `start` and not `end`."""

    start: datetime
    end: datetime

    def holds(self, event: dict) -> bool:
        return self.start <= _when(event) < self.end


@dataclass(frozen=True)
class Figures:
    """One line's money over a span: a bet's, the overhead's, or the whole company's."""

    revenue: Fraction = Fraction(0)
    refunds: Fraction = Fraction(0)
    fees: Fraction = Fraction(0)
    spent: Fraction = Fraction(0)
    cost: Fraction = Fraction(0)

    @property
    def net(self) -> Fraction:
        return self.revenue - self.refunds - self.fees

    @property
    def margin(self) -> Fraction:
        return self.net - self.cost - self.spent

    @property
    def is_zero(self) -> bool:
        return not any((self.revenue, self.refunds, self.fees, self.spent, self.cost))


@dataclass(frozen=True)
class Ladder:
    """The trailing month's bar. `foreign` holds money the sums cannot add, and then the rest means nothing;
    `uncharged` holds the opening of each window whose cost is unknown, and with any of them no bar is claimed."""

    month: Span
    lines: dict[str, Figures]
    total: Figures
    bar_lines: dict[int, Fraction]
    reached: int
    uncharged: tuple[datetime, ...]
    foreign: tuple[int, ...]

    @property
    def margin(self) -> Fraction | None:
        """Net revenue less the next bar's line, or None at the top bar."""
        return None if self.reached == TOP_BAR else self.total.net - self.bar_lines[self.reached + 1]


@dataclass(frozen=True)
class MinutesDue:
    """The `minutes-charged` events owed, and what kept a decision from being charged."""

    charges: list[dict]
    problems: list[str]


def _exact(value) -> Fraction:
    return Fraction(str(value))


def _when(event: dict) -> datetime:
    when = times.parse_stamp(event["ts"])
    if when is None:
        raise ValueError(f"event {event['seq']} has no readable time")
    return when


def _of_kind(events: list[dict], *kinds: str) -> list[dict]:
    return [event for event in events if event["kind"] in kinds]


def last_seven_days(now: datetime) -> Span:
    """The week a digest reads back over; an event stamped in `now`'s own second is in it."""
    return Span(now - WEEK, now + timedelta(seconds=1))


def _newest_complete_window_end(events: list[dict], now: datetime) -> datetime:
    """The account's windows, stepped from the newest reading that can be true; with none, they step back from `now`."""
    for event in reversed(_of_kind(events, "usage-reading")):
        if event.get("window") != "seven_day":
            continue
        resets_at, taken_at = times.parse_stamp(event.get("resets_at")), times.parse_stamp(event.get("taken_at"))
        if resets_at is not None and not reading.problem("seven_day", event.get("used_percent"), resets_at, taken_at, now):
            return resets_at + ((now - resets_at) // WEEK) * WEEK
    return now


def trailing_month(events: list[dict], now: datetime) -> Span:
    """The four most recent complete seven-day windows."""
    end = _newest_complete_window_end(events, now)
    return Span(end - _MONTH_WEEKS * WEEK, end)


def _window_index(week_start: str, month: Span) -> int:
    """Which of the month's windows a charge is for, 0 to 3 if any. Rounded, since a reset read by hand may be a minute off."""
    start = times.parse_stamp(week_start)
    if start is None:
        raise ValueError(f"a charge's week_start is no time: {week_start}")
    return round((start - month.start) / WEEK)


def _whole_charges(events: list[dict]) -> list[dict]:
    """The `resource-charged` lines of each charge that wrote them all: a charge stopped part way counts for nothing."""
    lines = _of_kind(events, "resource-charged")
    written = Counter(event["charge_id"] for event in lines)
    return [event for event in lines if written[event["charge_id"]] == event["charge_lines"]]


def _charges_by_window(events: list[dict], month: Span) -> dict[tuple[int, str], dict]:
    """The newest line of each window and line in the month, from whole charges: each is the window so far."""
    charges = {}
    for event in _whole_charges(events):
        index = _window_index(event["week_start"], month)
        if 0 <= index < _MONTH_WEEKS:
            charges[index, event["line"]] = event
    return charges


def foreign_money(events: list[dict], span: Span, kinds=tuple(_MONEY_FIELDS)) -> tuple[int, ...]:
    """The money events of `kinds` in `span` not in the company's currency: there is no rate to add them with."""
    return tuple(event["seq"] for event in _of_kind(events, *kinds) if span.holds(event) and event["currency"] != CURRENCY)


def spent(events: list[dict], span: Span) -> Fraction:
    """Dollars spent in `span`, in the company's currency."""
    spends = (e for e in _of_kind(events, "spend") if span.holds(e) and e["currency"] == CURRENCY)
    return sum((Fraction(e["amount"]) for e in spends), Fraction(0))


def figures(events: list[dict], month: Span) -> dict[str, Figures]:
    """Each line's money over the month: money with no bet is on the overhead line, so the lines add up to the company."""
    amounts: dict[str, dict[str, Fraction]] = defaultdict(lambda: defaultdict(Fraction))
    for event in _of_kind(events, *_MONEY_FIELDS):
        if month.holds(event) and event["currency"] == CURRENCY:
            amounts[event.get("bet", OVERHEAD)][_MONEY_FIELDS[event["kind"]]] += Fraction(event["amount"])
    for (_, line), charge in _charges_by_window(events, month).items():
        amounts[line]["cost"] += Fraction(charge["cost"])
    return {line: Figures(**found) for line, found in amounts.items()}


def _sum(lines) -> Figures:
    fields = ("revenue", "refunds", "fees", "spent", "cost")
    return Figures(*(sum((getattr(line, name) for line in lines), Fraction(0)) for name in fields))


@dataclass(frozen=True)
class _SessionRun:
    """A session as its events tell it: `end` is None until one says it has gone, since it may still be replying."""

    start: datetime
    end: datetime | None
    last_seq: int

    def ran_in(self, window: Span) -> bool:
        return self.start < window.end and (self.end is None or self.end >= window.start)


def _session_runs(events: list[dict]) -> list[_SessionRun]:
    by_session: dict[str, list[dict]] = defaultdict(list)
    for event in _of_kind(events, "session-started", *_SESSION_ENDS):
        by_session[event["session"]].append(event)
    runs = []
    for found in by_session.values():
        times_seen = [_when(event) for event in found]
        gone = any(event["kind"] in _SESSION_ENDS for event in found)
        runs.append(_SessionRun(min(times_seen), max(times_seen) if gone else None, max(event["seq"] for event in found)))
    return runs


def _uncharged_windows(events: list[dict], month: Span) -> tuple[datetime, ...]:
    """Each window of the month that a session ran in without having ended before its newest charge.

    A charge is the window so far, so what that session did after it is in no charge, and the window's cost is unknown.
    """
    newest: dict[int, int] = {}
    for (index, _), charge in _charges_by_window(events, month).items():
        newest[index] = max(newest.get(index, 0), charge["seq"])
    runs = _session_runs(events)
    uncharged = []
    for index in range(_MONTH_WEEKS):
        window = Span(month.start + index * WEEK, month.start + (index + 1) * WEEK)
        if any(run.ran_in(window) and (run.end is None or run.last_seq > newest.get(index, 0)) for run in runs):
            uncharged.append(window.start)
    return tuple(uncharged)


def ladder(events: list[dict], terms: Terms, now: datetime) -> Ladder:
    month = trailing_month(events, now)
    lines = figures(events, month)
    total = _sum(lines.values())
    covered = total.cost + total.spent
    trial = terms.new_bet_token_share * terms.company_share * weekly_price(terms.monthly_price) * _MONTH_WEEKS + terms.new_bet_dollars
    bar_lines = {1: covered, 2: covered + trial, 3: terms.monthly_price + total.spent}
    uncharged = _uncharged_windows(events, month)
    cleared = (bar for bar, line in bar_lines.items() if total.net > 0 and total.net >= line)
    reached = 0 if uncharged else max(cleared, default=0)
    return Ladder(month, lines, total, bar_lines, reached, uncharged, foreign_money(events, month))


def bets(events: list[dict], lines: dict[str, Figures]) -> dict[str, bool]:
    """The bets to report, each with whether it is closed: a closed bet with nothing in the month drops off."""
    known = {event["bet"] for event in _of_kind(events, "bet-admitted", "session-started") if "bet" in event}
    known |= set(lines) - {OVERHEAD}
    closed = {event["bet"] for event in _of_kind(events, "bet-closed")}
    return {
        bet: bet in closed
        for bet in sorted(known)
        if bet not in closed or not lines.get(bet, Figures()).is_zero
    }


def minutes_due(events: list[dict], table: dict) -> MinutesDue:
    """What each decision and send owes, once each; any decision took Daniel's time, whichever way it went."""
    by_seq = {event["seq"]: event for event in events}
    charged = _charged_subjects(events)
    charges, problems = [], []
    for event in _of_kind(events, "approval-decided", "send-confirmed"):
        if event["seq"] in charged:
            continue
        if event["kind"] == "send-confirmed":
            action, bet = SEND_ACTION, _cell_bet(by_seq.get(event["draft_seq"], {}))
        else:
            ask = by_seq.get(event["ask_seq"], {})
            if ask.get("kind") != "approval-asked":
                problems.append(f"event {event['seq']} cites no approval ask, so it was not charged")
                continue
            action, bet = ask["action"], ask.get("bet")
        if action not in table:
            problems.append(f"event {event['seq']}'s action {action} is not in the minutes table, so it was not charged")
            continue
        charge = {"action": action, "minutes": table[action], "subject_seq": event["seq"]}
        charges.append({**charge, "bet": bet} if bet else charge)
    return MinutesDue(charges, problems)


def _cell_bet(event: dict) -> str | None:
    writer = event.get("writer", "")
    return writer.removeprefix(CELL_PREFIX) if writer.startswith(CELL_PREFIX) else None


def _charged_subjects(events: list[dict]) -> set[int]:
    return {event["subject_seq"] for event in _of_kind(events, "minutes-charged")}


def uncharged_decisions(events: list[dict]) -> int:
    """How many decisions and sends have no charge yet."""
    charged = _charged_subjects(events)
    return sum(event["seq"] not in charged for event in _of_kind(events, "approval-decided", "send-confirmed"))


def minutes_by_subject(events: list[dict]) -> dict[int, Fraction]:
    """What each charged decision or send stands at: its estimate, or Daniel's newest correction, which replaces it.

    Every total of Daniel-minutes reads this. A subject charged twice, by two charges racing, counts once,
    and a correction of either charge holds.
    """
    subject_of: dict[int, int] = {}
    standing: dict[int, Fraction] = {}
    for event in _of_kind(events, "minutes-charged", "minutes-corrected"):
        if event["kind"] == "minutes-charged":
            subject_of[event["seq"]] = event["subject_seq"]
            standing.setdefault(event["subject_seq"], _exact(event["minutes"]))
        elif event["charge_seq"] in subject_of:
            standing[subject_of[event["charge_seq"]]] = _exact(event["minutes"])
    return standing


def minutes_total(events: list[dict], span: Span) -> Fraction:
    """Daniel-minutes spent in `span`: a charge counts when its decision or send was made, however late it was charged."""
    by_seq = {event["seq"]: event for event in events}
    return sum((minutes for subject, minutes in minutes_by_subject(events).items() if span.holds(by_seq[subject])), Fraction(0))


def week_charges_due(result: Share, events: list[dict]) -> list[dict]:
    """A `resource-charged` event for each line of the open window whose charge has changed; each is the window so far.

    A session started or ended since the newest charge writes every line, changed or not: with no reply of its own it
    moves no number, and only a charge after it can show that it was counted.
    """
    week = result.seven_day
    if not isinstance(week, WindowShare) or result.cost_lines is None or result.line_weights is None:
        return []
    week_start = times.stamp(week.reading.window_start)
    charges = [event for event in _whole_charges(events) if event["week_start"] == week_start]
    newest = {event["line"]: (event["weight"], event["cost"]) for event in charges}
    newest_seq = max((event["seq"] for event in charges), default=0)
    window = Span(week.reading.window_start, week.reading.resets_at)
    recount = any(run.ran_in(window) and run.last_seq > newest_seq for run in _session_runs(events))
    due = []
    for line in sorted(result.line_weights):
        weight = result.line_weights[line]
        share_of_all = weight / week.all_weight if week.all_weight else Fraction(0)
        cost = f"{float(result.cost_lines[line]):.6f}"
        if recount or newest.get(line) != (float(weight), cost):
            due.append(
                {
                    "week_start": week_start,
                    "line": line,
                    "weight": float(weight),
                    "fraction": float(share_of_all),
                    "company_used": float(share_of_all * week.reading.used_percent),
                    "cost": cost,
                    "reading_seq": week.reading.seq,
                }
            )
    return due
