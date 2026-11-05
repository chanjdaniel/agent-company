"""The quant cell's registration and backtest runner, through the company tools over stdio, as a real session reaches them.

Every strategy here runs under the real `bwrap`, since it takes some 20 milliseconds and the code has no other way to run one.

The worked month, on one symbol, SPY, with a cost of 10 and a slippage of 5 basis points per unit of turnover (0.0015):

    date        close  next's move
    2026-01-05    100        +0.10
    2026-01-06    110        -0.10
    2026-01-07     99         0
    2026-01-08     99        +0.10
    2026-01-09  108.9        (the last in-sample bar: nothing follows, so no position is taken on it)

Holding 1.0 throughout turns over 1.0 only at the start, so its returns are 0.10 - 0.0015 = 0.0985, -0.10, 0, 0.10.
    n_returns: 4
    total_return: 1.0985 x 0.9 x 1 x 1.1 - 1 = 0.087515
    max_drawdown: the peak is 1.0985, the trough after it 1.0985 x 0.9, so 0.10
    mean: 0.0985 / 4 = 0.024625
    deviations: 0.073875, -0.124625, -0.024625, 0.075375, whose squares add to 0.0272766875
    sharpe: 0.024625 / sqrt(0.0272766875 / 3) = 0.024625 / 0.09535 = 0.25825
    skew and kurtosis: m3 / m2^1.5 and m4 / m2^2 of those deviations, as `WORKED_SKEW` and `WORKED_KURTOSIS` work them

Holding 1.0 on the first bar alone earns the first move less its cost, then pays the cost of leaving:
    returns 0.0985, -0.0015, 0, 0, so total_return is 1.0985 x 0.9985 - 1 = 0.09685225.
"""

import hashlib
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from session_checks import events, pid_is_running, wait_for

from company import paths, quant, treasurer
from company.ledger import AppendRefused, Ledger

SESSION = "eeeeeeee-0000-4000-8000-000000000000"
HOLDOUT_MARKER = "HOLDOUT-MARKER-71f3"
IN_SAMPLE_MARKER = "IN-SAMPLE-MARKER-2c9a"
# A close no in-sample bar has, so that a holdout price cannot pass unseen as a number.
HOLDOUT_CLOSE = 7777.77

_DEVIATIONS = (0.073875, -0.124625, -0.024625, 0.075375)
_M2 = sum(value**2 for value in _DEVIATIONS) / 4
WORKED_SKEW = (sum(value**3 for value in _DEVIATIONS) / 4) / _M2**1.5
WORKED_KURTOSIS = (sum(value**4 for value in _DEVIATIONS) / 4) / _M2**2

HOLD = 'def decide(bar, parameters):\n    return {"SPY": 1.0}\n'
HOLD_FIRST = """
seen = 0
def decide(bar, parameters):
    global seen
    seen += 1
    return {"SPY": 1.0 if seen == 1 else 0.0}
"""
FLAT = "def decide(bar, parameters):\n    return {}\n"
SCALED = 'def decide(bar, parameters):\n    return {"SPY": parameters["weight"]}\n'


def strategy_doing(action):
    """A strategy that tries this on its first bar, and whose failure says what came of it."""
    return f"def decide(bar, parameters):\n    {action}\n    return {{}}\n"


def bar(day, close, note=None):
    fields = {"open": close, "high": close, "low": close, "close": close, "volume": 1000}
    return {"date": day, "symbols": {"SPY": fields | ({"note": note} if note else {}), "QQQ": fields}}


IN_SAMPLE_BARS = [
    bar("2026-01-05", 100, IN_SAMPLE_MARKER),
    bar("2026-01-06", 110),
    bar("2026-01-07", 99),
    bar("2026-01-08", 99),
    bar("2026-01-09", 108.9),
]
HOLDOUT_BARS = [
    bar("2026-02-02", HOLDOUT_CLOSE, HOLDOUT_MARKER),
    bar("2026-02-03", HOLDOUT_CLOSE * 2, HOLDOUT_MARKER),
    bar("2026-02-04", HOLDOUT_CLOSE, HOLDOUT_MARKER),
]


def write_market(name="daily", bars=(*IN_SAMPLE_BARS, *HOLDOUT_BARS)):
    folder = paths.home() / "market-data"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.jsonl"
    path.write_text("".join(json.dumps(item) + "\n" for item in bars))
    return path


def registration(**changes):
    fields = {
        "strategy": "momentum",
        "universe": ["SPY"],
        "data_source": "fixture:daily",
        "in_sample": {"start": "2026-01-05", "end": "2026-01-09"},
        "holdout": {"start": "2026-02-02", "end": "2026-02-04"},
        "cost_model": {"bps_per_turnover": 10},
        "slippage_model": {"bps_per_turnover": 5},
        "max_configurations": 3,
        "acceptance": {"min_deflated_sharpe": 0.9, "min_holdout_return": 0, "max_drawdown": 0.2},
    }
    return {**fields, **changes}


class CellTools:
    """One cell's company tools over stdio, keeping everything the cell received."""

    def __init__(self, bet="alpha", seconds=20):
        arguments = ["-P", "-m", "company.tools", "--role", "cell", "--session", SESSION, "--bet", bet, "--backtest-seconds", str(seconds)]
        self.process = subprocess.Popen([sys.executable, *arguments], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.received = []
        self.next_id = 1

    def call(self, name, arguments):
        message = {"jsonrpc": "2.0", "id": self.next_id, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
        self.next_id += 1
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        self.received.append(line)
        return json.loads(line)["result"]

    def register(self, **changes):
        return self.call("register_strategy", registration(**changes))

    def backtest(self, code=HOLD, parameters=None, strategy="momentum"):
        """A backtest's answer, as the JSON the tool gave; a refusal has to be read with `call`."""
        answer = self.call("run_backtest", {"strategy": strategy, "code": code, "parameters": parameters or {}})
        assert not answer["isError"], answer
        return json.loads(answer["content"][0]["text"])

    def close(self):
        self.process.stdin.close()
        self.process.wait(timeout=10)


def text_of(answer):
    return answer["content"][0]["text"]


def refusals(kind):
    return [event for event in events("append-refused") if event["attempted_kind"] == kind]


@pytest.fixture
def market():
    return write_market()


@pytest.fixture
def tools(market):
    opened = CellTools()
    yield opened
    opened.close()


@pytest.fixture
def registered(tools):
    assert not tools.register()["isError"]
    return tools


@pytest.fixture
def quick(market):
    """Tools with a time limit of one second, for what hangs."""
    opened = CellTools(seconds=1)
    assert not opened.register(max_configurations=20)["isError"]
    yield opened
    opened.close()


# Registration


def test_a_registration_is_in_the_ledger_as_the_cell_with_the_data_hashed_by_the_tool(tools, market):
    answer = tools.register(paper_days=30)

    assert not answer["isError"], answer
    event = events("strategy-registered")[-1]
    assert event["writer"] == "cell:alpha"
    assert event["strategy"] == "momentum"
    assert event["universe"] == ["SPY"]
    assert event["max_configurations"] == 3
    assert event["paper_days"] == 30
    assert event["data_hash"] == hashlib.sha256(market.read_bytes()).hexdigest()
    assert str(event["seq"]) in text_of(answer)


def test_a_registration_with_no_paper_days_records_the_ninety_it_means(tools):
    tools.register()
    assert events("strategy-registered")[-1]["paper_days"] == 90


@pytest.mark.parametrize(
    "field",
    ["strategy", "universe", "data_source", "in_sample", "holdout", "cost_model", "slippage_model", "max_configurations", "acceptance"],
)
def test_a_registration_missing_a_required_field_is_refused_and_logged(tools, field):
    arguments = registration()
    del arguments[field]

    answer = tools.call("register_strategy", arguments)

    assert answer["isError"]
    assert field in text_of(answer)
    assert "Nothing was written" in text_of(answer)
    assert events("strategy-registered") == []
    refused = refusals("strategy-registered")[-1]
    assert refused["reason"] == f"missing-fields:{field}"
    assert refused["attempted_writer"] == "cell:alpha"
    assert refused["session"] == SESSION
    assert refused["tool"] == "register_strategy"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("strategy", "Not A Name"),
        ("strategy", 5),
        ("universe", []),
        ("universe", "SPY"),
        ("universe", ["SPY", "SPY"]),
        ("universe", ["../x"]),
        ("data_source", 5),
        ("in_sample", "2026"),
        ("in_sample", {"start": "2026-01-05"}),
        ("in_sample", {"start": "2026-13-05", "end": "2026-01-09"}),
        ("in_sample", {"start": "2026-01-09", "end": "2026-01-05"}),
        ("holdout", {"start": "2026-02-04", "end": "2026-02-02"}),
        ("cost_model", {}),
        ("cost_model", {"bps_per_turnover": -1}),
        ("slippage_model", {"bps_per_turnover": "low"}),
        ("slippage_model", {"bps_per_turnover": True}),
        ("cost_model", {"bps_per_turnover": 10_001}),
        ("cost_model", {"bps_per_turnover": 10**400}),
        ("slippage_model", {"bps_per_turnover": 17 * 10**307}),
        ("acceptance", {"min_deflated_sharpe": 10**400, "min_holdout_return": 0, "max_drawdown": 0.2}),
        ("max_configurations", 0),
        ("max_configurations", 1.5),
        ("max_configurations", True),
        ("acceptance", {"min_deflated_sharpe": 0.9}),
        ("acceptance", {"min_deflated_sharpe": "high", "min_holdout_return": 0, "max_drawdown": 0.2}),
        ("paper_days", 0),
    ],
)
def test_a_registration_whose_field_makes_no_sense_is_refused_and_names_the_field(tools, field, value):
    answer = tools.register(**{field: value})

    assert answer["isError"]
    assert events("strategy-registered") == []
    assert refusals("strategy-registered")[-1]["reason"] == f"bad-field:{field}"


@pytest.mark.parametrize("field", ["data_hash", "session", "writer"])
def test_a_registration_cannot_choose_what_the_tool_fills_in(tools, field):
    answer = tools.register(**{field: "planted"})

    assert answer["isError"]
    assert events("strategy-registered") == []
    assert refusals("strategy-registered")[-1]["reason"] == "unknown-fields"


