"""The one page Daniel reads each week: it prints the Treasurer's numbers and writes nothing."""

from datetime import datetime
from fractions import Fraction

from company import reading, times, treasurer

NONE = "none"
_SECTIONS = ("Bar", "Bets", "Resources", "Incidents", "Honesty", "Pending approvals")


def broken() -> str:
    """All a digest says over a broken chain: any number it could give would rest on the ledger that broke."""
    return "THE LEDGER IS BROKEN, so this digest prints no numbers. `company ledger verify` names what is wrong.\n"


def empty(now: datetime) -> str:
    return _render(now, {name: [] for name in _SECTIONS})


def page(events: list[dict], share: treasurer.Share, terms: treasurer.Terms, now: datetime) -> str:
    ladder = treasurer.ladder(events, terms, now)
    week = treasurer.last_seven_days(now)
    return _render(
        now,
        {
            "Bar": _bar(ladder),
            "Bets": _bets(events, ladder),
            "Resources": _resources(events, share, terms, week),
            "Incidents": _incidents(events, week),
            "Honesty": _honesty(events, week),
            "Pending approvals": _pending(events),
        },
    )


def _render(now: datetime, sections: dict[str, list[str]]) -> str:
    lines = [f"The company's digest at {times.stamp(now)}"]
    for name in _SECTIONS:
        lines += ["", f"## {name}", *(sections[name] or [NONE])]
    return "\n".join(lines) + "\n"


def _dollars(amount: Fraction) -> str:
    text = f"{abs(float(amount)):.2f}"
    return f"-${text}" if amount < 0 and text != "0.00" else f"${text}"


def _minutes(amount) -> str:
    return f"{float(amount):g}"


def _cannot_compute(seqs: tuple[int, ...]) -> list[str]:
    named = f"event {seqs[0]} is" if len(seqs) == 1 else "events " + ", ".join(map(str, seqs)) + " are"
    return [f"cannot be computed: {named} not in {treasurer.CURRENCY}"]


def _bar(ladder: treasurer.Ladder) -> list[str]:
    if ladder.foreign:
        return _cannot_compute(ladder.foreign)
    total = ladder.total
    window = f"the four windows from {times.stamp(ladder.month.start)} to {times.stamp(ladder.month.end)}"
    takings = f"revenue {_dollars(total.revenue)}, refunds {_dollars(total.refunds)}, fees {_dollars(total.fees)}"
    lines = [
        f"Bar reached: {ladder.reached} ({treasurer.BARS[ladder.reached]}), over {window}",
        f"Net revenue: {_dollars(total.net)} ({takings})",
        f"Against it: share cost {_dollars(total.cost)}, dollars spent {_dollars(total.spent)}",
    ]
    lines += [
        f"No bar is claimed: the window opening {times.stamp(start)} holds sessions and no charge, so its cost is unknown"
        for start in ladder.uncharged
    ]
    if ladder.margin is None:
        return [*lines, "Margin against the next bar: none, this is the top bar"]
    bar = ladder.reached + 1
    name = f"Margin against bar {bar} ({treasurer.BARS[bar]})"
    if ladder.uncharged:
        return [*lines, f"{name}: at most {_dollars(ladder.margin)}"]
    return [*lines, f"{name}: {_dollars(ladder.margin)} (its line is {_dollars(ladder.bar_lines[bar])})"]


def _bet_line(name: str, figures: treasurer.Figures) -> str:
    return (
        f"{name}: margin {_dollars(figures.margin)} (net revenue {_dollars(figures.net)}, "
        f"share cost {_dollars(figures.cost)}, dollars spent {_dollars(figures.spent)})"
    )


def _bets(events: list[dict], ladder: treasurer.Ladder) -> list[str]:
    if ladder.foreign:
        return _cannot_compute(ladder.foreign)
    lines = [
        _bet_line(f"{bet} (closed)" if closed else bet, ladder.lines.get(bet, treasurer.Figures()))
        for bet, closed in treasurer.bets(events, ladder.lines).items()
    ]
    overhead = ladder.lines.get(treasurer.OVERHEAD, treasurer.Figures())
    return lines if overhead.is_zero else [*lines, _bet_line(treasurer.OVERHEAD, overhead)]


def _token_line(name: str, found, terms: treasurer.Terms) -> str:
    if isinstance(found, reading.Unreadable):
        return f"Tokens, {name}: cannot be read: {found.reason}: {found.detail}. Fix: `{reading.FIX}`."
    return (
        f"Tokens, {name}: company used {float(found.company_used):.2f}% "
        f"against a share of {float(terms.company_share * 100):.2f}%"
    )


