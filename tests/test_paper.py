"""The paper account and the paper period, on a fake broker: every test here runs with no network, as the suite's guard enforces.

The command runs in this process wherever a test needs the broker, since `paper.transport` is the seam, and a child process would reach for the real one.

The worked period, on a registration whose in-sample and holdout bars are `quant_tools`', with SPY closing at 100 on the newest day:

    A strategy holding 1.0 of an account of $100,000 wants 100,000 / 100 = 1,000 shares.
    The first reading is the base, so equity of 100,500 reads as a profit of 500.
    Its registered `max_drawdown` of 0.6 is its kill: from a peak of 100,000, equity of 40,000 is exactly 0.6, and not past it; 39,999 is.
"""

import ast
import fcntl
import hashlib
import json
import os
import ssl
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import ClassVar
from urllib.parse import parse_qs, urlsplit

import pytest
from quant_tools import (
    HOLD,
    HOLDOUT_BARS,
    IN_SAMPLE_BARS,
    SESSION,
    CellTools,
    bar,
    registration,
    verdict_of,
    write_market,
)
from session_checks import events

from company import cli, paper, paths, schedule, times, tools
from company.ledger import AppendRefused, Ledger

KEY_ID = "FIXTUREKEYIDVALUE"
SECRET = "fixture-secret-never-printed-9f1c"
LIVE_HOST = "api." + "alpaca.markets"
LENIENT = {"min_deflated_sharpe": 0, "min_holdout_return": -1, "max_drawdown": 0.6}
TODAY_BAR = bar("2026-03-02", 100)
ORDER_PATHS = frozenset({"place_order", "cancel_orders"})
# Only these two may name the account, whose methods include the order path: `paper_period.py` trades it, and the command makes it.
ACCOUNT_USERS = frozenset({"paper.py", "paper_period.py", "cli.py"})
ORDER_USERS = frozenset({"paper.py", "paper_period.py"})
NETWORK_MODULES = frozenset({"http", "urllib", "socket", "ssl", "ftplib", "smtplib", "asyncio", "requests", "httpx", "aiohttp"})
NETWORK_USERS = frozenset({"paper.py"})


def wire_bar(item, symbol):
    fields = item["symbols"][symbol]
    return {"t": f"{item['date']}T05:00:00Z", "o": fields["open"], "h": fields["high"], "l": fields["low"], "c": fields["close"], "v": fields["volume"], "n": 1, "vw": fields["close"]}


class FakeBroker:
    """The broker's two hosts as its documents describe them, keeping every request and filling each order at once."""

    hosts = paper.HOSTS

    def __init__(self, equity="100000", market=None, page_size=10_000):
        self.equity, self.market, self.page_size = equity, market if market is not None else [*IN_SAMPLE_BARS, *HOLDOUT_BARS, TODAY_BAR], page_size
        self.requests = []
        self.positions = {}
        self.status = "ACTIVE"
        self.fail = {}
        self.next_order = 1

    def send(self, method, host, target, headers, body):
        split = urlsplit(target)
        self.requests.append({"method": method, "host": host, "path": split.path, "query": parse_qs(split.query), "headers": headers, "body": json.loads(body) if body else None})
        failure = self.fail.get((method, split.path))
        if failure is not None:
            return failure
        route = {
            ("GET", paper.PAPER_HOST, "/v2/account"): self._account,
            ("GET", paper.PAPER_HOST, "/v2/positions"): self._positions,
            ("DELETE", paper.PAPER_HOST, "/v2/orders"): lambda: (207, b"[]"),
            ("POST", paper.PAPER_HOST, "/v2/orders"): self._order,
            ("GET", paper.DATA_HOST, "/v2/stocks/bars"): self._bars,
        }.get((method, host, split.path))
        return (404, b"{}") if route is None else route()

    def _account(self):
        return 200, json.dumps({"status": self.status, "equity": self.equity, "account_number": "PA0000"}).encode()

    def _positions(self):
        held = [{"symbol": symbol, "qty": str(abs(quantity)), "side": "long" if quantity > 0 else "short", "market_value": "1"} for symbol, quantity in self.positions.items()]
        return 200, json.dumps(held).encode()

    def _order(self):
        order = self.requests[-1]["body"]
        change = Decimal(order["qty"]) * (1 if order["side"] == "buy" else -1)
        self.positions[order["symbol"]] = self.positions.get(order["symbol"], Decimal(0)) + change
        if self.positions[order["symbol"]] == 0:
            del self.positions[order["symbol"]]
        self.next_order += 1
        return 200, json.dumps({"id": f"order-{self.next_order}", "status": "accepted"}).encode()

    def _bars(self):
        query = self.requests[-1]["query"]
        symbols = query["symbols"][0].split(",")
        start, end = query["start"][0], query["end"][0]
        rows = [(symbol, item) for item in self.market for symbol in symbols if start <= item["date"] <= end and symbol in item["symbols"]]
        offset = int(query.get("page_token", ["0"])[0])
        page, rest = rows[offset : offset + self.page_size], rows[offset + self.page_size :]
        answer = {"bars": {}, "next_page_token": str(offset + self.page_size) if rest else None, "currency": "USD"}
        for symbol, item in page:
            answer["bars"].setdefault(symbol, []).append(wire_bar(item, symbol))
        return 200, json.dumps(answer).encode()

    def orders(self):
        return [request for request in self.requests if request["method"] == "POST"]

    def paths(self):
        return [request["path"] for request in self.requests]


@pytest.fixture
def broker(monkeypatch):
    chosen = FakeBroker()
    monkeypatch.setattr(paper, "transport", lambda: chosen)
    return chosen


@pytest.fixture
def key():
    return write_key()


def write_key(content=f"{KEY_ID}\n{SECRET}\n", mode=0o600):
    path = paths.paper_key()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(mode)
    return path


@pytest.fixture
def run(capsys):
    """The command in this process, on the chosen transport; gives the exit, what it printed and what it complained of."""

    def call(*arguments):
        capsys.readouterr()
        exit_code = cli.main(list(arguments))
        captured = capsys.readouterr()
        return exit_code, captured.out, captured.err

    return call


@pytest.fixture
def clock(monkeypatch):
    """Move the time a tick reads, with no change to the time the ledger stamps."""

    def move(day):
        when = datetime.combine(day, datetime.min.time(), tzinfo=UTC).replace(hour=22)
        monkeypatch.setattr(times, "now", lambda: when)

    return move