def test_a_holdout_that_does_not_come_after_the_in_sample_is_refused(tools):
    answer = tools.register(holdout={"start": "2026-01-09", "end": "2026-02-04"})

    assert answer["isError"]
    assert events("strategy-registered") == []
    assert refusals("strategy-registered")[-1]["reason"] == "holdout-not-after-in-sample"


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        ("fixture:absent", "data-unavailable:no-such-source"),
        ("fixture:../../company-config/settings", "data-unavailable:no-such-source"),
        ("fixture:", "data-unavailable:no-such-source"),
        ("a-broker:bars", "data-unavailable:no-such-source"),
        ("/etc/passwd", "data-unavailable:no-such-source"),
    ],
)
def test_a_data_source_that_is_not_available_is_refused(tools, source, reason):
    answer = tools.register(data_source=source)

    assert answer["isError"]
    assert events("strategy-registered") == []
    assert refusals("strategy-registered")[-1]["reason"] == reason


@pytest.mark.parametrize(
    "content",
    [
        "not json\n",
        '{"date": "2026-01-05"}\n',
        '{"date": "soon", "symbols": {}}\n',
        json.dumps(bar("2026-01-06", 100)) + "\n" + json.dumps(bar("2026-01-05", 100)) + "\n",
        json.dumps(bar("2026-01-05", 100)) + "\n" + json.dumps(bar("2026-01-05", 100)) + "\n",
        json.dumps(bar("2026-01-05", -1)) + "\n",
        json.dumps(bar("2026-01-05", 0)) + "\n",
        '{"date": "2026-01-05", "symbols": {"SPY": {"close": ' + str(10**400) + "}}}\n",
        json.dumps({"date": "2026-01-05", "symbols": {"SPY": {"open": 1}}}) + "\n",
    ],
)
def test_data_that_cannot_be_read_as_bars_is_not_available(tools, content):
    write_market("broken").write_text(content)

    answer = tools.register(data_source="fixture:broken")

    assert answer["isError"]
    assert refusals("strategy-registered")[-1]["reason"] == "data-unavailable:unreadable"


@pytest.mark.parametrize(
    "changes",
    [
        {"universe": ["SPY", "ABSENT"]},
        {"in_sample": {"start": "2026-01-05", "end": "2026-01-05"}},
        {"in_sample": {"start": "2025-01-01", "end": "2025-02-01"}},
        {"holdout": {"start": "2026-02-02", "end": "2026-02-02"}},
        {"holdout": {"start": "2027-01-01", "end": "2027-02-01"}},
    ],
)
def test_data_that_does_not_cover_what_is_registered_is_not_available(tools, changes):
    answer = tools.register(**changes)

    assert answer["isError"]
    assert refusals("strategy-registered")[-1]["reason"] == "data-unavailable:not-covered"


def test_a_universe_symbol_missing_on_one_day_of_a_period_is_not_covered(tools):
    gap = json.loads(json.dumps(IN_SAMPLE_BARS))
    del gap[2]["symbols"]["SPY"]
    write_market("gap", [*gap, *HOLDOUT_BARS])

    answer = tools.register(data_source="fixture:gap")

    assert answer["isError"]
    assert refusals("strategy-registered")[-1]["reason"] == "data-unavailable:not-covered"


# A backtest and its registration


def test_a_backtest_before_any_registration_does_not_run_and_is_logged(tools):
    answer = tools.call("run_backtest", {"strategy": "momentum", "code": HOLD, "parameters": {}})

    assert answer["isError"]
    assert "Nothing was written" in text_of(answer)
    assert events("config-run") == []
    refused = refusals("config-run")[-1]
    assert refused["reason"] == "no-registration"
    assert refused["session"] == SESSION


def test_a_backtest_of_another_cells_registration_does_not_run(registered, market):
    other = CellTools(bet="beta")
    try:
        answer = other.call("run_backtest", {"strategy": "momentum", "code": HOLD, "parameters": {}})
    finally:
        other.close()

    assert answer["isError"]
    assert events("config-run") == []
    assert refusals("config-run")[-1]["reason"] == "no-registration"


@pytest.mark.parametrize(
    "arguments",
    [
        {"code": HOLD},
        {"strategy": "momentum"},
        {"strategy": "momentum", "code": ""},
        {"strategy": "momentum", "code": 5},
        {"strategy": "momentum", "code": HOLD, "parameters": [1]},
        {"strategy": 5, "code": HOLD},
        {"strategy": "momentum", "code": "#" * (quant.MAX_CODE_CHARACTERS + 1)},
    ],
)
def test_a_backtest_whose_arguments_make_no_configuration_does_not_run(registered, arguments):
    answer = registered.call("run_backtest", arguments)

    assert answer["isError"]
    assert events("config-run") == []
    assert refusals("config-run")[-1]["reason"] == "bad-arguments"


def test_a_registration_may_be_replaced_before_its_first_run_and_the_newest_stands(registered):
    assert not registered.register(max_configurations=1)["isError"]

    assert registered.backtest(HOLD)["status"] == "ok"
    newest = events("strategy-registered")[-1]
    assert events("config-run")[-1]["registration_seq"] == newest["seq"]
    assert registered.call("run_backtest", {"strategy": "momentum", "code": FLAT, "parameters": {}})["isError"]
    assert events("config-refused")[-1]["registration_seq"] == newest["seq"]


def test_a_registration_cannot_change_after_its_first_run(registered):
    registered.backtest(HOLD)
    before = events("strategy-registered")

    answer = registered.register(max_configurations=100)

    assert answer["isError"]
    assert "Nothing was written" in text_of(answer)
    assert events("strategy-registered") == before
    assert refusals("strategy-registered")[-1]["reason"] == "registration-closed"
    assert registered.backtest(FLAT)["budget"] == 3


def test_a_new_in_sample_may_not_read_an_earlier_registrations_holdout(registered):
    answer = registered.register(strategy="second", in_sample={"start": "2026-01-05", "end": "2026-02-02"}, holdout={"start": "2026-02-03", "end": "2026-02-04"})

    assert answer["isError"]
    assert refusals("strategy-registered")[-1]["reason"] == "holdout-already-held"
    assert [event["strategy"] for event in events("strategy-registered")] == ["momentum"]


def test_a_new_holdout_may_not_be_a_period_an_earlier_registration_could_read(market):
    write_market("daily", [bar("2025-12-01", 100), bar("2025-12-02", 101), *IN_SAMPLE_BARS, *HOLDOUT_BARS])
    first = CellTools()
    second = CellTools(bet="beta")
    try:
        assert not first.register()["isError"]
        answer = second.register(
            strategy="second", in_sample={"start": "2025-12-01", "end": "2025-12-02"}, holdout={"start": "2026-01-08", "end": "2026-01-09"}
        )
    finally:
        first.close()
        second.close()

    assert answer["isError"]
    assert refusals("strategy-registered")[-1]["reason"] == "holdout-already-seen"


def test_a_new_name_cannot_reset_a_budget_on_the_same_holdout(market):
    """Without this, three names with a budget of one each would run three configurations and ask three verdicts of one holdout."""
    tools = CellTools()
    try:
        assert not tools.register(strategy="a1", max_configurations=1)["isError"]
        tools.backtest(HOLD, strategy="a1")

        for holdout in ({"start": "2026-02-02", "end": "2026-02-04"}, {"start": "2026-02-03", "end": "2026-02-04"}):
            answer = tools.register(strategy="a2", max_configurations=1, holdout=holdout)
            assert answer["isError"]
            assert refusals("strategy-registered")[-1]["reason"] == "holdout-already-held"
    finally:
        tools.close()

    assert [event["strategy"] for event in events("strategy-registered")] == ["a1"]
    assert len(events("config-run")) == 1


def test_a_new_registration_may_share_the_in_sample_with_a_holdout_of_its_own(registered):
    write_market("daily", [*IN_SAMPLE_BARS, *HOLDOUT_BARS, bar("2026-03-02", 100), bar("2026-03-03", 100)])

    assert not registered.register(strategy="second", holdout={"start": "2026-03-02", "end": "2026-03-03"})["isError"]
    assert registered.backtest(HOLD, strategy="second")["status"] == "ok"


def test_a_registration_replaced_before_its_first_run_holds_no_period_any_more(registered):
    answer = registered.register(in_sample={"start": "2026-01-05", "end": "2026-02-02"}, holdout={"start": "2026-02-03", "end": "2026-02-04"})
    assert not answer["isError"], answer


def test_a_registration_replaced_holds_no_period_against_another_strategy(registered):
    write_market("daily", [*IN_SAMPLE_BARS, *HOLDOUT_BARS, bar("2026-02-05", 100)])
    answer = registered.register(in_sample={"start": "2026-01-05", "end": "2026-01-06"}, holdout={"start": "2026-01-07", "end": "2026-01-08"})
    assert not answer["isError"], answer

    answer = registered.register(strategy="third", in_sample={"start": "2026-02-02", "end": "2026-02-03"}, holdout={"start": "2026-02-04", "end": "2026-02-05"})

    assert not answer["isError"], answer


# The search budget


def test_each_new_configuration_counts_against_the_budget(registered):
    assert registered.backtest(HOLD)["budget_used"] == 1
    assert registered.backtest(FLAT)["budget_used"] == 2
    assert registered.backtest(SCALED, {"weight": 0.5})["budget_used"] == 3
    assert [event["budget_used"] for event in events("config-run")] == [1, 2, 3]
    assert {event["writer"] for event in events("config-run")} == {"runner"}


def test_the_same_code_with_other_parameters_is_another_configuration(registered):
    registered.backtest(SCALED, {"weight": 0.5})
    assert registered.backtest(SCALED, {"weight": 0.25})["budget_used"] == 2


def test_a_repeat_costs_nothing_and_returns_the_stored_result(registered):
    first = registered.backtest(SCALED, {"a": 1, "weight": 0.5})
    count = len(events())

    again = registered.backtest(SCALED, {"weight": 0.5, "a": 1})

    assert again["repeat"] is True
    assert first["repeat"] is False
    assert {key: value for key, value in again.items() if key != "repeat"} == {key: value for key, value in first.items() if key != "repeat"}
    assert len(events()) == count
    assert registered.backtest(FLAT)["budget_used"] == 2


