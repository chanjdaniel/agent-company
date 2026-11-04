"""The Treasurer's numbers: pure functions over the ledger's events, the usage records and Daniel's settings."""

from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction

from company import reading, times, usage

OVERHEAD = "overhead"
_WEEKS_PER_YEAR = 52
_MONTHS_PER_YEAR = 12


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
    `five_hour` is None when no such reading exists, since a window may be absent. `company_cost` and `cost_lines`
    are None when the seven-day window cannot be read, since the cost comes from that window alone."""

    now: datetime
    seven_day: WindowShare | reading.Unreadable
    five_hour: WindowShare | reading.Unreadable | None
    weekly_price: Fraction
    company_cost: Fraction | None
    cost_lines: dict[str, Fraction] | None


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


def _cost_lines(week: WindowShare, cost: Fraction, records: usage.Records, sessions: dict, now: datetime) -> dict:
    """Each bet's part of the week's cost by its sessions' weight, with the sessions of no bet on the overhead line."""
    lines = {OVERHEAD: Fraction(0)}
    if not week.company_weight:
        return lines
    for session, weight in records.weights(week.reading.window_start, now).items():
        if session in sessions:
            line = sessions[session]
            lines[line] = lines.get(line, Fraction(0)) + cost * weight / week.company_weight
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
        return Share(now, week, five_hour, price, None, None)
    cost = week.company_used / 100 * price
    return Share(now, week, five_hour, price, cost, _cost_lines(week, cost, records, sessions, now))


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