def pass_a_verdict(code=HOLD, bet="alpha", **changes):
    market_bars = changes.pop("market_bars", None)
    write_market(bars=market_bars or (*IN_SAMPLE_BARS, *HOLDOUT_BARS))
    opened = CellTools(bet=bet)
    try:
        answer = opened.register(**{"acceptance": LENIENT, **changes})
        assert not answer["isError"], answer
        strategy = changes.get("strategy", "momentum")
        verdict = verdict_of(opened, opened.backtest(code, strategy=strategy)["config_hash"], strategy)
    finally:
        opened.close()
    return verdict


@pytest.fixture
def period(board):
    """Daniel's settings, and a passing strategy that opened a period."""
    verdict = pass_a_verdict()
    assert verdict["passed"], verdict
    return events("paper-opened")[-1]


def everything_written():
    """Every file in the company home and the config directory but the key, moved aside or not, as bytes."""
    found = b""
    for root in (paths.home(), paths.config()):
        for path in root.rglob("*"):
            if path.is_file() and not path.name.startswith(paths.PAPER_KEY):
                found += path.read_bytes()
    return found


def assert_no_key_anywhere(*printed):
    for text in (KEY_ID, SECRET):
        assert text.encode() not in everything_written()
        for output in printed:
            assert text not in output


# Opening a period


def test_a_passing_verdict_opens_a_period_with_its_end_date_kill_and_promise(board):
    verdict = pass_a_verdict(paper_days=30)

    opened = events("paper-opened")
    assert len(opened) == 1
    expected_end = (date.today() + timedelta(days=30)).isoformat()
    assert opened[0]["writer"] == "runner"
    assert opened[0]["verdict_seq"] == verdict["event"]
    assert opened[0]["end_date"] == expected_end
    assert opened[0]["drawdown_kill"] == 0.6
    promise = next(event for event in events("promise-recorded") if event["seq"] == opened[0]["promise_seq"])
    assert promise["due_date"] == expected_end


def test_the_runners_promise_for_the_end_date_always_sets_the_bet(board):
    pass_a_verdict(bet="beta-bet")

    promises = events("promise-recorded")
    assert [(event["writer"], event["bet"]) for event in promises] == [("runner", "beta-bet")]


def test_a_period_of_no_stated_length_is_the_ninety_days_the_design_says(board):
    pass_a_verdict()

    assert events("paper-opened")[0]["end_date"] == (date.today() + timedelta(days=90)).isoformat()


def test_a_failed_verdict_opens_nothing(board):
    verdict = pass_a_verdict(acceptance={**LENIENT, "min_holdout_return": 100})

    assert not verdict["passed"]
    assert events("paper-opened") == []
    assert events("promise-recorded") == []


@pytest.mark.parametrize("days", [0, -1, 3651, 10**12, True, 1.5])
def test_a_paper_period_no_date_could_hold_is_refused_at_the_registration(market, days):
    opened = CellTools()
    try:
        answer = opened.register(paper_days=days)
    finally:
        opened.close()

    assert answer["isError"]
    assert "bad-field:paper_days" in answer["content"][0]["text"]


@pytest.fixture
def market():
    return write_market()


def test_one_strategy_holds_the_account_and_the_next_opens_when_it_closes(board, broker, key, run, clock):
    days = [{**item, "date": day} for item, day in zip(HOLDOUT_BARS, ("2026-03-02", "2026-03-03", "2026-03-04"), strict=True)]
    all_bars = (*IN_SAMPLE_BARS, *HOLDOUT_BARS, *days)
    pass_a_verdict(market_bars=all_bars)
    pass_a_verdict(strategy="second", holdout={"start": "2026-03-02", "end": "2026-03-04"}, market_bars=all_bars)

    assert len(events("verdict")) == 2
    first = events("paper-opened")
    assert [event["verdict_seq"] for event in first] == [events("verdict")[0]["seq"]]

    clock(date.fromisoformat(first[0]["end_date"]))
    exit_code, out, err = run("paper", "tick")

    assert exit_code == 0, err
    opened = events("paper-opened")
    assert [event["verdict_seq"] for event in opened] == [event["seq"] for event in events("verdict")]
    assert events("paper-closed")[0]["period_seq"] == first[0]["seq"]
    assert f"PAPER period {opened[1]['seq']} opened" in out
    assert len(events("promise-recorded")) == 2


def test_a_tick_opens_a_passed_verdict_that_could_not_open_its_period(board, broker, key, run, period):
    """A crash between the verdict and its period loses nothing: built by hand here, since the verdict's own path opens it at once."""
    Ledger().append("paper-closed", {"period_seq": period["seq"], "reason": "end-date", "equity": "100000"}, "runner")
    first = events("verdict")[0]
    fields = {name: value for name, value in first.items() if name not in ("seq", "ts", "kind", "writer", "prev")}
    Ledger().append("verdict", fields, "treasurer")

    exit_code, _, err = run("paper", "tick")

    assert exit_code == 0, err
    assert len(events("paper-opened")) == 2
    assert events("paper-opened")[1]["verdict_seq"] == events("verdict")[1]["seq"]


# A tick: the reading and the Treasurer's metric


def test_the_first_tick_reads_the_account_as_the_base(period, broker, key, run):
    exit_code, out, err = run("paper", "tick")

    assert exit_code == 0, err
    reading = events("paper-reading")[-1]
    assert (reading["period_seq"], reading["equity"], reading["pnl"], reading["writer"]) == (period["seq"], "100000", "0", "runner")
    assert times.parse_stamp(reading["taken_at"]) is not None
    assert "equity $100,000.00, profit and loss $0.00" in out


def test_a_later_tick_reads_profit_and_loss_against_that_base(period, broker, key, run):
    run("paper", "tick")
    broker.equity = "100500.25"
    run("paper", "tick")
    assert events("paper-reading")[-1]["pnl"] == "500.25"

    broker.equity = "99000"
    _, out, _ = run("paper", "tick")
    assert events("paper-reading")[-1]["pnl"] == "-1000"
    assert "profit and loss -$1,000.00" in out


def test_the_digest_shows_paper_profit_and_loss_as_the_metric_and_calls_it_paper(period, broker, key, run, company):
    run("paper", "tick")
    broker.equity = "100500"
    run("paper", "tick")

    page = company("digest").stdout

    bets = page.split("## Bets")[1].split("## Resources")[0]
    assert f"PAPER results, no real money: alpha, strategy momentum: profit and loss $500.00 on equity $100500.00 at {events('paper-reading')[-1]['taken_at']}; open until {period['end_date']}, drawdown kill 60%" in bets


def test_a_period_citing_no_registration_does_not_stop_the_page(board, company):
    Ledger().append("paper-opened", {"registration_seq": 1, "verdict_seq": 1, "end_date": "2027-01-01", "drawdown_kill": 0.2}, "runner")

    done = company("digest")

    assert done.returncode == 0, done.stderr
    assert "PAPER results, no real money: unknown, strategy unknown: no reading yet" in done.stdout


