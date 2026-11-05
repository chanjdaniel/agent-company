"""The Treasurer's one page, which Daniel reads each week; it writes nothing."""

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


def page(events: list[dict], share: treasurer.Share | str, terms: treasurer.Terms, now: datetime) -> str:
    """The page; `share` is the share, or why the usage records behind it cannot be read."""
    ladder = treasurer.ladder(events, terms, now)
    week = treasurer.last_seven_days(now)
    return _render(
        now,
        {
            "Bar": _bar(ladder),
            "Bets": [*_bets(events, ladder), *map(_paper_line, treasurer.paper_results(events))],
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


def minutes_phrase(amount) -> str:
    """An amount of minutes in words: "1 minute", "0.5 minutes"."""
    number = _minutes(amount)
    return f"{number} minute" if number == "1" else f"{number} minutes"


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
        f"No bar is claimed: the window opening {times.stamp(start)} holds a session that no charge has counted, so its cost is unknown"
        for start in ladder.uncharged
    ]
    if ladder.margin is None:
        return [*lines, "Margin against the next bar: none, this is the top bar"]
    bar = ladder.reached + 1
    name = f"Margin against bar {bar} ({treasurer.BARS[bar]})"
    if ladder.uncharged:
        return [*lines, f"{name}: at most {_dollars(ladder.margin)}"]
    return [*lines, f"{name}: {_dollars(ladder.margin)} (its line is {_dollars(ladder.bar_lines[bar])})"]


def _bet_line(name: str, figures: treasurer.Figures, at_most: bool) -> str:
    margin = f"at most {_dollars(figures.margin)}" if at_most else _dollars(figures.margin)
    return (
        f"{name}: margin {margin} (net revenue {_dollars(figures.net)}, "
        f"share cost {_dollars(figures.cost)}, dollars spent {_dollars(figures.spent)})"
    )


def _bets(events: list[dict], ladder: treasurer.Ladder) -> list[str]:
    if ladder.foreign:
        return _cannot_compute(ladder.foreign)
    # A window's unknown cost could belong to any line, and can only lower a margin.
    at_most = bool(ladder.uncharged)
    lines = [
        _bet_line(f"{bet} (closed)" if closed else bet, ladder.lines.get(bet, treasurer.Figures()), at_most)
        for bet, closed in treasurer.bets(events, ladder.lines).items()
    ]
    overhead = ladder.lines.get(treasurer.OVERHEAD, treasurer.Figures())
    return lines if overhead.is_zero else [*lines, _bet_line(treasurer.OVERHEAD, overhead, at_most)]


def _paper_line(result: treasurer.PaperResult) -> str:
    """A period's results, which are the cell's metric and no money, and say so."""
    period = result.period
    name = f"PAPER results, no real money: {result.bet}, strategy {result.strategy}"
    if result.reading is None:
        figures = "no reading yet"
    else:
        pnl, equity = Fraction(result.reading["pnl"]), Fraction(result.reading["equity"])
        figures = f"profit and loss {_dollars(pnl)} on equity {_dollars(equity)} at {result.reading['taken_at']}"
    if result.closed is not None:
        return f"{name}: {figures}; closed: {result.closed['reason']}"
    return f"{name}: {figures}; open until {period['end_date']}, drawdown kill {float(period['drawdown_kill']) * 100:g}%"


def _token_line(name: str, found, terms: treasurer.Terms) -> str:
    if isinstance(found, reading.Unreadable):
        return f"Tokens, {name}: cannot be read: {found.reason}: {found.detail}. Fix: `{reading.FIX}`."
    return (
        f"Tokens, {name}: company used {float(found.company_used):.2f}% "
        f"against a share of {float(terms.company_share * 100):.2f}%"
    )


def _dollars_line(events: list[dict], week: treasurer.Span) -> str:
    foreign = treasurer.foreign_money(events, week, ("spend",))
    if foreign:
        return "Dollars: " + _cannot_compute(foreign)[0]
    return f"Dollars: {_dollars(treasurer.spent(events, week))} spent in the last seven days, against a budget of none"


def _minutes_line(events: list[dict], terms: treasurer.Terms, week: treasurer.Span) -> str:
    line = f"Daniel-minutes: {_minutes(treasurer.minutes_total(events, week))} of {_minutes(terms.weekly_minutes)} in the last seven days"
    uncharged = treasurer.uncharged_decisions(events)
    if not uncharged:
        return line
    decisions = "1 decision is" if uncharged == 1 else f"{uncharged} decisions are"
    return f"{line}; {decisions} not charged yet: `company treasurer charge` charges them, or says why not"


def _token_lines(share: treasurer.Share | str, terms: treasurer.Terms) -> list[str]:
    if isinstance(share, str):
        return [f"Tokens: cannot be read: {share}"]
    windows = (("seven_day", share.seven_day), ("five_hour", share.five_hour))
    return [_token_line(name, found, terms) for name, found in windows if found is not None]


def _resources(events: list[dict], share: treasurer.Share | str, terms: treasurer.Terms, week: treasurer.Span) -> list[str]:
    tokens = _token_lines(share, terms)
    return [*tokens, _dollars_line(events, week), _minutes_line(events, terms, week)]


def _bet_note(event: dict) -> str:
    return f", bet {event['bet']}" if "bet" in event else ""


def _incidents(events: list[dict], week: treasurer.Span) -> list[str]:
    lines = []
    for event in events:
        if event["kind"] == "incident" and week.holds(event):
            lines.append(f"Event {event['seq']}: {event['class']}{_bet_note(event)}, caused by event {event['cause_seq']}")
    return lines


def _promises_line(events: list[dict]) -> str | None:
    """The cells' promises against those kept: a runner's promise is the code's, so it is left out either way."""
    made = {e["seq"] for e in events if e["kind"] == "promise-recorded" and e["writer"].startswith(treasurer.CELL_PREFIX)}
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
        minutes = minutes_phrase(ask["minutes"])
        lines.append(f"Event {ask['seq']}: {ask['action']}, {minutes}, expected margin {ask['expected_margin']}{_bet_note(ask)}")
    total = sum(Fraction(str(ask["minutes"])) for ask in asks)
    return [*lines, f"Total: {len(asks)} pending, {minutes_phrase(total)}"]