def _dollars_line(events: list[dict], week: treasurer.Span) -> str:
    foreign = treasurer.foreign_money(events, week)
    if foreign:
        return "Dollars: " + _cannot_compute(foreign)[0]
    return f"Dollars: {_dollars(_spent(events, week))} spent in the last seven days, against a budget of none"


def _spent(events: list[dict], week: treasurer.Span) -> Fraction:
    spends = (e for e in events if e["kind"] == "spend" and week.holds(e))
    return sum((Fraction(e["amount"]) for e in spends), Fraction(0))


def _minutes_line(events: list[dict], terms: treasurer.Terms, week: treasurer.Span) -> str:
    line = f"Daniel-minutes: {_minutes(treasurer.minutes_total(events, week))} of {_minutes(terms.weekly_minutes)} in the last seven days"
    uncharged = treasurer.uncharged_decisions(events)
    if not uncharged:
        return line
    decisions = "1 decision is" if uncharged == 1 else f"{uncharged} decisions are"
    return f"{line}; {decisions} not charged yet: run `company treasurer charge`"


def _resources(events: list[dict], share: treasurer.Share, terms: treasurer.Terms, week: treasurer.Span) -> list[str]:
    tokens = [
        _token_line(name, found, terms)
        for name, found in (("seven_day", share.seven_day), ("five_hour", share.five_hour))
        if found is not None
    ]
    return [*tokens, _dollars_line(events, week), _minutes_line(events, terms, week)]


def _incidents(events: list[dict], week: treasurer.Span) -> list[str]:
    lines = []
    for event in events:
        if event["kind"] == "incident" and week.holds(event):
            bet = f", bet {event['bet']}" if "bet" in event else ""
            lines.append(f"Event {event['seq']}: {event['class']}{bet}, caused by event {event['cause_seq']}")
    return lines


def _promises_line(events: list[dict]) -> str | None:
    """The cells' promises against those kept: a runner's promise is the code's, so it is left out either way."""
    made = {e["seq"] for e in events if e["kind"] == "promise-recorded" and e["writer"].startswith("cell:")}
    if not made:
        return None
    results = {e["promise_seq"]: e["result"] for e in events if e["kind"] == "promise-checked" and e["promise_seq"] in made}
    kept = sum(result == "kept" for result in results.values())
    failed = sum(result == "broken" for result in results.values())
    return f"Cells' promises: {len(made)} made, {kept} kept, {failed} broken, {len(made) - len(results)} open"


def _findings_line(events: list[dict], week: treasurer.Span) -> str | None:
    findings = [e for e in events if e["kind"] == "finding"]
    if not findings:
        return None
    confirmed = {e["finding_seq"] for e in events if e["kind"] == "finding-confirmed"}
    recent = sum(week.holds(e) for e in findings)
    unconfirmed = sum(e["seq"] not in confirmed for e in findings)
    return f"Findings: {recent} in the last seven days, {unconfirmed} unconfirmed in all"


def _count_line(events: list[dict], week: treasurer.Span, kind: str, name: str) -> str | None:
    count = sum(e["kind"] == kind and week.holds(e) for e in events)
    return f"{name}: {count} in the last seven days" if count else None


def _paused_line(events: list[dict]) -> str | None:
    paused: dict[tuple, str] = {}
    for event in events:
        key = (event.get("scope"), event.get("bet"))
        if event["kind"] == "cell-paused":
            paused[key] = f"cell {event.get('bet')}" if event["scope"] == "cell" else "all outside actions"
        elif event["kind"] == "cell-resumed":
            paused.pop(key, None)
    return "Paused now: " + ", ".join(paused.values()) if paused else None


def _honesty(events: list[dict], week: treasurer.Span) -> list[str]:
    lines = [
        _promises_line(events),
        _findings_line(events, week),
        _count_line(events, week, "complaint", "Complaints"),
        _count_line(events, week, "spam-flag", "Spam flags"),
        _count_line(events, week, "refund", "Refunds"),
        _paused_line(events),
    ]
    return [line for line in lines if line]


def _pending(events: list[dict]) -> list[str]:
    decided = {e["ask_seq"] for e in events if e["kind"] == "approval-decided"}
    asks = [e for e in events if e["kind"] == "approval-asked" and e["seq"] not in decided]
    if not asks:
        return []
    lines = []
    for ask in asks:
        bet = f", bet {ask['bet']}" if "bet" in ask else ""
        lines.append(f"Event {ask['seq']}: {ask['action']}, {_minutes(ask['minutes'])} minutes, expected margin {ask['expected_margin']}{bet}")
    total = sum(Fraction(str(ask["minutes"])) for ask in asks)
    return [*lines, f"Total: {len(asks)} pending, {_minutes(total)} minutes"]