def test_a_loss_reads_as_a_loss_and_a_period_with_no_reading_says_so(period, broker, key, run, company):
    assert "PAPER results, no real money: alpha, strategy momentum: no reading yet; open until" in company("digest").stdout

    run("paper", "tick")
    broker.equity = "99000"
    run("paper", "tick")

    assert "profit and loss -$1000.00 on equity $99000.00" in company("digest").stdout


def test_a_closed_period_says_how_it_ended_in_the_digest(period, broker, key, run, company, clock):
    clock(date.fromisoformat(period["end_date"]))
    run("paper", "tick")

    assert "closed: end-date" in company("digest").stdout


def test_paper_results_are_no_money_in_any_bar_or_margin(period, broker, key, run, company):
    run("paper", "tick")
    broker.equity = "900000"
    run("paper", "tick")

    page = company("digest").stdout

    assert "Net revenue: $0.00" in page
    assert "Bar reached: 0" in page


# Paper results are labelled


def test_every_line_a_tick_prints_is_labelled_paper(period, broker, key, run):
    _, placing, _ = run("paper", "tick")
    broker.equity = "120000"
    _, again, _ = run("paper", "tick")
    for output in (placing, again):
        for line in output.splitlines():
            assert "PAPER" in line, line
            assert "no real money" in line, line


def test_a_tick_with_nothing_open_is_labelled_and_calls_nobody(board, broker, key, run):
    exit_code, out, _ = run("paper", "tick")

    assert exit_code == 0
    assert out == "PAPER, no real money: no paper period is open, so this tick did nothing.\n"
    assert broker.requests == []


def test_the_check_is_labelled_paper(board, broker, key, run):
    _, out, _ = run("paper", "check")

    assert out == "PAPER, no real money: the paper account's status is ACTIVE, and its equity is $100,000.00.\n"


# The drawdown kill


@pytest.mark.parametrize(("equity", "closes"), [("40000", False), ("39999.99", True)])
def test_only_past_its_drawdown_kill_does_a_tick_close(period, broker, key, run, equity, closes):
    run("paper", "tick")
    held = dict(broker.positions)
    assert held
    broker.equity = equity

    exit_code, out, err = run("paper", "tick")

    assert exit_code == 0, err
    closed = events("paper-closed")
    if closes:
        assert [(event["period_seq"], event["reason"], event["equity"]) for event in closed] == [(period["seq"], "drawdown-kill", "39999.99")]
        assert broker.positions == {}
        assert f"PAPER period {period['seq']} closed, no real money: drawdown-kill." in out
    else:
        assert closed == []
        assert broker.positions != {}


def test_the_kill_counts_from_the_highest_reading_and_not_the_first(period, broker, key, run):
    run("paper", "tick")
    broker.equity = "200000"
    run("paper", "tick")
    broker.equity = "79999"

    run("paper", "tick")

    assert events("paper-closed")[0]["reason"] == "drawdown-kill"


def test_a_kill_needs_neither_the_bars_nor_the_strategy(period, broker, key, run):
    run("paper", "tick")
    broker.equity = "1"
    broker.fail[("GET", "/v2/stocks/bars")] = (500, b"")

    exit_code, _, err = run("paper", "tick")

    assert exit_code == 0, err
    assert events("paper-closed")[0]["reason"] == "drawdown-kill"


# The end date


def test_the_day_before_the_end_date_a_tick_leaves_the_period_open(period, broker, key, run, clock):
    clock(date.fromisoformat(period["end_date"]) - timedelta(days=1))

    run("paper", "tick")

    assert events("paper-closed") == []


@pytest.mark.parametrize("late", [0, 5])
def test_the_first_tick_on_or_after_the_end_date_closes_its_positions_and_the_period(period, broker, key, run, clock, late):
    run("paper", "tick")
    assert broker.positions
    clock(date.fromisoformat(period["end_date"]) + timedelta(days=late))

    exit_code, out, err = run("paper", "tick")

    assert exit_code == 0, err
    assert broker.positions == {}
    assert [(event["reason"], event["period_seq"]) for event in events("paper-closed")] == [("end-date", period["seq"])]
    assert "end-date" in out
    assert events("paper-order")[-1]["side"] == "sell"


def test_a_tick_after_the_close_does_nothing_more(period, broker, key, run, clock):
    clock(date.fromisoformat(period["end_date"]))
    run("paper", "tick")
    requests = len(broker.requests)
    written = len(Ledger().read())

    exit_code, out, _ = run("paper", "tick")

    assert exit_code == 0
    assert "no paper period is open" in out
    assert len(broker.requests) == requests
    assert len(Ledger().read()) == written


def test_a_close_whose_order_fails_leaves_the_period_open_for_the_next_tick(period, broker, key, run, clock):
    run("paper", "tick")
    clock(date.fromisoformat(period["end_date"]))
    broker.fail[("POST", "/v2/orders")] = (403, b'{"message": "no"}')

    exit_code, _, err = run("paper", "tick")

    assert exit_code == 1
    assert "the broker answered 403 to POST /v2/orders" in err
    assert '"message"' not in err
    assert events("paper-closed") == []

    broker.fail.clear()
    assert run("paper", "tick")[0] == 0
    assert events("paper-closed")[0]["reason"] == "end-date"
    assert broker.positions == {}


def test_a_close_sells_a_long_and_buys_back_a_short(period, broker, key, run, clock):
    broker.positions = {"SPY": Decimal(10), "QQQ": Decimal(-5)}
    clock(date.fromisoformat(period["end_date"]))

    run("paper", "tick")

    assert sorted((event["symbol"], event["side"], event["quantity"]) for event in events("paper-order")) == [("QQQ", "buy", "5"), ("SPY", "sell", "10")]
    assert broker.positions == {}


# The strategy's orders


def test_a_tick_runs_the_strategy_and_places_its_order_by_code_on_the_paper_host(period, broker, key, run):
    exit_code, out, err = run("paper", "tick")

    assert exit_code == 0, err
    order = broker.orders()[0]
    assert order["host"] == paper.PAPER_HOST
    assert order["body"] == {"symbol": "SPY", "qty": "1000", "side": "buy", "type": "market", "time_in_force": "day"}
    logged = events("paper-order")[0]
    assert (logged["writer"], logged["period_seq"], logged["symbol"], logged["side"], logged["quantity"], logged["status"]) == ("runner", period["seq"], "SPY", "buy", "1000", "accepted")
    assert logged["broker_order_id"].startswith("order-")
    assert "PAPER order, no real money: buy 1000 SPY, accepted." in out