def test_the_run_past_the_budget_is_refused_and_logged_and_a_repeat_still_answers(market):
    tools = CellTools()
    try:
        assert not tools.register(max_configurations=1)["isError"]
        first = tools.backtest(HOLD)

        answer = tools.call("run_backtest", {"strategy": "momentum", "code": FLAT, "parameters": {}})

        assert answer["isError"]
        assert "did not run" in text_of(answer)
        refused = events("config-refused")[-1]
        assert refused["writer"] == "runner"
        assert refused["reason"] == "budget-spent"
        assert str(refused["seq"]) in text_of(answer)
        assert len(events("config-run")) == 1

        assert tools.backtest(HOLD)["sharpe"] == first["sharpe"]
        assert len(events("config-refused")) == 1
    finally:
        tools.close()


def test_two_cells_racing_for_the_last_of_a_budget_run_one(market):
    """Two sessions of one bet, each with its own server, cannot both take the last configuration."""
    slow = "import time\ndef decide(bar, parameters):\n    time.sleep(0.2)\n    return {}\n"
    first, second = CellTools(), CellTools()
    try:
        assert not first.register(max_configurations=1)["isError"]
        answers = []
        threads = [
            threading.Thread(target=lambda tool=tool, code=code: answers.append(tool.call("run_backtest", {"strategy": "momentum", "code": code, "parameters": {}})))
            for tool, code in ((first, slow), (second, slow + "# another\n"))
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    finally:
        first.close()
        second.close()

    assert sorted(answer["isError"] for answer in answers) == [False, True]
    assert len(events("config-run")) == 1
    assert len(events("config-refused")) == 1


def test_data_changed_since_the_registration_is_refused_at_no_cost(registered, market):
    market.write_text(market.read_text().replace('"close": 110', '"close": 111'))

    answer = registered.call("run_backtest", {"strategy": "momentum", "code": HOLD, "parameters": {}})

    assert answer["isError"]
    assert events("config-run") == []
    assert events("config-refused")[-1]["reason"] == "data-changed"


def test_data_gone_since_the_registration_is_refused_at_no_cost(registered, market):
    market.unlink()

    assert registered.call("run_backtest", {"strategy": "momentum", "code": HOLD, "parameters": {}})["isError"]
    assert events("config-run") == []
    assert events("config-refused")[-1]["reason"] == "data-changed"


def test_a_sessions_rules_deny_the_bars_and_the_kept_configurations(cell_session, stub):
    """The bars hold every holdout: the sandbox denies the shell the whole home, and these deny the file tools."""
    cell_session()

    deny = stub.settings()["permissions"]["deny"]
    for root in (paths.home() / "market-data", paths.home() / "configurations"):
        for tool in ("Read", "Edit"):
            assert f"{tool}(//{str(root).lstrip('/')}/**)" in deny
    assert str(paths.home()) in stub.settings()["sandbox"]["filesystem"]["denyRead"]


def test_each_configuration_is_kept_for_the_verdict_to_run(registered):
    result = registered.backtest(SCALED, {"weight": 0.5})

    kept = json.loads((paths.home() / "configurations" / str(result["registration_seq"]) / f"{result['config_hash']}.json").read_text())

    assert kept == {"code": SCALED, "parameters": {"weight": 0.5}}
    assert quant.config_hash(SCALED, {"weight": 0.5}) == result["config_hash"]


# One bar at a time, and the costs


def test_the_runner_records_the_worked_result_with_its_costs_applied(registered):
    result = registered.backtest(HOLD)

    assert result["status"] == "ok"
    assert result["n_returns"] == 4
    assert result["total_return"] == pytest.approx(0.087515)
    assert result["max_drawdown"] == pytest.approx(0.10)
    assert result["sharpe"] == pytest.approx(0.25825, abs=1e-5)
    assert result["skew"] == pytest.approx(WORKED_SKEW)
    assert result["kurtosis"] == pytest.approx(WORKED_KURTOSIS)
    recorded = events("config-run")[-1]
    assert recorded["total_return"] == result["total_return"]
    assert len(recorded["returns_hash"]) == 64


def test_a_position_earns_the_move_after_its_bar_and_pays_to_enter_and_to_leave(registered):
    result = registered.backtest(HOLD_FIRST)

    assert result["total_return"] == pytest.approx(0.09685225)


@pytest.mark.parametrize(
    ("bps", "worked"),
    [(0, 1.1 * 1.0 - 1), (100, (1 + 0.1 - 0.02) * (1 - 0.02) - 1)],
)
def test_the_runner_applies_the_registered_costs_whatever_the_code_says(market, bps, worked):
    """The same positions under a dearer registration return less: each model charges its basis points per unit of turnover."""
    tools = CellTools()
    try:
        tools.register(cost_model={"bps_per_turnover": bps}, slippage_model={"bps_per_turnover": bps})
        result = tools.backtest("COST = 0\n" + HOLD_FIRST)
    finally:
        tools.close()

    assert result["total_return"] == pytest.approx(worked)


def test_an_account_that_has_lost_everything_stays_lost(market):
    """At the largest costs, entering costs 2 and each flip 4, so the first two returns are about -2.1 and -4.1.

    Multiplied through, those two losses past the whole would turn back into a gain of about 3.4.
    """
    flip = """
weight = 1.0
def decide(bar, parameters):
    global weight
    weight = -weight
    return {"SPY": weight}
"""
    tools = CellTools()
    try:
        tools.register(cost_model={"bps_per_turnover": 10_000}, slippage_model={"bps_per_turnover": 10_000})
        result = tools.backtest(flip)
    finally:
        tools.close()

    assert result["status"] == "ok"
    assert result["total_return"] == -1
    assert result["max_drawdown"] == 1


def test_a_flat_strategy_has_no_variance_and_reads_as_nothing_earned(registered):
    result = registered.backtest(FLAT)

    assert result["status"] == "ok"
    assert result["total_return"] == 0
    assert result["max_drawdown"] == 0
    assert result["sharpe"] == 0
    assert result["skew"] == 0
    assert result["kurtosis"] == 3


def test_one_return_has_no_spread_to_measure_against(market):
    tools = CellTools()
    try:
        tools.register(in_sample={"start": "2026-01-05", "end": "2026-01-06"})
        result = tools.backtest(HOLD)
    finally:
        tools.close()

    assert result["n_returns"] == 1
    assert result["total_return"] == pytest.approx(0.0985)
    assert (result["sharpe"], result["skew"], result["kurtosis"]) == (0, 0, 3)


def test_returns_too_small_to_measure_are_a_failed_configuration_and_no_crash_of_the_server(registered):
    result = registered.backtest('def decide(bar, parameters):\n    return {"SPY": 1e-100}\n')

    assert result["status"] == "failed"
    assert result["failure"] == "not-finite"
    assert result["budget_used"] == 1
    assert registered.backtest(FLAT)["status"] == "ok"


@pytest.mark.parametrize("weight", ["1.0", "-1.0"])
def test_a_market_too_wild_to_measure_is_a_failed_configuration_and_no_crash_of_the_server(market, weight):
    wild = [bar("2026-01-05", 1e-300), bar("2026-01-06", 1e300), bar("2026-01-07", 1e-300), bar("2026-01-08", 1e300), *HOLDOUT_BARS]
    write_market("wild", wild)
    tools = CellTools()
    try:
        tools.register(data_source="fixture:wild", in_sample={"start": "2026-01-05", "end": "2026-01-08"})
        result = tools.backtest(f'def decide(bar, parameters):\n    return {{"SPY": {weight}}}\n')
    finally:
        tools.close()

    assert result["status"] == "failed"
    assert result["failure"] == "not-finite"


def test_a_strategy_is_given_one_bar_at_a_time_and_only_its_universe(registered):
    seen = """
dates = []
def decide(bar, parameters):
    dates.append(bar["date"])
    if len(dates) == 4:
        raise RuntimeError(f"{dates} {sorted(bar['symbols'])}")
    return {}
"""
    result = registered.backtest(seen)

    assert result["failure"] == "crashed: RuntimeError: ['2026-01-05', '2026-01-06', '2026-01-07', '2026-01-08'] ['SPY']"


def test_no_position_is_asked_for_on_the_last_bar_since_no_return_follows_it(registered):
    assert registered.backtest(strategy_doing("assert bar['date'] != '2026-01-09'"))["status"] == "ok"


def test_no_later_bar_is_waiting_on_the_strategys_input_when_it_decides(registered):
    look = "import select, sys\ndef decide(bar, parameters):\n    if select.select([sys.stdin], [], [], 0.05)[0]:\n        raise RuntimeError('a later bar')\n    return {}\n"

    assert registered.backtest(look)["status"] == "ok"


@pytest.mark.parametrize(
    "action",
    ["import sys; sys.stdin.read()", "import sys; sys.stdin.readline()", "import sys; sys.stdin.buffer.read(1)", "import os; os.read(0, 1)"],
)
def test_a_strategy_that_asks_for_a_later_bar_gets_none_and_fails_at_its_time_limit(quick, action):
    result = quick.backtest(strategy_doing(action))

    assert result["status"] == "failed"
    assert result["failure"] == "timed-out"


def test_a_strategy_cannot_find_the_later_bars_on_the_disk(registered, market):
    result = registered.backtest(strategy_doing(f"open({str(market)!r})"))

    assert result["status"] == "failed"
    assert result["failure"].startswith("crashed: FileNotFoundError")


# Confinement


@pytest.mark.parametrize("path", ["/tmp/x", "/x", "/usr/x", "/runner/x", "/runner/child.py", "/dev/x", "/dev/shm/x"])
def test_a_strategy_cannot_write_anywhere_it_can_name(registered, path):
    result = registered.backtest(strategy_doing(f"open({path!r}, 'a')"))

    assert result["status"] == "failed"
    assert result["failure"].startswith(("crashed: OSError", "crashed: FileNotFoundError", "crashed: PermissionError"))


def test_a_strategy_can_use_the_standard_librarys_randomness(registered):
    result = registered.backtest(strategy_doing("import os, random; os.urandom(4); random.random()"))

    assert result["status"] == "ok", result


def test_a_strategy_cannot_write_a_path_of_the_real_machine(registered, tmp_path):
    target = tmp_path / "escaped"

    result = registered.backtest(strategy_doing(f"open({str(target)!r}, 'w')"))

    assert result["status"] == "failed"
    assert not target.exists()


def test_a_strategy_cannot_read_the_ledger_or_daniels_settings_or_the_repository(registered, repo):
    for path in (paths.home() / "ledger.jsonl", paths.config() / "settings.json", repo / "CLAUDE.md"):
        result = registered.backtest(strategy_doing(f"open({str(path)!r})"))
        assert result["failure"].startswith("crashed: FileNotFoundError"), path


def test_a_strategy_cannot_reach_a_listener_on_this_machine(registered):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.setblocking(False)
        port = listener.getsockname()[1]

        result = registered.backtest(strategy_doing(f"import socket; socket.create_connection(('127.0.0.1', {port}), timeout=2)"))

        assert result["status"] == "failed"
        assert result["failure"].startswith("crashed: ")
        with pytest.raises(BlockingIOError):
            listener.accept()


def test_a_strategy_sees_none_of_the_environment_or_the_machines_processes(registered):
    result = registered.backtest(strategy_doing("import os; raise RuntimeError(str(sorted(os.environ)))"))
    assert "COMPANY" not in result["failure"]
    assert "PATH" not in result["failure"]

    result = registered.backtest(strategy_doing("import os; os.listdir('/proc')"))
    assert result["failure"].startswith("crashed: FileNotFoundError")


def _descendants(pid):
    found = []
    try:
        children = Path(f"/proc/{pid}/task/{pid}/children").read_text().split()
    except OSError:
        return found
    for child in children:
        found += [int(child), *_descendants(int(child))]
    return found


def _name(pid):
    try:
        return Path(f"/proc/{pid}/comm").read_text()
    except OSError:
        return ""


def test_a_server_killed_during_a_backtest_leaves_no_strategy_running(market):
    tools = CellTools(seconds=60)
    assert not tools.register()["isError"]
    message = {"jsonrpc": "2.0", "id": 99, "method": "tools/call", "params": {"name": "run_backtest", "arguments": {"strategy": "momentum", "code": strategy_doing("import time; time.sleep(600)"), "parameters": {}}}}
    tools.process.stdin.write(json.dumps(message) + "\n")
    tools.process.stdin.flush()
    found = []

    def has_a_sandbox():
        found[:] = _descendants(tools.process.pid)
        return len(found) >= 2

    wait_for(has_a_sandbox)

    tools.process.kill()
    tools.process.wait(timeout=10)

    wait_for(lambda: not any(pid_is_running(pid) for pid in found))


def test_a_session_stopped_during_a_backtest_leaves_no_strategy_running(company, stub, board, market):
    assert company("settings", "set", "session_max_minutes", "0.05").returncode == 0
    stub.play(
        {"do": "tool", "name": "register_strategy", "arguments": registration()},
        {"do": "tool", "name": "run_backtest", "arguments": {"strategy": "momentum", "code": strategy_doing("import time; time.sleep(600)")}},
    )
    script = Path(sys.executable).parent / "company"
    launch = subprocess.Popen([script, "session", "start", "cell", "--bet", "alpha"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    inside = []

    def has_a_sandbox():
        inside[:] = [found for pid in _descendants(launch.pid) if "bwrap" in _name(pid) for found in (pid, *_descendants(pid))]
        return len(inside) >= 2

    try:
        wait_for(has_a_sandbox)
        launch.wait(timeout=30)
    finally:
        launch.kill()
        launch.wait()

    assert events("session-stopped")[-1]["reason"] == "max-minutes"
    wait_for(lambda: not any(pid_is_running(pid) for pid in inside))


def _module_call(arguments, writer="cell:alpha", seconds=5):
    return quant.run(arguments, writer, seconds)


def test_with_no_bwrap_nothing_runs_unconfined_and_the_budget_is_untouched(registered, monkeypatch, tmp_path):
    monkeypatch.setattr(quant, "SYSTEM_PATH", str(tmp_path / "empty"))

    with pytest.raises(quant.Logged) as refused:
        _module_call({"strategy": "momentum", "code": HOLD, "parameters": {}})

    assert refused.value.reason == "no-confinement"
    assert events("config-run") == []
    assert events("config-refused")[-1]["reason"] == "no-confinement"


def test_a_bwrap_that_cannot_set_up_is_no_failure_of_the_strategy_and_costs_nothing(registered, monkeypatch, tmp_path):
    fake = tmp_path / "broken-bwrap"
    fake.mkdir()
    (fake / "bwrap").write_text("#!/bin/sh\necho 'setting up uid map: Permission denied' >&2\nexit 1\n")
    (fake / "bwrap").chmod(0o755)
    monkeypatch.setattr(quant, "SYSTEM_PATH", str(fake))

    with pytest.raises(quant.Logged) as refused:
        _module_call({"strategy": "momentum", "code": HOLD, "parameters": {}})

    assert refused.value.reason == "confinement-failed"
    assert events("config-run") == []


def test_a_sandbox_that_never_starts_is_no_failure_of_the_strategy_either(registered, monkeypatch, tmp_path):
    fake = tmp_path / "stuck-bwrap"
    fake.mkdir()
    (fake / "bwrap").write_text("#!/bin/sh\nexec /bin/sleep 600\n")
    (fake / "bwrap").chmod(0o755)
    monkeypatch.setattr(quant, "SYSTEM_PATH", str(fake))

    with pytest.raises(quant.Logged) as refused:
        _module_call({"strategy": "momentum", "code": HOLD, "parameters": {}}, seconds=0.5)

    assert refused.value.reason == "confinement-failed"
    assert events("config-run") == []


def test_the_runner_starts_under_bwrap_with_every_namespace_unshared_and_nothing_writable(registered, monkeypatch, tmp_path):
    real = shutil.which("bwrap", path=quant.SYSTEM_PATH)
    assert real is not None, "this test and the runner need bwrap: CI installs it"
    spy = tmp_path / "spy"
    spy.mkdir()
    (spy / "bwrap").write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > {tmp_path}/arguments\nexec {real} "$@"\n')
    (spy / "bwrap").chmod(0o755)
    monkeypatch.setattr(quant, "SYSTEM_PATH", str(spy))

    result = _module_call({"strategy": "momentum", "code": HOLD, "parameters": {}})

    assert result["status"] == "ok"
    arguments = (tmp_path / "arguments").read_text().split("\n")
    for flag in ("--unshare-all", "--die-with-parent", "--new-session", "--remount-ro"):
        assert flag in arguments
    assert "--bind" not in arguments
    assert "--tmpfs" not in arguments
    assert "--share-net" not in arguments
    assert str(paths.home()) not in arguments
    assert str(paths.config()) not in arguments


# What fails


@pytest.mark.parametrize(
    ("code", "failure"),
    [
        ("import time\ndef decide(bar, parameters):\n    time.sleep(600)\n", "timed-out"),
        ("def decide(bar, parameters):\n    while True:\n        pass\n", "timed-out"),
        ("import time\ntime.sleep(600)\n", "timed-out"),
        (strategy_doing("import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(600)"), "timed-out"),
        (strategy_doing("import sys; sys.stdout.write('half a line'); sys.stdout.flush(); import time; time.sleep(600)"), "timed-out"),
    ],
)
def test_a_strategy_that_hangs_is_a_failed_configuration_that_counts(quick, code, failure):
    began = time.monotonic()
    result = quick.backtest(code)

    assert result["status"] == "failed"
    assert result["failure"] == failure
    assert result["budget_used"] == 1
    assert time.monotonic() - began < 10
    assert "sharpe" not in result
    assert events("config-run")[-1]["status"] == "failed"
    assert events("config-run")[-1]["failure"] == failure


@pytest.mark.parametrize(
    ("code", "failure"),
    [
        (strategy_doing("raise ValueError('boom')"), "crashed: ValueError: boom"),
        ("def (", "crashed: SyntaxError"),
        ("raise SystemExit(3)", "crashed: SystemExit: 3"),
        ("x = 1\n", "crashed: KeyError: 'decide'"),
        (strategy_doing("raise SystemExit(0)"), "crashed: SystemExit: 0"),
        (strategy_doing("import os; os._exit(0)"), "ended-early"),
        (strategy_doing("import os; os._exit(1)"), "ended-early"),
        (strategy_doing("import os, signal; os.kill(os.getpid(), signal.SIGKILL)"), "ended-early"),
        (strategy_doing("bytearray(5 * 1024**3)"), "crashed: MemoryError"),
        (strategy_doing("import os; os.fork()"), "crashed: BlockingIOError"),
        (strategy_doing("import threading; threading.Thread(target=print).start()"), "crashed: RuntimeError"),
    ],
)
def test_a_strategy_that_crashes_is_a_failed_configuration_that_counts(quick, code, failure):
    result = quick.backtest(code)

    assert result["status"] == "failed"
    assert result["failure"].startswith(failure), result["failure"]
    assert result["budget_used"] == 1


def _returning(value):
    return f"nan = float('nan')\ninf = float('inf')\ndef decide(bar, parameters):\n    return {value}\n"


@pytest.mark.parametrize(
    "code",
    [
        strategy_doing("print('rubbish')"),
        strategy_doing("print('{}')"),
        strategy_doing("print('[1, 2]')"),
        strategy_doing("print('{\"positions\": 5}')"),
        strategy_doing("import sys; sys.stdout.buffer.write(bytes(range(256)) + b'\\n'); sys.stdout.flush()"),
        strategy_doing("print('x' * 10_000_000)"),
        strategy_doing("import sys, time; sys.stdout.write('x' * 10_000_000); sys.stdout.flush(); time.sleep(600)"),
        _returning('"SPY"'),
        _returning("5"),
        _returning("None"),
        _returning('{"QQQ": 0.5}'),
        _returning('{"SPY": "half"}'),
        _returning('{"SPY": None}'),
        _returning('{"SPY": True}'),
        _returning('{"SPY": nan}'),
        _returning('{"SPY": inf}'),
        _returning('{"SPY": 1.5}'),
        _returning('{"SPY": 10 ** 400}'),
    ],
)
def test_a_strategy_that_prints_rubbish_is_a_failed_configuration_that_counts(quick, code):
    result = quick.backtest(code)

    assert result["status"] == "failed"
    assert result["failure"].startswith("bad-output"), result["failure"]
    assert result["budget_used"] == 1
    assert "sharpe" not in result


def test_a_universe_may_not_be_held_past_its_whole_value(market):
    tools = CellTools()
    try:
        tools.register(universe=["SPY", "QQQ"])
        over = tools.backtest(_returning('{"SPY": 0.75, "QQQ": -0.75}'))
        whole = tools.backtest(_returning('{"SPY": 0.1, "QQQ": 0.9}'))
    finally:
        tools.close()

    assert over["failure"].startswith("bad-output")
    assert whole["status"] == "ok"


def test_a_failure_says_a_bounded_amount(quick):
    result = quick.backtest(strategy_doing("raise ValueError('x' * 100_000)"))

    assert len(result["failure"]) <= quant.MAX_FAILURE_CHARACTERS


def test_a_failed_configuration_is_stored_and_its_repeat_costs_nothing(quick):
    crash = strategy_doing("raise ValueError('boom')")
    first = quick.backtest(crash)
    count = len(events())

    again = quick.backtest(crash)

    assert again["repeat"] is True
    assert again["failure"] == first["failure"]
    assert len(events()) == count
    assert again["budget_used"] == 1


def test_the_tool_answers_with_the_records_numbers(registered):
    result = registered.backtest(HOLD)
    recorded = events("config-run")[-1]

    assert result["event"] == recorded["seq"]
    for name in ("registration_seq", "config_hash", "status", "budget_used", "sharpe", "n_returns", "skew", "kurtosis", "total_return", "max_drawdown", "returns_hash"):
        assert result[name] == recorded[name], name
    assert result["budget"] == 3
    assert math.isfinite(result["sharpe"])


# The holdout


def test_no_tool_gives_the_cell_a_holdout_bar_or_a_result_from_one(registered):
    """The planted marker and price are in the file, and the same plant in the in-sample bars does come through."""
    assert HOLDOUT_MARKER in (paths.home() / "market-data/daily.jsonl").read_text()
    registered.backtest(HOLD)
    registered.backtest(FLAT)
    leaked = registered.backtest(strategy_doing("raise RuntimeError(str(bar))"))

    received = "".join(registered.received)

    assert IN_SAMPLE_MARKER in received
    assert IN_SAMPLE_MARKER in leaked["failure"]
    assert HOLDOUT_MARKER not in received
    assert str(HOLDOUT_CLOSE) not in received
    assert "2026-02-03" not in received
    for event in events():
        assert HOLDOUT_MARKER not in json.dumps(event)
        assert str(HOLDOUT_CLOSE) not in json.dumps(event)


def test_a_strategy_that_reads_every_bar_it_is_given_sees_no_holdout(market):
    tools = CellTools()
    try:
        tools.register()
        spy = """
dates = []
def decide(bar, parameters):
    dates.append(bar["date"])
    if bar["date"] == "2026-01-08":
        raise RuntimeError(",".join(dates))
    return {}
"""
        result = tools.backtest(spy)
    finally:
        tools.close()

    assert result["failure"] == "crashed: RuntimeError: 2026-01-05,2026-01-06,2026-01-07,2026-01-08"


def test_changing_only_the_holdout_changes_no_result(market):
    other = [bar(item["date"], item["symbols"]["SPY"]["close"] * 3) for item in HOLDOUT_BARS]
    write_market("other", [*IN_SAMPLE_BARS, *other])
    tools = CellTools()
    try:
        tools.register(strategy="one")
        tools.register(strategy="two", data_source="fixture:other")
        one = tools.backtest(HOLD, strategy="one")
        two = tools.backtest(HOLD, strategy="two")
    finally:
        tools.close()

    assert one["returns_hash"] == two["returns_hash"]
    assert one["sharpe"] == two["sharpe"]


# The whole path, on the stub session


@pytest.fixture
def cell_session(company, stub, board, market):
    def run(*steps):
        stub.play(*steps)
        return company("session", "start", "cell", "--bet", "alpha", "--prompt", "research")

    return run


def _tool_text(result):
    return result["result"]["content"][0]["text"]


def test_a_stub_cell_registers_and_runs_its_backtests_through_the_real_tools(cell_session, stub):
    done = cell_session(
        {"do": "list-tools"},
        {"do": "tool", "name": "run_backtest", "arguments": {"strategy": "momentum", "code": HOLD}},
        {"do": "tool", "name": "register_strategy", "arguments": registration(max_configurations=2)},
        {"do": "tool", "name": "run_backtest", "arguments": {"strategy": "momentum", "code": HOLD}},
        {"do": "tool", "name": "run_backtest", "arguments": {"strategy": "momentum", "code": HOLD}},
        {"do": "tool", "name": "run_backtest", "arguments": {"strategy": "momentum", "code": FLAT}},
        {"do": "tool", "name": "run_backtest", "arguments": {"strategy": "momentum", "code": SCALED, "parameters": {"weight": 1}}},
    )

    assert done.returncode == 0, done.stdout + done.stderr
    listed = {tool["name"] for tool in stub.tool_lists()[-1]["result"]["tools"]}
    assert {"note", "register_strategy", "run_backtest", "request_verdict"} == listed
    allowed = stub.argument("--allowedTools").split(",")
    assert "mcp__company__register_strategy" in allowed
    assert "mcp__company__run_backtest" in allowed
    too_early, registered, first, repeat, second, past = stub.tool_results()
    assert too_early["result"]["isError"]
    assert not registered["result"]["isError"]
    assert json.loads(_tool_text(first))["total_return"] == pytest.approx(0.087515)
    assert json.loads(_tool_text(repeat))["repeat"] is True
    assert json.loads(_tool_text(second))["budget_used"] == 2
    assert past["result"]["isError"]

    assert [event["writer"] for event in events("strategy-registered")] == ["cell:alpha"]
    assert [event["status"] for event in events("config-run")] == ["ok", "ok"]
    assert [event["reason"] for event in events("config-refused")] == ["budget-spent"]
    assert refusals("config-run")[-1]["reason"] == "no-registration"

    received = json.dumps(stub.tool_results())
    assert HOLDOUT_MARKER not in received
    assert str(HOLDOUT_CLOSE) not in received


def test_daniels_setting_is_the_time_limit_a_cells_strategy_runs_under(cell_session, stub, company):
    assert company("settings", "set", "backtest_max_seconds", "1").returncode == 0
    began = time.monotonic()

    done = cell_session(
        {"do": "tool", "name": "register_strategy", "arguments": registration()},
        {"do": "tool", "name": "run_backtest", "arguments": {"strategy": "momentum", "code": strategy_doing("import time; time.sleep(600)")}},
    )

    assert done.returncode == 0, done.stdout + done.stderr
    assert time.monotonic() - began < 30
    assert json.loads(_tool_text(stub.tool_results()[-1]))["failure"] == "timed-out"
    arguments = stub.mcp_config()["mcpServers"]["company"]["args"]
    assert float(arguments[arguments.index("--backtest-seconds") + 1]) == 1


def test_only_a_cell_has_the_quant_tools(company, stub, board, market):
    stub.play(
        {"do": "list-tools"},
        {"do": "tool", "name": "register_strategy", "arguments": registration()},
        {"do": "tool", "name": "run_backtest", "arguments": {"strategy": "momentum", "code": HOLD}},
    )

    assert company("session", "start", "probe").returncode == 0

    assert {tool["name"] for tool in stub.tool_lists()[-1]["result"]["tools"]} == {"note"}
    assert all(result["result"]["isError"] for result in stub.tool_results())
    assert events("strategy-registered") == []
    assert events("config-run") == []


def test_a_line_nested_past_what_json_can_read_does_not_end_the_server(tools):
    tools.process.stdin.write("[" * 1_000_000 + "\n")
    tools.process.stdin.flush()
    assert json.loads(tools.process.stdout.readline())["error"]["message"] == "not JSON"

    assert not tools.register()["isError"]


def test_a_cells_server_will_not_start_with_no_time_limit():
    arguments = ["-P", "-m", "company.tools", "--role", "cell", "--session", SESSION, "--bet", "alpha"]
    done = subprocess.run([sys.executable, *arguments], stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=30)

    assert done.returncode != 0
    assert "--backtest-seconds" in done.stderr


def test_the_server_has_no_settings_path_and_needs_none(cell_session, stub):
    cell_session({"do": "tool", "name": "register_strategy", "arguments": registration()})

    assert "COMPANY_CONFIG" not in stub.mcp_config()["mcpServers"]["company"]["env"]
    assert os.environ["COMPANY_CONFIG"] not in json.dumps(stub.mcp_config())


# The verdict: the worked values
#
# The deflated Sharpe ratio is Z((SR - SR0) x sqrt(T - 1) / sqrt(1 - skew x SR + (kurtosis - 1) / 4 x SR^2)),
# with SR0 = sqrt(V) x ((1 - g) x Zinv(1 - 1 / N) + g x Zinv(1 - 1 / (N x e))), Bailey and López de Prado's equations 1 and 2.
#
# By hand, one trial: SR 0.1 over T = 101 normal returns, with SR0 0 since one trial has nothing to pick from:
#     0.1 x sqrt(100) / sqrt(1 - 0 + (3 - 1) / 4 x 0.01) = 1 / sqrt(1.005) = 0.99751, and Z(0.99751) = 0.84074.
# By hand, two trials: Zinv(1 / 2) is 0, Zinv(1 - 1 / (2e)) = Zinv(0.81606) = 0.90045 and g = 0.57722, so with V = 0.04:
#     SR0 = 0.2 x 0.57722 x 0.90045 = 0.10395, and on those returns (0.1 - 0.10395) x 10 / sqrt(1.005) = -0.03940, Z of which is 0.48429.
#
# The paper's own example: N = 100, a V of 1/2 a year and an SR of 2.5 a year over 250 bars a year, T = 1250, skew -3, kurtosis 10:
#     SR0 is 0.1132 a bar, and the value 0.9004; with N = 46 the value is 0.9505.
#
# On the worked month, HOLD alone: SR 0.25825, T = 4, skew -0.49684, kurtosis 1.63251, one trial:
#     1 + 0.49684 x 0.25825 + 0.63251 / 4 x 0.25825^2 = 1.13886, and 0.25825 x sqrt(3) / sqrt(1.13886) = 0.41916, Z of which is 0.66245.
# Beside one failed trial there is no spread among the Sharpe ratios, so V is chance's, 1 / (T - 1) = 1 / 3:
#     SR0 = sqrt(1 / 3) x 0.57722 x 0.90045 = 0.30008, and (0.25825 - 0.30008) x sqrt(3) / sqrt(1.13886) = -0.06789, Z of which is 0.47294.
#
# On the holdout, 7777.77 doubling and falling back, HOLD earns 1 - 0.0015 = 0.9985 and then -0.5:
#     holdout_return: 1.9985 x 0.5 - 1 = -0.00075; drawdown 0.5.

FIRST_DAYS = {"min_deflated_sharpe": 0, "min_holdout_return": -1, "max_drawdown": 1}
HOLD_HOLDOUT_RETURNS = [1.0 - 0.0015, -0.5]
HOLD_HOLDOUT_RETURN = -0.00075
FAILS_ON_THE_HOLDOUT = """
def decide(bar, parameters):
    if bar["date"] > "2026-01-31":
        {action}
    return {{"SPY": 1.0}}
"""


def ask_verdict(tools, config, strategy="momentum"):
    return tools.call("request_verdict", {"strategy": strategy, "configuration": config})


def verdict_of(tools, config, strategy="momentum"):
    """A verdict's answer, as the JSON the tool gave; a refusal has to be read with `ask_verdict`."""
    answer = ask_verdict(tools, config, strategy)
    assert not answer["isError"], answer
    return json.loads(text_of(answer))


def holdout_of(code, **changes):
    """The verdict on one configuration, the only one its registration ran."""
    tools = CellTools()
    try:
        assert not tools.register(**changes)["isError"]
        ran = tools.backtest(code)
        assert ran["status"] == "ok", ran
        return verdict_of(tools, ran["config_hash"])
    finally:
        tools.close()


def test_the_deflated_sharpe_ratio_matches_one_trial_worked_by_hand():
    assert treasurer.deflated_sharpe(0.1, 101, 0, 3, threshold=0) == pytest.approx(0.84074, abs=1e-5)


def test_the_expected_maximum_matches_two_trials_worked_by_hand():
    threshold = treasurer.expected_maximum_sharpe(0.04, 2)

    assert threshold == pytest.approx(0.10395, abs=1e-5)
    assert treasurer.deflated_sharpe(0.1, 101, 0, 3, threshold) == pytest.approx(0.48429, abs=1e-5)


@pytest.mark.parametrize(("trials", "threshold", "value"), [(100, 0.1132, 0.9004), (46, 0.1004, 0.9505)])
def test_the_deflated_sharpe_ratio_matches_the_papers_own_example(trials, threshold, value):
    found = treasurer.expected_maximum_sharpe(0.5 / 250, trials)

    assert found == pytest.approx(threshold, abs=5e-5)
    assert treasurer.deflated_sharpe(2.5 / math.sqrt(250), 1250, -3, 10, found) == pytest.approx(value, abs=5e-5)


def test_more_trials_on_the_same_returns_give_a_lower_value():
    values = [treasurer.deflated_sharpe(0.1, 101, 0, 3, treasurer.expected_maximum_sharpe(0.04, trials)) for trials in (1, 2, 5, 25, 100, 1000)]

    assert values == sorted(values, reverse=True)
    assert len(set(values)) == len(values)


def test_one_trial_has_nothing_to_pick_from():
    assert treasurer.expected_maximum_sharpe(0.04, 1) == 0


@pytest.mark.parametrize(
    ("sharpe", "n_returns", "skew", "kurtosis"),
    [
        pytest.param(0.5, 1, 0, 3, id="one return can show nothing"),
        pytest.param(1.0, 100, 2.0, 5.0, id="no spread in the estimate, a two-point distribution's limit"),
        pytest.param(1.0, 100, 4.0, 1.0, id="moments no distribution has"),
        pytest.param(1e200, 100, 0, 1e300, id="past what a float holds"),
    ],
)
def test_a_figure_that_cannot_be_measured_reads_as_no_confidence_at_all(sharpe, n_returns, skew, kurtosis):
    assert treasurer.deflated_sharpe(sharpe, n_returns, skew, kurtosis, threshold=0) == 0


def _run_record(sharpe, status="ok", n_returns=101):
    fields = {"sharpe": sharpe, "n_returns": n_returns, "skew": 0, "kurtosis": 3} if status == "ok" else {}
    return {"status": status, **fields}


def test_the_variance_of_trials_is_the_spread_of_those_that_gave_a_ratio():
    runs = [_run_record(0.0), _run_record(0.6), _run_record(0.0, status="failed"), _run_record(0.3)]
    # The mean is 0.3, so the squares add to 0.09 + 0.09 + 0, and over two degrees of freedom that is 0.09.
    assert treasurer.trials_variance(runs, n_returns=101) == pytest.approx(0.09)


@pytest.mark.parametrize("runs", [[_run_record(0.3)], [_run_record(0.3), _run_record(0.3)], [_run_record(0.3), _run_record(0.3, status="failed")]])
def test_trials_with_no_spread_vary_at_least_as_chance_does(runs):
    """A failed run may have told its cell its figures in its failure, so a search hidden that way cannot leave the threshold at nothing."""
    assert treasurer.trials_variance(runs, n_returns=101) == pytest.approx(1 / 100)


def test_a_spread_past_what_a_float_holds_leaves_no_confidence():
    runs = [_run_record(1e200), _run_record(-1e200), _run_record(1e200)]
    assert treasurer.deflated_sharpe_of(_run_record(1e200), runs) == 0


# The verdict: what the Treasurer computes


def test_the_verdict_is_the_treasurers_with_the_worked_figures(registered):
    ran = registered.backtest(HOLD)
    answer = verdict_of(registered, ran["config_hash"])

    event = events("verdict")[-1]
    assert event["writer"] == "treasurer"
    assert event["registration_seq"] == ran["registration_seq"]
    assert event["config_hash"] == ran["config_hash"]
    assert event["deflated_sharpe"] == pytest.approx(0.66245, abs=1e-5)
    assert event["holdout_return"] == pytest.approx(HOLD_HOLDOUT_RETURN)
    assert event["max_drawdown"] == pytest.approx(0.5)
    assert event["trials"] == 1
    assert event["config_run_seqs"] == [ran["event"]]
    assert answer["event"] == event["seq"]


def test_a_failed_trial_counts_and_the_same_returns_get_a_lower_value(market):
    """The trials were run, and the failure's text could have told the cell how they did, so they count though they have no ratio."""
    tools = CellTools()
    try:
        assert not tools.register()["isError"]
        tools.backtest(strategy_doing("raise RuntimeError('how it did')"))
        ran = tools.backtest(HOLD)
        found = verdict_of(tools, ran["config_hash"])
    finally:
        tools.close()

    assert found["trials"] == 2
    assert found["deflated_sharpe"] == pytest.approx(0.47294, abs=1e-5)


def test_every_trial_run_lowers_the_value_of_the_same_returns(market):
    write_market("copy")
    tools = CellTools()
    try:
        assert not tools.register(strategy="few", max_configurations=10)["isError"]
        assert not tools.register(strategy="many", data_source="fixture:copy", max_configurations=10)["isError"]
        few = tools.backtest(HOLD, strategy="few")
        many = tools.backtest(HOLD, strategy="many")
        for weight in (0.1, -0.5, 0.25, -1):
            tools.backtest(SCALED, {"weight": weight}, strategy="many")
        fewer, more = verdict_of(tools, few["config_hash"], "few"), verdict_of(tools, many["config_hash"], "many")
    finally:
        tools.close()

    assert few["returns_hash"] == many["returns_hash"]
    assert (fewer["trials"], more["trials"]) == (1, 5)
    assert more["deflated_sharpe"] < fewer["deflated_sharpe"]


def _with_later_holdouts():
    return [*IN_SAMPLE_BARS, *HOLDOUT_BARS, bar("2026-03-02", 100), bar("2026-03-03", 101), bar("2026-04-01", 100), bar("2026-04-02", 101)]


def test_a_cells_trials_on_the_in_sample_count_across_its_registrations(market):
    """A new name with a holdout of its own gets a fresh budget on the same in-sample bars, and no fresh count."""
    write_market("daily", _with_later_holdouts())
    tools = CellTools()
    try:
        assert not tools.register(strategy="first")["isError"]
        earlier = tools.backtest(FLAT, strategy="first")
        assert not tools.register(strategy="second", holdout={"start": "2026-03-02", "end": "2026-03-03"})["isError"]
        chosen = tools.backtest(HOLD, strategy="second")
        found = verdict_of(tools, chosen["config_hash"], "second")
    finally:
        tools.close()

    assert found["trials"] == 2
    assert found["config_run_seqs"] == [earlier["event"], chosen["event"]]


def test_an_in_sample_that_overlaps_shares_its_trials_too(market):
    write_market("daily", _with_later_holdouts())
    tools = CellTools()
    try:
        assert not tools.register(strategy="first")["isError"]
        tools.backtest(FLAT, strategy="first")
        moved = {"start": "2026-01-06", "end": "2026-01-09"}
        assert not tools.register(strategy="second", in_sample=moved, holdout={"start": "2026-03-02", "end": "2026-03-03"})["isError"]
        chosen = tools.backtest(HOLD, strategy="second")
        found = verdict_of(tools, chosen["config_hash"], "second")
    finally:
        tools.close()

    assert found["trials"] == 2


def test_trials_on_other_bars_or_by_another_cell_do_not_count(market):
    bars = [*_with_later_holdouts(), bar("2026-05-04", 100), bar("2026-05-05", 101)]
    write_market("daily", bars)
    write_market("elsewhere", bars)
    tools, other = CellTools(), CellTools(bet="beta")
    try:
        assert not tools.register(strategy="first")["isError"]
        tools.backtest(FLAT, strategy="first")
        assert not tools.register(strategy="source", data_source="fixture:elsewhere")["isError"]
        tools.backtest(FLAT, strategy="source")
        march, april = {"start": "2026-03-02", "end": "2026-03-03"}, {"start": "2026-04-01", "end": "2026-04-02"}
        assert not tools.register(strategy="later", in_sample=march, holdout=april)["isError"]
        tools.backtest(FLAT, strategy="later")
        assert not other.register(strategy="theirs", holdout={"start": "2026-05-04", "end": "2026-05-05"})["isError"]
        other.backtest(FLAT, strategy="theirs")

        chosen = tools.backtest(HOLD, strategy="first")
        found = verdict_of(tools, chosen["config_hash"], "first")
    finally:
        tools.close()
        other.close()

    assert found["trials"] == 2


def test_a_verdict_recomputes_from_the_records_it_cites(market):
    tools = CellTools()
    try:
        assert not tools.register(max_configurations=5)["isError"]
        chosen = tools.backtest(HOLD)
        tools.backtest(HOLD_FIRST)
        tools.backtest(SCALED, {"weight": -0.5})
        tools.backtest(strategy_doing("raise RuntimeError('no')"))
        found = verdict_of(tools, chosen["config_hash"])
    finally:
        tools.close()

    event = events("verdict")[-1]
    by_seq = {item["seq"]: item for item in events("config-run")}
    cited = [by_seq[seq] for seq in event["config_run_seqs"]]
    assert sorted(by_seq) == event["config_run_seqs"]
    assert event["trials"] == len(cited) == 4

    selected = next(item for item in cited if item["config_hash"] == event["config_hash"])
    ratios = [item["sharpe"] for item in cited if item["status"] == "ok"]
    mean = sum(ratios) / len(ratios)
    spread = sum((ratio - mean) ** 2 for ratio in ratios) / (len(ratios) - 1)
    threshold = treasurer.expected_maximum_sharpe(max(spread, 1 / (selected["n_returns"] - 1)), len(cited))
    worked = treasurer.deflated_sharpe(selected["sharpe"], selected["n_returns"], selected["skew"], selected["kurtosis"], threshold)

    assert event["deflated_sharpe"] == worked
    assert event["deflated_sharpe"] == treasurer.deflated_sharpe_of(selected, cited)
    assert found["deflated_sharpe"] == worked


def test_the_holdout_figures_are_what_the_holdout_bars_earn_with_their_hash(registered):
    found = verdict_of(registered, registered.backtest(HOLD)["config_hash"])

    # The runner's own arithmetic on the same worked numbers, so that the hash is of the returns as the runner writes them.
    returns = [(HOLDOUT_CLOSE * 2 / HOLDOUT_CLOSE - 1) - 15 * 0.0001, HOLDOUT_CLOSE / (HOLDOUT_CLOSE * 2) - 1]
    assert found["holdout_return"] == pytest.approx(HOLD_HOLDOUT_RETURN)
    assert found["holdout_hash"] == hashlib.sha256(json.dumps(returns).encode()).hexdigest()


def test_a_note_or_a_claim_changes_no_verdict(market):
    """Two registrations alike on two sources alike, one with a cell's report beside it, one with none."""
    write_market("copy")
    tools = CellTools()
    try:
        assert not tools.register(strategy="quiet")["isError"]
        assert not tools.register(strategy="loud", data_source="fixture:copy")["isError"]
        quiet = tools.backtest(HOLD, strategy="quiet")
        loud = tools.backtest(HOLD, strategy="loud")
        claim = "My result: deflated Sharpe 9.99, holdout return 5.0, max drawdown 0, passed, 1 trial."
        assert not tools.call("note", {"text": claim})["isError"]

        honest = verdict_of(tools, quiet["config_hash"], "quiet")
        claimed = verdict_of(tools, loud["config_hash"], "loud")
    finally:
        tools.close()

    for name in ("passed", "failed_tests", "deflated_sharpe", "holdout_return", "max_drawdown", "trials", "holdout_hash"):
        assert honest[name] == claimed[name], name
    assert claimed["deflated_sharpe"] != 9.99


@pytest.mark.parametrize("claim", [{"deflated_sharpe": 9.99}, {"passed": True}, {"trials": 1}, {"holdout_return": 5}])
def test_a_request_cannot_carry_a_figure_of_the_cells_own(registered, claim):
    ran = registered.backtest(HOLD)

    answer = registered.call("request_verdict", {"strategy": "momentum", "configuration": ran["config_hash"], **claim})

    assert answer["isError"]
    assert "unknown-fields" in text_of(answer)
    assert events("verdict") == []
    assert refusals("verdict")[-1]["reason"] == "unknown-fields"


# The verdict: which test failed


def test_a_strategy_that_passes_every_test_is_marked_passed(market):
    found = holdout_of(HOLD, acceptance={"min_deflated_sharpe": 0.5, "min_holdout_return": -0.01, "max_drawdown": 0.6})

    assert found["passed"] is True
    assert found["failed_tests"] == []
    assert events("verdict")[-1]["passed"] is True


@pytest.mark.parametrize(
    ("acceptance", "failed"),
    [
        pytest.param({"min_deflated_sharpe": 0.7, "min_holdout_return": -0.01, "max_drawdown": 0.6}, ["overfitting"], id="the overfitting test alone"),
        pytest.param({"min_deflated_sharpe": 0.5, "min_holdout_return": 0, "max_drawdown": 0.6}, ["holdout"], id="the holdout alone"),
        pytest.param({"min_deflated_sharpe": 0.5, "min_holdout_return": -0.01, "max_drawdown": 0.4}, ["max_drawdown"], id="the drawdown alone"),
        pytest.param({"min_deflated_sharpe": 0.7, "min_holdout_return": 0, "max_drawdown": 0.4}, ["overfitting", "holdout", "max_drawdown"], id="all three"),
    ],
)
def test_a_strategy_that_fails_a_test_is_marked_failed_and_the_verdict_says_which(market, acceptance, failed):
    found = holdout_of(HOLD, acceptance=acceptance)

    assert found["passed"] is False
    assert found["failed_tests"] == failed
    assert events("verdict")[-1]["failed_tests"] == failed


def test_figures_exactly_at_the_registered_limits_pass(market):
    """A flat strategy sits exactly on each limit here, and being at a limit is no failure."""
    found = holdout_of(FLAT, acceptance={"min_deflated_sharpe": 0, "min_holdout_return": 0, "max_drawdown": 0})

    assert found["holdout_return"] == 0
    assert found["max_drawdown"] == 0
    assert found["passed"] is True


def test_the_drawdown_is_the_worse_of_the_in_sample_and_the_holdout(market):
    """A short holdout must not hide what the backtest recorded: this one loses in-sample, and sits flat through the holdout."""
    code = """
def decide(bar, parameters):
    return {"SPY": 1.0} if bar["date"] < "2026-01-31" else {}
"""
    found = holdout_of(code, acceptance={"min_deflated_sharpe": 0, "min_holdout_return": -1, "max_drawdown": 0.05})

    assert found["max_drawdown"] == pytest.approx(0.10)
    assert found["failed_tests"] == ["max_drawdown"]


def test_a_strategy_keeps_what_it_learned_in_sample_into_the_holdout(market):
    """A look-back would otherwise sit flat through a short holdout, and pass a return floor of zero by never trading."""
    looks_back = """
seen = 0
def decide(bar, parameters):
    global seen
    seen += 1
    return {"SPY": 1.0} if seen > 5 else {}
"""
    found = holdout_of(looks_back, acceptance=FIRST_DAYS)

    assert found["holdout_return"] == pytest.approx(HOLD_HOLDOUT_RETURN)


@pytest.mark.parametrize(
    ("action", "failure"),
    [
        pytest.param("raise RuntimeError(str(bar))", "crashed", id="crash"),
        pytest.param("return {'SPY': str(bar)}", "bad-output", id="rubbish"),
        pytest.param("raise SystemExit(0)", "crashed", id="exit"),
    ],
)
def test_a_strategy_that_fails_on_the_holdout_fails_its_verdict_and_says_only_how(market, action, failure):
    tools = CellTools()
    try:
        assert not tools.register()["isError"]
        ran = tools.backtest(FAILS_ON_THE_HOLDOUT.format(action=action))
        assert ran["status"] == "ok"
        found = verdict_of(tools, ran["config_hash"])
        received = "".join(tools.received)
    finally:
        tools.close()

    assert found["passed"] is False
    assert "holdout" in found["failed_tests"]
    assert found["holdout_failure"] == failure
    assert found["holdout_return"] is None
    assert found["holdout_hash"] is None
    assert HOLDOUT_MARKER not in received
    assert str(HOLDOUT_CLOSE) not in received
    assert HOLDOUT_MARKER not in json.dumps(events())


def test_a_strategy_that_hangs_on_the_holdout_fails_its_verdict(market):
    tools = CellTools(seconds=1)
    try:
        assert not tools.register()["isError"]
        ran = tools.backtest(FAILS_ON_THE_HOLDOUT.format(action="import time; time.sleep(600)"))
        found = verdict_of(tools, ran["config_hash"])
    finally:
        tools.close()

    assert found["holdout_failure"] == "timed-out"
    assert "holdout" in found["failed_tests"]


def test_the_holdout_run_has_the_time_per_bar_the_backtest_had(registered, monkeypatch):
    """Four bars were backtested and seven are fed here, so a strategy that fit its limit is not failed for the longer run."""
    ran = registered.backtest(FLAT)
    limits = []
    real_timer = threading.Timer

    def noting(interval, function):
        limits.append(interval)
        return real_timer(interval, function)

    monkeypatch.setattr(quant.threading, "Timer", noting)
    quant.verdict({"strategy": "momentum", "configuration": ran["config_hash"]}, "cell:alpha", 8)

    assert limits == [pytest.approx(14)]


# The verdict: once per registration, and only for what ran


def test_a_second_verdict_is_refused_and_logged(registered):
    first = registered.backtest(HOLD)
    second = registered.backtest(FLAT)
    verdict_of(registered, first["config_hash"])

    for config in (first["config_hash"], second["config_hash"]):
        answer = ask_verdict(registered, config)

        assert answer["isError"]
        assert "verdict-given" in text_of(answer)

    assert len(events("verdict")) == 1
    assert [event["reason"] for event in refusals("verdict")] == ["verdict-given", "verdict-given"]
    assert refusals("verdict")[-1]["attempted_writer"] == "cell:alpha"
    assert refusals("verdict")[-1]["tool"] == "request_verdict"


def test_two_requests_racing_get_one_verdict(market):
    first, second = CellTools(), CellTools()
    try:
        assert not first.register()["isError"]
        config = first.backtest(HOLD)["config_hash"]
        answers = []
        threads = [threading.Thread(target=lambda tool=tool: answers.append(ask_verdict(tool, config))) for tool in (first, second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    finally:
        first.close()
        second.close()

    assert sorted(answer["isError"] for answer in answers) == [False, True]
    assert len(events("verdict")) == 1


def test_a_new_name_cannot_buy_a_second_verdict_on_the_same_holdout(registered):
    verdict_of(registered, registered.backtest(HOLD)["config_hash"])

    answer = registered.register(strategy="again")

    assert answer["isError"]
    assert "holdout-already-held" in text_of(answer)


def test_a_verdict_before_any_registration_is_refused_and_logged(tools):
    answer = ask_verdict(tools, "0" * 64)

    assert answer["isError"]
    assert refusals("verdict")[-1]["reason"] == "no-registration"


def test_a_verdict_on_another_cells_registration_is_refused(registered, market):
    config = registered.backtest(HOLD)["config_hash"]
    other = CellTools(bet="beta")
    try:
        answer = ask_verdict(other, config)
    finally:
        other.close()

    assert answer["isError"]
    assert refusals("verdict")[-1]["reason"] == "no-registration"
    assert events("verdict") == []


def test_a_configuration_never_run_cannot_be_named(registered):
    registered.backtest(HOLD)

    answer = ask_verdict(registered, quant.config_hash(FLAT, {}))

    assert answer["isError"]
    assert refusals("verdict")[-1]["reason"] == "configuration-not-run"
    assert events("verdict") == []


def test_a_configuration_run_only_under_another_registration_cannot_be_named(market):
    write_market("daily", _with_later_holdouts())
    tools = CellTools()
    try:
        assert not tools.register(strategy="first")["isError"]
        config = tools.backtest(HOLD, strategy="first")["config_hash"]
        assert not tools.register(strategy="second", holdout={"start": "2026-03-02", "end": "2026-03-03"})["isError"]
        tools.backtest(FLAT, strategy="second")

        answer = ask_verdict(tools, config, "second")
    finally:
        tools.close()

    assert answer["isError"]
    assert refusals("verdict")[-1]["reason"] == "configuration-not-run"


def test_a_failed_configuration_cannot_be_named_and_spends_no_verdict(registered):
    failed = registered.backtest(strategy_doing("raise RuntimeError('no')"))
    good = registered.backtest(HOLD)

    answer = ask_verdict(registered, failed["config_hash"])

    assert answer["isError"]
    assert refusals("verdict")[-1]["reason"] == "configuration-failed"
    assert verdict_of(registered, good["config_hash"])["trials"] == 2


@pytest.mark.parametrize(
    "arguments",
    [
        pytest.param({}, id="nothing"),
        pytest.param({"strategy": "momentum"}, id="no configuration"),
        pytest.param({"configuration": "0" * 64}, id="no strategy"),
        pytest.param({"strategy": 1, "configuration": "0" * 64}, id="a strategy that is no name"),
        pytest.param({"strategy": "momentum", "configuration": ["0"]}, id="a configuration that is no hash"),
    ],
)
def test_a_request_whose_arguments_name_nothing_is_refused(registered, arguments):
    registered.backtest(HOLD)

    answer = registered.call("request_verdict", arguments)

    assert answer["isError"]
    assert refusals("verdict")[-1]["reason"] == "bad-arguments"
    assert events("verdict") == []


# The verdict: what stops it, at no cost


def test_data_changed_since_the_registration_gives_no_verdict_and_spends_none(registered, market):
    config = registered.backtest(HOLD)["config_hash"]
    original = market.read_text()
    market.write_text(original + json.dumps(bar("2026-03-02", 1)) + "\n")

    answer = ask_verdict(registered, config)

    assert answer["isError"]
    assert "did not run" in text_of(answer)
    assert events("verdict") == []
    assert events("config-refused")[-1]["reason"] == "data-changed"
    assert events("config-refused")[-1]["config_hash"] == config

    market.write_text(original)
    assert verdict_of(registered, config)["trials"] == 1


def test_data_gone_gives_no_verdict(registered, market):
    config = registered.backtest(HOLD)["config_hash"]
    market.unlink()

    assert ask_verdict(registered, config)["isError"]
    assert events("verdict") == []
    assert events("config-refused")[-1]["reason"] == "data-changed"


def test_with_no_bwrap_nothing_runs_on_the_holdout_and_no_verdict_is_spent(registered, monkeypatch, tmp_path):
    config = registered.backtest(HOLD)["config_hash"]
    monkeypatch.setattr(quant, "SYSTEM_PATH", str(tmp_path / "empty"))

    with pytest.raises(quant.Logged) as refused:
        quant.verdict({"strategy": "momentum", "configuration": config}, "cell:alpha", 5)

    assert refused.value.reason == "no-confinement"
    assert events("verdict") == []
    # The tools' own server has the system's path, and asks again as if the machine were mended.
    assert verdict_of(registered, config)["trials"] == 1


@pytest.mark.parametrize(
    "damage",
    [
        pytest.param(lambda path: path.unlink(), id="gone"),
        pytest.param(lambda path: path.write_text("{"), id="not JSON"),
        pytest.param(lambda path: path.write_text("[1]"), id="no object"),
        pytest.param(lambda path: path.write_text(json.dumps({"code": HOLD})), id="no parameters"),
        pytest.param(lambda path: path.write_text(json.dumps({"code": FLAT, "parameters": {}})), id="other code than the record names"),
    ],
)
def test_a_kept_configuration_that_is_not_what_ran_is_never_run(registered, damage):
    ran = registered.backtest(HOLD)
    damage(paths.configurations() / str(ran["registration_seq"]) / f"{ran['config_hash']}.json")

    answer = ask_verdict(registered, ran["config_hash"])

    assert answer["isError"]
    assert events("verdict") == []
    assert events("config-refused")[-1]["reason"] == "configuration-lost"


# The verdict: what the cell sees


VERDICT_FIELDS = {"registration_seq", "config_hash", "passed", "failed_tests", "deflated_sharpe", "holdout_return", "max_drawdown", "trials", "config_run_seqs", "holdout_hash"}


def _home_files_but_the_bars():
    return [path for path in paths.home().rglob("*") if path.is_file() and path.parent.name != "market-data"]


def _holds_a_holdout_figure(text):
    """Whether the text holds a holdout bar's mark or price, or either of HOLD's returns on those bars."""
    figures = (HOLDOUT_MARKER, str(HOLDOUT_CLOSE), json.dumps(HOLD_HOLDOUT_RETURNS[0]), json.dumps(HOLD_HOLDOUT_RETURNS[1]), "2026-02-03")
    return [figure for figure in figures if figure in text]


def test_after_its_verdict_the_cell_has_only_the_verdicts_fields(registered):
    ran = registered.backtest(HOLD)
    before = "".join(registered.received)
    answer = ask_verdict(registered, ran["config_hash"])
    told = json.loads(text_of(answer))

    assert set(told) == {"event", *VERDICT_FIELDS}
    event = events("verdict")[-1]
    assert {name: told[name] for name in VERDICT_FIELDS} == {name: event[name] for name in VERDICT_FIELDS}
    assert _holds_a_holdout_figure(before) == []
    assert _holds_a_holdout_figure(json.dumps(answer)) == []


def test_no_record_or_file_of_the_company_holds_a_holdout_figure_before_or_after(registered):
    """A view of the ledger can show only what the ledger holds, and whatever view a later ticket builds shows none of this."""
    ran = registered.backtest(HOLD)
    assert all(_holds_a_holdout_figure(path.read_text()) == [] for path in _home_files_but_the_bars())

    verdict_of(registered, ran["config_hash"])

    assert all(_holds_a_holdout_figure(path.read_text()) == [] for path in _home_files_but_the_bars())


def test_a_strategy_that_tries_to_say_a_holdout_bar_says_nothing(market):
    """The one code handed a holdout bar is the cell's, in the sandbox, and it speaks only through positions and a failure."""
    spy = """
import sys
def decide(bar, parameters):
    if bar["date"] > "2026-01-31":
        print(bar)
        sys.stderr.write(str(bar))
        raise RuntimeError("seen: " + str(bar))
    return {}
"""
    tools = CellTools()
    try:
        assert not tools.register()["isError"]
        ran = tools.backtest(spy)
        verdict_of(tools, ran["config_hash"])
        received = "".join(tools.received)
    finally:
        tools.close()

    assert _holds_a_holdout_figure(received) == []
    assert all(_holds_a_holdout_figure(path.read_text()) == [] for path in _home_files_but_the_bars())


def test_only_the_treasurer_may_write_a_verdict(registered):
    ran = registered.backtest(HOLD)
    fields = {name: 1 for name in VERDICT_FIELDS} | {"registration_seq": ran["registration_seq"], "config_run_seqs": [ran["event"]]}

    with pytest.raises(AppendRefused):
        Ledger().append("verdict", fields, "cell:alpha")

    assert events("verdict") == []


def test_a_stub_cell_gets_its_verdict_through_the_real_tools(cell_session, stub):
    config = quant.config_hash(HOLD, {})
    done = cell_session(
        {"do": "list-tools"},
        {"do": "tool", "name": "register_strategy", "arguments": registration()},
        {"do": "tool", "name": "request_verdict", "arguments": {"strategy": "momentum", "configuration": config}},
        {"do": "tool", "name": "run_backtest", "arguments": {"strategy": "momentum", "code": HOLD}},
        {"do": "tool", "name": "note", "arguments": {"text": "I expect 9.99."}},
        {"do": "tool", "name": "request_verdict", "arguments": {"strategy": "momentum", "configuration": config}},
        {"do": "tool", "name": "request_verdict", "arguments": {"strategy": "momentum", "configuration": config}},
    )

    assert done.returncode == 0, done.stdout + done.stderr
    assert "request_verdict" in {tool["name"] for tool in stub.tool_lists()[-1]["result"]["tools"]}
    assert "mcp__company__request_verdict" in stub.argument("--allowedTools").split(",")
    _, too_early, _, _, given, second = stub.tool_results()
    assert too_early["result"]["isError"]
    assert json.loads(_tool_text(given))["deflated_sharpe"] == pytest.approx(0.66245, abs=1e-5)
    assert second["result"]["isError"]
    assert len(events("verdict")) == 1
    assert events("verdict")[-1]["writer"] == "treasurer"
    received = json.dumps(stub.tool_results())
    assert HOLDOUT_MARKER not in received
    assert str(HOLDOUT_CLOSE) not in received


def test_only_a_cell_has_the_verdict_tool(company, stub, board, market):
    stub.play({"do": "tool", "name": "request_verdict", "arguments": {"strategy": "momentum", "configuration": "0" * 64}})

    assert company("session", "start", "probe").returncode == 0

    assert stub.tool_results()[-1]["result"]["isError"]
    assert refusals("verdict")[-1]["reason"] == "tool-not-in-role"
