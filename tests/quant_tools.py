"""What the quant cell's tests and the paper period's share: the worked bars, and one cell's company tools over stdio."""

import json
import subprocess
import sys

from company import paths

SESSION = "eeeeeeee-0000-4000-8000-000000000000"
HOLDOUT_MARKER = "HOLDOUT-MARKER-71f3"
IN_SAMPLE_MARKER = "IN-SAMPLE-MARKER-2c9a"
# A close no in-sample bar has, so that a holdout price cannot pass unseen as a number.
HOLDOUT_CLOSE = 7777.77

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


def ask_verdict(tools, config, strategy="momentum"):
    return tools.call("request_verdict", {"strategy": strategy, "configuration": config})


def verdict_of(tools, config, strategy="momentum"):
    """A verdict's answer, as the JSON the tool gave; a refusal has to be read with `ask_verdict`."""
    answer = ask_verdict(tools, config, strategy)
    assert not answer["isError"], answer
    return json.loads(text_of(answer))