def test_a_tick_at_the_target_places_nothing(period, broker, key, run):
    run("paper", "tick")
    orders = len(broker.orders())

    _, out, _ = run("paper", "tick")

    assert len(broker.orders()) == orders
    assert "already holds the strategy's target" in out


def test_a_tick_replaces_whatever_the_last_left_waiting_before_it_orders(period, broker, key, run):
    run("paper", "tick")

    methods = [(request["method"], request["path"]) for request in broker.requests]
    assert methods.index(("DELETE", "/v2/orders")) < methods.index(("POST", "/v2/orders"))


def test_a_whole_share_is_the_smallest_order_and_a_weight_never_overdraws(board, broker, key, run):
    half = 'def decide(bar, parameters):\n    return {"SPY": 0.5}\n'
    pass_a_verdict(half)
    broker.market = [*IN_SAMPLE_BARS, *HOLDOUT_BARS, bar("2026-03-02", 33)]

    run("paper", "tick")

    # 0.5 x 100,000 / 33 = 1,515.15, so 1,515 shares.
    assert broker.orders()[0]["body"]["qty"] == "1515"


def test_a_position_crossing_zero_closes_first_and_turns_on_the_next_tick(board, broker, key, run):
    short = 'def decide(bar, parameters):\n    return {"SPY": -0.5}\n'
    pass_a_verdict(short)
    broker.positions = {"SPY": Decimal(10)}

    run("paper", "tick")
    assert broker.orders()[-1]["body"] == {"symbol": "SPY", "qty": "10", "side": "sell", "type": "market", "time_in_force": "day"}
    assert broker.positions == {}

    run("paper", "tick")
    assert broker.orders()[-1]["body"]["side"] == "sell"
    assert broker.orders()[-1]["body"]["qty"] == "500"
    assert broker.positions == {"SPY": Decimal(-500)}


def test_what_the_strategy_does_not_hold_is_sold_first_to_free_the_cash(period, broker, key, run):
    broker.positions = {"AAPL": Decimal("2.5")}

    run("paper", "tick")

    assert [(order["body"]["symbol"], order["body"]["side"], order["body"]["qty"]) for order in broker.orders()] == [("AAPL", "sell", "2.5"), ("SPY", "buy", "1000")]


def test_the_strategy_sees_every_day_since_its_in_sample_began_one_at_a_time_as_in_its_verdict(board, broker, key, run):
    count = """
seen = []
def decide(bar, parameters):
    seen.append(bar["date"])
    assert seen == sorted(seen)
    return {"SPY": min(len(seen) / 100, 1)}
"""
    pass_a_verdict(count)
    broker.page_size = 2

    run("paper", "tick")

    # Nine days fed, so a weight of 0.09: 0.09 x 100,000 / 100 = 90 shares.
    assert broker.orders()[0]["body"]["qty"] == "90"
    assert broker.paths().count("/v2/stocks/bars") > 1


def test_a_day_that_lacks_a_symbol_of_the_universe_is_left_out(board, broker, key, run):
    both = 'def decide(bar, parameters):\n    return {"SPY": 0.5, "QQQ": 0.5}\n'
    pass_a_verdict(both, universe=["SPY", "QQQ"])
    missing = {"date": "2026-03-03", "symbols": {"SPY": {"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}}}
    broker.market = [*IN_SAMPLE_BARS, *HOLDOUT_BARS, TODAY_BAR, missing]

    run("paper", "tick")

    # Priced at the last whole day, whose SPY closed at 100, and not at the lone day's 1.
    assert {order["body"]["symbol"]: order["body"]["qty"] for order in broker.orders()} == {"QQQ": "500", "SPY": "500"}


def test_a_strategy_that_fails_on_paper_closes_its_period_and_its_words_go_nowhere(board, broker, key, run):
    crashes = """
def decide(bar, parameters):
    if bar["date"] > "2026-02-28":
        raise RuntimeError("WORDS-OF-THE-STRATEGY")
    return {"SPY": 1.0}
"""
    pass_a_verdict(crashes)
    broker.positions = {"SPY": Decimal(10)}

    exit_code, out, err = run("paper", "tick")

    assert exit_code == 0, err
    assert events("paper-closed")[0]["reason"] == "strategy-failed:crashed"
    assert broker.positions == {}
    assert "WORDS-OF-THE-STRATEGY" not in out + err
    assert b"WORDS-OF-THE-STRATEGY" not in Ledger().path.read_bytes()


def test_a_lost_configuration_closes_its_period(period, broker, key, run):
    kept = next(paths.configurations().rglob("*.json"))
    kept.write_text("{}")

    assert run("paper", "tick")[0] == 0

    assert events("paper-closed")[0]["reason"] == "strategy-failed:configuration-lost"


def test_a_missing_sandbox_is_no_fault_of_the_strategys_and_closes_nothing(period, broker, key, run, monkeypatch, tmp_path):
    from company import quant

    monkeypatch.setattr(quant, "SYSTEM_PATH", str(tmp_path))

    exit_code, _, err = run("paper", "tick")

    assert exit_code == 1
    assert "no-confinement" in err
    assert events("paper-closed") == []
    assert broker.orders() == []


def test_no_bars_at_all_places_nothing_and_closes_nothing(period, broker, key, run):
    broker.market = []

    exit_code, _, err = run("paper", "tick")

    assert exit_code == 1
    assert "no day holding every symbol" in err
    assert broker.orders() == []
    assert events("paper-closed") == []


def test_an_account_that_is_not_active_is_read_and_not_traded(period, broker, key, run):
    broker.status = "ACCOUNT_UPDATED"

    exit_code, _, err = run("paper", "tick")

    assert exit_code == 1
    assert "status is ACCOUNT_UPDATED" in err
    assert broker.orders() == []
    assert events("paper-reading") == []


def test_a_second_tick_at_the_same_moment_is_refused(period, broker, key, run):
    fd = os.open(paths.home() / "paper.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        exit_code, _, err = run("paper", "tick")
    finally:
        os.close(fd)

    assert exit_code == 1
    assert "another paper tick is running" in err
    assert broker.requests == []


# What stops a tick


def test_the_kill_switch_stops_a_tick_and_a_check_before_any_call(period, broker, key, run, company, systemctl):
    assert company("kill", "--reason", "test").returncode == 0

    for command in ("tick", "check"):
        exit_code, _, err = run("paper", command)
        assert exit_code == 1
        assert "company resume" in err

    assert broker.requests == []


def test_a_pull_during_a_tick_stops_its_next_order(period, broker, key, run, monkeypatch):
    from company import kill_state

    monkeypatch.setattr(kill_state, "present", lambda: bool(broker.orders()))
    broker.positions = {"AAPL": Decimal(1)}

    exit_code, _, err = run("paper", "tick")

    assert exit_code == 1
    assert "pulled during this tick" in err
    assert [order["body"]["symbol"] for order in broker.orders()] == ["AAPL"]


def test_a_broken_ledger_stops_a_tick_and_a_check(period, broker, key, run):
    ledger = Ledger().path
    ledger.write_text(ledger.read_text().replace('"passed":true', '"passed":false'))

    for command in ("tick", "check"):
        assert run("paper", command)[0] == 1

    assert broker.requests == []


def test_settings_that_were_edited_stop_a_tick(period, broker, key, run):
    settings_file = paths.config() / "settings.json"
    settings_file.write_text(settings_file.read_text() + " ")

    exit_code, _, err = run("paper", "tick")

    assert exit_code == 1
    assert "did not run" in err
    assert broker.requests == []


@pytest.mark.parametrize("command", ["tick", "check"])
def test_inside_a_session_the_command_refuses_and_logs_it(period, broker, key, run, monkeypatch, command):
    monkeypatch.setenv("COMPANY_SESSION", SESSION)

    exit_code, _, err = run("paper", command)

    assert exit_code == 1
    assert "refused" in err
    assert broker.requests == []
    assert events("append-refused")[-1]["reason"] == "inside-a-session"


# The schedule


def test_the_tick_is_a_job_on_a_weekday_after_the_close(systemctl):
    job = schedule.job("paper-tick")

    assert job.command == ("paper", "tick")
    assert "Mon..Fri" in job.calendar


def test_the_tick_stays_off_with_the_schedule_so_daniel_runs_it_by_hand(period, broker, key, run):
    exit_code, _, err = run("schedule", "run", "paper-tick")

    assert exit_code == 1
    assert "the schedule is off" in err
    assert broker.requests == []
    assert events("paper-reading") == []

    assert run("paper", "tick")[0] == 0
    assert len(events("paper-reading")) == 1


def test_with_the_schedule_on_the_timer_runs_a_tick(period, broker, key, run, company, systemctl):
    assert company("schedule", "enable", "--message", "1234").returncode == 0
    assert "paper-tick" in events("schedule-enabled")[-1]["jobs"]

    assert run("schedule", "run", "paper-tick")[0] == 0

    assert len(events("paper-reading")) == 1


# Only code places an order


def order_path_users(root):
    """Each module, by name, that reaches the order path but may not: by the methods' names, or by naming the account class at all."""
    found = set()
    for path in Path(root).rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Attribute) and node.attr in ORDER_PATHS and path.name not in ORDER_USERS:
                found.add(path.name)
            if isinstance(node, ast.Attribute) and node.attr == "Account" and path.name not in ACCOUNT_USERS:
                found.add(path.name)
            if isinstance(node, ast.ImportFrom) and node.module == "company.paper" and any(alias.name == "Account" for alias in node.names) and path.name not in ACCOUNT_USERS:
                found.add(path.name)
            if isinstance(node, ast.ImportFrom) and node.module == "company" and any(alias.name == "paper_period" for alias in node.names) and path.name not in ("cli.py",):
                found.add(path.name)
    return sorted(found)


def test_only_the_tick_reaches_the_order_path(repo):
    assert order_path_users(repo / "src/company") == []


@pytest.mark.parametrize(
    "planted",
    [
        "def act(account):\n    account.place_order('SPY', 'buy', 1)\n",
        "def act(account):\n    account.cancel_orders()\n",
        "from company import paper\naccount = paper.Account(paper.transport())\n",
        "from company.paper import Account\n",
        "from company import paper_period\n",
    ],
)
def test_that_check_catches_another_order_path(tmp_path, planted):
    (tmp_path / "tools.py").write_text(planted)

    assert order_path_users(tmp_path) == ["tools.py"]


def test_no_company_tool_is_an_order(repo):
    for tool in tools.TOOLS.values():
        assert "order" not in tool.name
        assert tool.kind != "paper-order"
    assert not any(name.startswith("paper") for names in tools.ROLE_TOOLS.values() for name in names)


def test_the_tools_server_never_loads_the_tick():
    code = "import sys; import company.tools; print('company.paper_period' in sys.modules)"
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, timeout=30)

    assert done.stdout.strip() == "False"


def test_a_cell_going_from_its_registration_to_its_verdict_places_no_order(board, broker, key):
    market_data = paper.MarketData(broker)
    server = tools.Server("cell", "alpha", SESSION, 20, market_data)
    fields = registration(data_source=paper.BARS_SOURCE, acceptance=LENIENT)

    assert not server.call("register_strategy", fields)["isError"]
    backtest = json.loads(server.call("run_backtest", {"strategy": "momentum", "code": HOLD})["content"][0]["text"])
    answer = server.call("request_verdict", {"strategy": "momentum", "configuration": backtest["config_hash"]})

    assert not answer["isError"], answer
    assert len(events("paper-opened")) == 1
    assert {(request["method"], request["host"]) for request in broker.requests} == {("GET", paper.DATA_HOST)}
    assert events("paper-order") == []


def test_only_the_paper_module_may_reach_the_network(repo):
    found = {}
    for path in (repo / "src/company").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots = {node.module.split(".")[0]}
            else:
                continue
            if roots & NETWORK_MODULES and path.name not in NETWORK_USERS:
                found[path.name] = roots
    assert found == {}


# No path to a live account


@pytest.mark.parametrize("build", [paper.Account, paper.MarketData])
@pytest.mark.parametrize("reach", [frozenset({LIVE_HOST}), frozenset({paper.PAPER_HOST, LIVE_HOST}), frozenset({"example.com"}), {paper.PAPER_HOST}, None])
def test_a_transport_aimed_at_another_host_is_refused_before_the_key_is_read(build, reach, monkeypatch):
    class Elsewhere(FakeBroker):
        hosts = reach

    def no_read(_path):
        pytest.fail("the key was read")

    monkeypatch.setattr(paper, "_read_key", no_read)
    sender = Elsewhere()

    with pytest.raises(paper.ForeignTransport):
        build(sender)
    assert sender.requests == []


def test_a_transport_with_no_word_of_where_it_goes_is_refused():
    with pytest.raises(paper.ForeignTransport):
        paper.Account(object())


def test_the_real_transport_refuses_another_host_and_opens_no_connection():
    for host in (LIVE_HOST, "example.com", ""):
        with pytest.raises(paper.ForeignTransport):
            paper.HttpsTransport().send("GET", host, "/v2/account", {}, None)


class FakeConnection:
    """Stands where the standard library's connection would, so that what the real transport asks of it can be read."""

    made: ClassVar[list] = []
    failure = None

    def __init__(self, host, timeout=None, context=None):
        self.host, self.timeout, self.context, self.closed = host, timeout, context, False
        FakeConnection.made.append(self)

    def request(self, method, target, body=None, headers=None):
        if FakeConnection.failure is not None:
            raise FakeConnection.failure
        self.sent = (method, target, body, headers)

    def getresponse(self):
        return self

    status = 200

    def read(self, _limit):
        return b"{}"

    def close(self):
        self.closed = True


@pytest.fixture
def connection(monkeypatch):
    FakeConnection.made, FakeConnection.failure = [], None
    monkeypatch.setattr(paper.http.client, "HTTPSConnection", FakeConnection)
    return FakeConnection


def test_the_real_transport_goes_to_that_host_alone_with_a_checked_certificate_and_a_time_limit(connection):
    answer = paper.HttpsTransport().send("GET", paper.PAPER_HOST, "/v2/account", {"Accept": "x"}, None)

    assert answer == (200, b"{}")
    made = connection.made[0]
    assert made.host == paper.PAPER_HOST
    assert made.timeout > 0
    assert made.context.check_hostname
    assert made.context.verify_mode == ssl.CERT_REQUIRED
    assert made.sent == ("GET", "/v2/account", None, {"Accept": "x"})
    assert made.closed


def test_a_host_that_cannot_be_reached_is_a_failure_that_says_no_more_than_its_type(connection):
    connection.failure = OSError(f"reset while sending {SECRET}")

    with pytest.raises(paper.BrokerFailed) as failed:
        paper.HttpsTransport().send("GET", paper.DATA_HOST, "/v2/stocks/bars", {}, None)

    assert SECRET not in str(failed.value)
    assert "OSError" in str(failed.value)
    assert connection.made[0].closed


def test_the_command_says_so_of_a_transport_aimed_elsewhere(board, key, run, monkeypatch):
    class Elsewhere(FakeBroker):
        hosts = frozenset({LIVE_HOST})

    sender = Elsewhere()
    monkeypatch.setattr(paper, "transport", lambda: sender)

    exit_code, _, err = run("paper", "check")

    assert exit_code == 1
    assert "aimed at a host other than" in err
    assert LIVE_HOST not in err
    assert sender.requests == []


def test_a_redirect_is_a_failure_and_is_not_followed(board, broker, key, run):
    broker.fail[("GET", "/v2/account")] = (302, b"")

    exit_code, _, err = run("paper", "check")

    assert exit_code == 1
    assert "the broker answered 302" in err
    assert len(broker.requests) == 1


def test_each_call_goes_to_the_paper_or_data_host_alone(period, broker, key, run):
    run("paper", "tick")

    assert {request["host"] for request in broker.requests} == paper.HOSTS
    for request in broker.requests:
        assert (request["host"] == paper.DATA_HOST) == (request["path"] == "/v2/stocks/bars")


# The key


def test_the_key_is_sent_only_as_the_brokers_two_headers(period, broker, key, run):
    run("paper", "tick")

    for request in broker.requests:
        assert request["headers"][paper.KEY_ID_HEADER] == KEY_ID
        assert request["headers"][paper.SECRET_HEADER] == SECRET
        assert KEY_ID not in request["path"] and KEY_ID not in json.dumps(request["query"]) and KEY_ID not in json.dumps(request["body"])


def test_the_key_is_read_at_each_use(board, broker, key, run):
    run("paper", "check")
    write_key(f"ANOTHERKEYID\n{SECRET}\n")
    run("paper", "check")
    assert [request["headers"][paper.KEY_ID_HEADER] for request in broker.requests] == [KEY_ID, "ANOTHERKEYID"]

    key.unlink()
    assert run("paper", "check")[0] == 1
    assert len(broker.requests) == 2


@pytest.mark.parametrize("mode", [0o640, 0o604, 0o644, 0o660, 0o666, 0o601, 0o610])
def test_a_key_file_anyone_else_can_reach_is_refused_and_not_used(board, broker, run, mode):
    write_key(mode=mode)

    exit_code, _, err = run("paper", "check")

    assert exit_code == 1
    assert "chmod 600" in err
    assert broker.requests == []
    assert SECRET not in err


@pytest.mark.parametrize("mode", [0o600, 0o400])
def test_a_key_file_only_its_owner_can_reach_is_used(board, broker, run, mode):
    write_key(mode=mode)

    assert run("paper", "check")[0] == 0


def test_a_link_for_a_key_file_is_refused(board, broker, run, tmp_path):
    target = tmp_path / "elsewhere"
    target.write_text(f"{KEY_ID}\n{SECRET}\n")
    target.chmod(0o600)
    paths.config().mkdir(parents=True, exist_ok=True)
    paths.paper_key().symlink_to(target)

    exit_code, _, err = run("paper", "check")

    assert exit_code == 1
    assert "cannot be opened" in err
    assert broker.requests == []


@pytest.mark.parametrize("make", [os.mkfifo, os.mkdir])
def test_a_directory_or_pipe_for_a_key_file_is_refused_and_does_not_hang(board, broker, run, make):
    paths.config().mkdir(parents=True, exist_ok=True)
    make(paths.paper_key(), 0o600)

    exit_code, _, err = run("paper", "check")

    assert exit_code == 1
    assert "is not a file" in err
    assert broker.requests == []


@pytest.mark.parametrize("content", ["", "onlyonepart\n", "partone\nparttwo\npartthree\n", f"{KEY_ID} é\n"])
def test_a_key_file_that_is_no_key_is_refused_and_not_quoted(board, broker, run, content):
    write_key(content)

    exit_code, _, err = run("paper", "check")

    assert exit_code == 1
    assert "not a key id and a secret" in err
    assert broker.requests == []
    for part in content.split():
        assert part not in err


def test_the_key_is_in_no_ledger_line_log_or_output_through_a_period(period, broker, key, run, company, clock):
    printed = [*run("paper", "check")[1:], *run("paper", "tick")[1:]]
    broker.fail[("POST", "/v2/orders")] = (403, SECRET.encode())
    broker.fail[("GET", "/v2/positions")] = (500, SECRET.encode())
    printed += run("paper", "tick")[1:]
    broker.fail.clear()
    clock(date.fromisoformat(period["end_date"]))
    printed += run("paper", "tick")[1:]
    printed.append(company("digest").stdout)
    printed.append(company("ledger", "show").stdout)

    assert_no_key_anywhere(*printed)


def test_a_broker_that_echoes_the_key_does_not_get_it_printed(board, broker, key, run):
    broker.fail[("GET", "/v2/account")] = (401, json.dumps({"message": f"bad key {SECRET}"}).encode())

    _, out, err = run("paper", "check")

    assert_no_key_anywhere(out, err)


def test_the_key_is_in_no_session_environment_or_file(company, stub, board, market, key):
    stub.play(
        {"do": "tool", "name": "register_strategy", "arguments": registration(acceptance=LENIENT)},
        {"do": "tool", "name": "run_backtest", "arguments": {"strategy": "momentum", "code": HOLD}},
    )

    done = company("session", "start", "cell", "--bet", "alpha", "--prompt", "research")

    assert done.returncode == 0, done.stdout + done.stderr
    seen = json.dumps(stub.environment())
    assert KEY_ID not in seen and SECRET not in seen
    assert str(paths.paper_key()) not in seen
    assert_no_key_anywhere(done.stdout, done.stderr, json.dumps(stub.mcp_config()), json.dumps(stub.settings()))


def test_a_sessions_rules_deny_the_key(company, stub, board, market, key):
    stub.play()
    assert company("session", "start", "cell", "--bet", "alpha").returncode == 0

    settings = json.dumps(stub.settings())
    assert f"{paths.config()}/**" in settings


# With no key


def test_with_no_key_the_check_says_what_to_do_and_exits_non_zero(company):
    """The real command, in its own process, and the suite's guard fails it if it tries the network."""
    done = company("paper", "check")

    assert done.returncode == 1
    assert str(paths.paper_key()) in done.stderr
    assert "create the free paper account" in done.stderr
    assert "chmod 600" in done.stderr


def test_with_no_key_a_tick_places_nothing_and_says_what_to_do(period, broker, run):
    exit_code, _, err = run("paper", "tick")

    assert exit_code == 1
    assert "create the free paper account" in err
    assert broker.requests == []
    assert events("paper-reading") == []


def test_with_no_period_a_tick_needs_no_key(board, company):
    done = company("paper", "tick")

    assert done.returncode == 0, done.stderr


@pytest.mark.parametrize(
    ("path", "answer"),
    [
        ("/v2/account", (500, b"")),
        ("/v2/account", (200, b"not json")),
        ("/v2/account", (200, b"[]")),
        ("/v2/account", (200, b'{"status": "ACTIVE", "equity": "NaN"}')),
        ("/v2/account", (200, b'{"status": "ACTIVE", "equity": "Infinity"}')),
        ("/v2/account", (200, b'{"status": "ACTIVE", "equity": 100}')),
        ("/v2/account", (200, b'{"status": "ACTIVE", "equity": "lots"}')),
        ("/v2/account", (200, b'{"equity": "100"}')),
    ],
)
def test_an_account_that_cannot_be_read_stops_the_check_with_no_traceback(board, broker, key, run, path, answer):
    broker.fail[("GET", path)] = answer

    exit_code, out, err = run("paper", "check")

    assert exit_code == 1
    assert out == ""
    assert "was not read" in err


@pytest.mark.parametrize(
    "answer",
    [
        (200, b"{}"),
        (200, b"[1]"),
        (200, b'[{"symbol": "SPY", "qty": "many"}]'),
        (200, b'[{"qty": "1"}]'),
    ],
)
def test_positions_that_cannot_be_read_place_nothing(period, broker, key, run, answer):
    broker.fail[("GET", "/v2/positions")] = answer

    exit_code, _, err = run("paper", "tick")

    assert exit_code == 1
    assert "positions" in err or "quantity" in err
    assert broker.orders() == []


def test_an_order_answer_that_cannot_be_read_stops_the_tick(period, broker, key, run):
    broker.fail[("POST", "/v2/orders")] = (200, b'{"status": "accepted"}')

    exit_code, _, err = run("paper", "tick")

    assert exit_code == 1
    assert "no id and status" in err


# Market data, from either provider through one interface


def broker_tools(broker, bet="alpha"):
    return tools.Server("cell", bet, SESSION, 20, paper.MarketData(broker))


def test_the_brokers_bars_are_fetched_at_the_registration_and_hashed_into_the_ledger(broker, key):
    server = broker_tools(broker)

    answer = server.call("register_strategy", registration(data_source=paper.BARS_SOURCE))

    assert not answer["isError"], answer
    event = events("strategy-registered")[0]
    assert event["data_source"] == paper.BARS_SOURCE
    kept = paths.market_data() / "broker" / f"{event['data_hash']}.jsonl"
    assert hashlib.sha256(kept.read_bytes()).hexdigest() == event["data_hash"]
    request = broker.requests[0]
    assert (request["host"], request["path"]) == (paper.DATA_HOST, "/v2/stocks/bars")
    assert request["query"]["feed"] == ["iex"]
    assert request["query"]["timeframe"] == ["1Day"]
    assert request["query"]["symbols"] == ["SPY"]
    assert (request["query"]["start"], request["query"]["end"]) == (["2026-01-05"], ["2026-02-04"])


def test_a_fixture_and_the_broker_give_the_same_run_of_the_same_bars(broker, key):
    server = broker_tools(broker)

    assert not server.call("register_strategy", registration(data_source=paper.BARS_SOURCE))["isError"]
    from_broker = json.loads(server.call("run_backtest", {"strategy": "momentum", "code": HOLD})["content"][0]["text"])

    other = tools.Server("cell", "beta", SESSION, 20)
    write_market("same", [*(_plain(item) for item in IN_SAMPLE_BARS), *(_plain(item, day) for item, day in zip(HOLDOUT_BARS, ("2026-03-02", "2026-03-03", "2026-03-04"), strict=True))])
    assert not other.call("register_strategy", registration(data_source="fixture:same", holdout={"start": "2026-03-02", "end": "2026-03-04"}))["isError"]
    from_fixture = json.loads(other.call("run_backtest", {"strategy": "momentum", "code": HOLD})["content"][0]["text"])

    assert from_broker["returns_hash"] == from_fixture["returns_hash"]


def _plain(item, day=None):
    return {"date": day or item["date"], "symbols": {"SPY": {k: v for k, v in item["symbols"]["SPY"].items() if k != "note"}}}


def test_a_run_and_a_verdict_use_the_kept_bars_and_never_call_again(broker, key):
    server = broker_tools(broker)
    assert not server.call("register_strategy", registration(data_source=paper.BARS_SOURCE))["isError"]
    calls = len(broker.requests)

    backtest = json.loads(server.call("run_backtest", {"strategy": "momentum", "code": HOLD})["content"][0]["text"])
    answer = server.call("request_verdict", {"strategy": "momentum", "configuration": backtest["config_hash"]})

    assert not answer["isError"], answer
    assert len(broker.requests) == calls


@pytest.mark.parametrize("damage", ["edited", "gone"])
def test_kept_bars_that_changed_are_refused_as_any_source_is(broker, key, damage):
    server = broker_tools(broker)
    assert not server.call("register_strategy", registration(data_source=paper.BARS_SOURCE))["isError"]
    kept = next((paths.market_data() / "broker").iterdir())
    if damage == "edited":
        kept.write_text(kept.read_text().replace('"close":100', '"close":101'))
    else:
        kept.unlink()

    answer = server.call("run_backtest", {"strategy": "momentum", "code": HOLD})

    assert answer["isError"]
    assert events("config-refused")[-1]["reason"] == "data-changed"


def test_no_fixture_name_can_reach_the_kept_bars(broker, key):
    server = broker_tools(broker)
    assert not server.call("register_strategy", registration(data_source=paper.BARS_SOURCE))["isError"]
    name = events("strategy-registered")[0]["data_hash"]

    for source in (f"fixture:{name}", f"fixture:broker/{name}", f"fixture:../market-data/broker/{name}"):
        answer = server.call("register_strategy", registration(strategy="other", data_source=source, holdout={"start": "2026-01-08", "end": "2026-01-09"}, in_sample={"start": "2026-01-05", "end": "2026-01-06"}))
        assert answer["isError"]


def test_a_broker_source_on_a_holdout_held_on_a_fixture_is_refused_with_no_call(broker, key, market):
    fixture_side = tools.Server("cell", "beta", SESSION, 20)
    assert not fixture_side.call("register_strategy", registration())["isError"]

    answer = broker_tools(broker).call("register_strategy", registration(strategy="second", data_source=paper.BARS_SOURCE))

    assert answer["isError"]
    assert events("append-refused")[-1]["reason"] == "holdout-already-held"
    assert broker.requests == []


@pytest.mark.parametrize(
    ("setup", "reason"),
    [
        ("no-key", "data-unavailable:no-key"),
        ("key-open", "data-unavailable:no-key"),
        ("broker-fails", "data-unavailable:broker-failed"),
        ("bad-bars", "data-unavailable:broker-failed"),
        ("no-bars", "data-unavailable:not-covered"),
    ],
)
def test_bars_that_cannot_be_had_refuse_the_registration_and_say_why(broker, setup, reason):
    if setup != "no-key":
        write_key(mode=0o644 if setup == "key-open" else 0o600)
    if setup == "broker-fails":
        broker.fail[("GET", "/v2/stocks/bars")] = (500, b"")
    if setup == "bad-bars":
        broker.fail[("GET", "/v2/stocks/bars")] = (200, json.dumps({"bars": {"SPY": [{"t": "2026-01-05T05:00:00Z", "c": -1}]}}).encode())
    if setup == "no-bars":
        broker.market = []

    answer = broker_tools(broker).call("register_strategy", registration(data_source=paper.BARS_SOURCE))

    assert answer["isError"]
    assert events("strategy-registered") == []
    assert events("append-refused")[-1]["reason"] == reason
    assert_no_key_anywhere(answer["content"][0]["text"])


def test_a_day_lacking_a_registered_symbol_leaves_the_registration_not_covered(broker, key):
    broker.market = [*IN_SAMPLE_BARS[:-1], {"date": "2026-01-09", "symbols": {"QQQ": IN_SAMPLE_BARS[-1]["symbols"]["QQQ"]}}, *HOLDOUT_BARS]

    answer = broker_tools(broker).call("register_strategy", registration(data_source=paper.BARS_SOURCE, universe=["SPY", "QQQ"]))

    assert answer["isError"]
    assert events("append-refused")[-1]["reason"] == "data-unavailable:not-covered"


def test_a_holdout_reaching_today_is_not_covered_since_its_bar_is_not_whole(broker, key):
    today = times.now().date().isoformat()

    answer = broker_tools(broker).call("register_strategy", registration(data_source=paper.BARS_SOURCE, holdout={"start": "2026-02-02", "end": today}))

    assert answer["isError"]
    assert events("append-refused")[-1]["reason"] == "data-unavailable:not-covered"
    assert broker.requests == []


def test_a_server_with_no_key_path_has_no_broker_source(market):
    answer = tools.Server("cell", "alpha", SESSION, 20).call("register_strategy", registration(data_source=paper.BARS_SOURCE))

    assert answer["isError"]
    assert events("append-refused")[-1]["reason"] == "data-unavailable:no-such-source"


def test_every_page_of_the_brokers_bars_is_read(broker, key):
    broker.page_size = 2

    bars = paper.MarketData(broker).bars(["SPY", "QQQ"], "2026-01-05", "2026-02-04")

    assert [item["date"] for item in bars] == [item["date"] for item in (*IN_SAMPLE_BARS, *HOLDOUT_BARS)]
    assert all(set(item["symbols"]) == {"SPY", "QQQ"} for item in bars)
    assert len(broker.requests) > 2
    assert bars[0]["symbols"]["SPY"] == {"open": 100, "high": 100, "low": 100, "close": 100, "volume": 1000}


def test_a_broker_that_never_stops_paging_is_a_failure_and_not_a_hang(key):
    class Endless(FakeBroker):
        def send(self, method, host, target, headers, body):
            self.requests.append(target)
            return 200, b'{"bars": {}, "next_page_token": "more"}'

    sender = Endless()

    with pytest.raises(paper.BrokerFailed):
        paper.MarketData(sender).bars(["SPY"], "2026-01-05", "2026-01-06")
    assert len(sender.requests) == 200


# The kill switch and the key


def test_the_paper_key_is_an_outside_account_by_default_and_a_pull_rotates_it(company, board, key, systemctl):
    done = company("kill", "--reason", "test")

    assert done.returncode == 0, done.stdout + done.stderr
    step = next(event for event in events("kill-step") if event["step"] == "rotation")
    assert (step["target"], step["result"]) == ("paper", "moved-aside")
    assert not key.exists()
    assert list(key.parent.glob("paper.key.revoked-*"))
    assert_no_key_anywhere(done.stdout, done.stderr)


def test_after_a_pull_and_a_resume_the_key_stays_moved_and_the_check_says_what_to_do(company, board, key, systemctl):
    assert company("kill", "--reason", "test").returncode == 0
    assert company("resume").returncode == 0

    done = company("paper", "check")

    assert done.returncode == 1
    assert "there is no paper key" in done.stderr


# A contract's new field


def test_a_reading_of_a_loss_is_a_signed_decimal_and_rubbish_is_refused(period):
    fields = {"period_seq": period["seq"], "equity": "99000.50", "pnl": "-1000.25", "taken_at": "2026-11-05T09:30:00Z"}
    assert Ledger().append("paper-reading", fields, "runner")["pnl"] == "-1000.25"

    for bad in ({"pnl": "NaN"}, {"pnl": 5}, {"equity": "-1"}):
        with pytest.raises(AppendRefused, match="bad-field"):
            Ledger().append("paper-reading", {**fields, **bad}, "runner")
