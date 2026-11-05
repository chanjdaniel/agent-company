"""The quant cell's rules: registration, the search budget, and the runner that backtests a strategy outside its session.

The company tools call this, so it runs in their process, outside the session's sandbox, where the agent's shell cannot reach.
A strategy is code a cell wrote, so it runs in its own `bwrap` with no network, no writes and a time limit, and there is no other way to run one.
It is given the in-sample bars one at a time, and the holdout never leaves this process: nothing here passes a holdout bar on.
"""

import contextlib
import fcntl
import hashlib
import itertools
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from company import paths
from company.ledger import Ledger

# Fixed, so that the sandbox's binary never comes from a path a caller chose. A test replaces this.
SYSTEM_PATH = "/usr/local/bin:/usr/bin:/bin"
MAX_CODE_CHARACTERS = 1_000_000
MAX_FAILURE_CHARACTERS = 300
DEFAULT_PAPER_DAYS = 90

_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9./-]{0,15}")
_FIXTURE = re.compile(r"fixture:(?P<name>[a-z0-9][a-z0-9_-]{0,63})")
_REQUIRED = ("strategy", "universe", "data_source", "in_sample", "holdout", "cost_model", "slippage_model", "max_configurations", "acceptance")
_OPTIONAL = ("paper_days",)
_ACCEPTANCE = ("min_deflated_sharpe", "min_holdout_return", "max_drawdown")
_MIN_BARS = 2
_BASIS_POINT = 0.0001
# A position line past this is rubbish, whether or not it ever ends.
_MAX_LINE_BYTES = 1_000_000
_TOLERANCE = 1e-9
_CHILD_PATH = "/runner/child.py"
_ROOT_DIRECTORIES = ("bin", "sbin", "lib", "lib32", "lib64")
_OK, _FAILED = "ok", "failed"
_TIMED_OUT = "timed-out"
_ENDED = "ended-early"
_BAD_OUTPUT = "bad-output"


class Refused(Exception):
    """Nothing happened, and the caller logs why; `reason` is a code naming no rejected value."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class Logged(Exception):
    """A backtest of a registration did not run, and event `seq`, a `config-refused`, says why."""

    def __init__(self, reason: str, seq: int):
        super().__init__(reason)
        self.reason, self.seq = reason, seq


class _NoConfinement(Exception):
    """No sandbox started, so no code of the cell's ran, and the reason is no fault of the strategy's."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class _StrategyFailed(Exception):
    """The strategy did not give a position for every bar."""


@dataclass(frozen=True)
class _Market:
    """A data source's bars, oldest first, and the hash of what they were read from."""

    bars: list[dict]
    digest: str


def _is_number(value) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _is_whole(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _period(value) -> tuple[date, date] | None:
    """A registered period's first and last days, or None if it is no period."""
    if not isinstance(value, dict) or set(value) != {"start", "end"}:
        return None
    try:
        start, end = date.fromisoformat(value["start"]), date.fromisoformat(value["end"])
    except (TypeError, ValueError):
        return None
    return (start, end) if start <= end else None


def _is_model(value) -> bool:
    return isinstance(value, dict) and set(value) == {"bps_per_turnover"} and _is_number(value["bps_per_turnover"]) and value["bps_per_turnover"] >= 0


def _is_universe(value) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(symbol, str) and _SYMBOL.fullmatch(symbol) for symbol in value)
        and len(set(value)) == len(value)
    )


def _is_acceptance(value) -> bool:
    return isinstance(value, dict) and set(value) == set(_ACCEPTANCE) and all(_is_number(value[name]) for name in _ACCEPTANCE)


_FIELD_CHECKS = {
    "strategy": lambda value: isinstance(value, str) and _NAME.fullmatch(value) is not None,
    "universe": _is_universe,
    "data_source": lambda value: isinstance(value, str),
    "in_sample": lambda value: _period(value) is not None,
    "holdout": lambda value: _period(value) is not None,
    "cost_model": _is_model,
    "slippage_model": _is_model,
    "max_configurations": _is_whole,
    "acceptance": _is_acceptance,
    "paper_days": _is_whole,
}


def _checked_registration(arguments: dict) -> dict:
    if set(arguments) - set(_REQUIRED) - set(_OPTIONAL):
        raise Refused("unknown-fields")
    missing = [name for name in _REQUIRED if name not in arguments]
    if missing:
        raise Refused("missing-fields:" + ",".join(missing))
    for name, value in arguments.items():
        if not _FIELD_CHECKS[name](value):
            raise Refused(f"bad-field:{name}")
    if _period(arguments["holdout"])[0] <= _period(arguments["in_sample"])[1]:  # type: ignore[index]
        raise Refused("holdout-not-after-in-sample")
    return {"paper_days": DEFAULT_PAPER_DAYS, **arguments}


def _is_bar(item) -> bool:
    if not isinstance(item, dict) or not isinstance(item.get("bars"), dict) or not isinstance(item.get("date"), str):
        return False
    return all(isinstance(fields, dict) and _is_number(fields.get("close")) and fields["close"] > 0 for fields in item["bars"].values())


def _market_data(source: str) -> _Market:
    """A data source's bars; raise `Refused` if it is no source this company has, or what it holds cannot be read as bars."""
    match = _FIXTURE.fullmatch(source)
    if match is None:
        raise Refused("data-unavailable:no-such-source")
    try:
        content = (paths.market_data() / f"{match['name']}.jsonl").read_bytes()
    except FileNotFoundError:
        raise Refused("data-unavailable:no-such-source") from None
    except OSError:
        raise Refused("data-unavailable:unreadable") from None
    try:
        bars = [json.loads(line) for line in content.splitlines()]
        days = [date.fromisoformat(item["date"]) for item in bars]
    except (ValueError, KeyError, TypeError, RecursionError):
        raise Refused("data-unavailable:unreadable") from None
    if not bars or not all(_is_bar(item) for item in bars) or any(later <= earlier for earlier, later in itertools.pairwise(days)):
        raise Refused("data-unavailable:unreadable")
    return _Market(bars, hashlib.sha256(content).hexdigest())


def _in_period(market: _Market, period: dict, universe: list[str]) -> list[dict] | None:
    """The bars of a period, holding the universe alone; None if a day lacks a symbol or the period has too few to give a return."""
    start, end = _period(period)  # type: ignore[misc]
    chosen = [item for item in market.bars if start <= date.fromisoformat(item["date"]) <= end]
    if len(chosen) < _MIN_BARS or any(symbol not in item["bars"] for item in chosen for symbol in universe):
        return None
    return [{"date": item["date"], "bars": {symbol: item["bars"][symbol] for symbol in universe}} for item in chosen]


def _overlap(one: dict, other: dict) -> bool:
    first, second = _period(one), _period(other)
    return first is not None and second is not None and first[0] <= second[1] and second[0] <= first[1]


def _registrations(events: list[dict]) -> list[dict]:
    return [event for event in events if event["kind"] == "strategy-registered"]


def _runs_of(events: list[dict], seq: int) -> list[dict]:
    return [event for event in events if event["kind"] == "config-run" and event["registration_seq"] == seq]


def _same_strategy(event: dict, writer: str, strategy: str) -> bool:
    return event["writer"] == writer and event["strategy"] == strategy


def _check_periods_unspent(events: list[dict], fields: dict, writer: str) -> None:
    """Keep a holdout unseen: no later in-sample period may read an earlier holdout, nor any holdout be what a strategy could read.

    A registration that was replaced ran nothing, so only the newest of each strategy holds its periods, and this one replaces its own.
    """
    standing = {(event["writer"], event["strategy"]): event for event in _registrations(events)}
    for earlier in standing.values():
        if earlier["data_source"] != fields["data_source"] or _same_strategy(earlier, writer, fields["strategy"]):
            continue
        if _overlap(fields["in_sample"], earlier["holdout"]):
            raise Refused("holdout-already-held")
        if _overlap(fields["holdout"], earlier["in_sample"]):
            raise Refused("holdout-already-seen")


@contextlib.contextmanager
def _locked() -> Iterator[None]:
    """One registration or backtest at a time, so that two sessions cannot both spend a budget's last run.

    The strategy's time limit bounds how long this is held.
    """
    paths.home().mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(paths.home() / "quant.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def register(arguments: dict, writer: str) -> dict:
    """Log a cell's registration, with the data's hash filled in here; raise `Refused` if it may not stand.

    It may be replaced until its first run cites it, and the newest of a strategy's registrations is the one that counts.
    """
    fields = _checked_registration(arguments)
    with _locked():
        ledger = Ledger()
        events = ledger.read()
        own = (event for event in _registrations(events) if _same_strategy(event, writer, fields["strategy"]))
        if any(_runs_of(events, event["seq"]) for event in own):
            raise Refused("registration-closed")
        market = _market_data(fields["data_source"])
        if _in_period(market, fields["in_sample"], fields["universe"]) is None or _in_period(market, fields["holdout"], fields["universe"]) is None:
            raise Refused("data-unavailable:not-covered")
        _check_periods_unspent(events, fields, writer)
        return ledger.append("strategy-registered", {**fields, "data_hash": market.digest}, writer)


def config_hash(code: str, parameters: dict) -> str:
    """A configuration's identity: the hash of its code and parameters, whichever order they were written in."""
    canonical = json.dumps({"code": code, "parameters": parameters}, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _checked_configuration(arguments: dict) -> tuple[str, str, dict, str]:
    strategy, code, parameters = arguments.get("strategy"), arguments.get("code"), arguments.get("parameters", {})
    if not isinstance(strategy, str) or not isinstance(code, str) or not code or len(code) > MAX_CODE_CHARACTERS or not isinstance(parameters, dict):
        raise Refused("bad-arguments")
    try:
        return strategy, code, parameters, config_hash(code, parameters)
    except (ValueError, RecursionError):
        raise Refused("bad-arguments") from None


def _keep_configuration(registration_seq: int, digest: str, code: str, parameters: dict) -> None:
    """Keep what the verdict will run on the holdout, where no session can reach it, before any record cites it."""
    folder = paths.configurations() / str(registration_seq)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(folder / f"{digest}.json", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as file:
        json.dump({"code": code, "parameters": parameters}, file)


def _sandbox(bwrap: str) -> list[str]:
    """The sandbox: every namespace unshared, nothing writable, and of this machine only the system's files and Python."""
    python = os.path.realpath(sys.executable)
    standard_library = str(Path(os.__file__).resolve().parent.parent)
    root: list[str] = []
    for name in _ROOT_DIRECTORIES:
        path = Path("/") / name
        if path.is_symlink():
            root += ["--symlink", os.readlink(path), str(path)]
        elif path.is_dir():
            root += ["--ro-bind", str(path), str(path)]
    child = str(Path(__file__).with_name("strategy_child.py"))
    return [
        bwrap,
        "--unshare-all", "--die-with-parent", "--new-session",
        "--ro-bind", "/usr", "/usr",
        *root,
        "--ro-bind", standard_library, standard_library,
        "--ro-bind", python, python,
        "--ro-bind", child, _CHILD_PATH,
        "--chdir", "/",
        "--remount-ro", "/",
        python, "-I", "-S", "-B", _CHILD_PATH,
    ]  # fmt: skip


def _no_constant(name: str):
    raise ValueError(name)


def _read_message(process: subprocess.Popen) -> dict | None:
    """The strategy's next line as an object, or None if it ended first; anything else is rubbish."""
    line = process.stdout.readline(_MAX_LINE_BYTES)  # type: ignore[union-attr]
    if not line:
        return None
    if not line.endswith(b"\n"):
        if len(line) < _MAX_LINE_BYTES:
            return None
        raise _StrategyFailed(f"{_BAD_OUTPUT}: a line too long")
    try:
        message = json.loads(line, parse_constant=_no_constant)
    except (ValueError, RecursionError):
        raise _StrategyFailed(f"{_BAD_OUTPUT}: not JSON") from None
    if not isinstance(message, dict):
        raise _StrategyFailed(f"{_BAD_OUTPUT}: not an object")
    return message


def _send(process: subprocess.Popen, message: dict) -> None:
    process.stdin.write((json.dumps(message) + "\n").encode())  # type: ignore[union-attr]
    process.stdin.flush()  # type: ignore[union-attr]


def _positions(message: dict | None, universe: list[str]) -> dict[str, float]:
    """The target weights in one answer, which may together hold at most the account's whole value."""
    if message is None:
        raise _StrategyFailed(_ENDED)
    if set(message) == {"error"}:
        raise _StrategyFailed(f"crashed: {message['error']}")
    positions = message.get("positions") if set(message) == {"positions"} else None
    if not isinstance(positions, dict) or not all(symbol in universe for symbol in positions):
        raise _StrategyFailed(f"{_BAD_OUTPUT}: not positions in the universe")
    for value in positions.values():
        if not isinstance(value, int | float) or isinstance(value, bool) or not abs(value) <= 1:
            raise _StrategyFailed(f"{_BAD_OUTPUT}: a position that is not a weight from -1 to 1")
    if sum(abs(value) for value in positions.values()) > 1 + _TOLERANCE:
        raise _StrategyFailed(f"{_BAD_OUTPUT}: positions past the account's whole value")
    return {symbol: float(value) for symbol, value in positions.items()}


def _play(code: str, parameters: dict, bars: list[dict], universe: list[str], seconds: float) -> list[dict[str, float]]:
    """The strategy's positions, one per bar, each sent only once it has answered the last.

    Raise `_NoConfinement` if no sandbox started, and `_StrategyFailed` if the strategy failed in one.
    """
    bwrap = shutil.which("bwrap", path=SYSTEM_PATH)
    if bwrap is None:
        raise _NoConfinement("no-confinement")
    expired = threading.Event()
    try:
        # It stays in this process's group, so that a session's stop reaches it, and `--die-with-parent` covers the rest.
        process = subprocess.Popen(_sandbox(bwrap), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env={}, cwd="/")
    except OSError:
        raise _NoConfinement("no-confinement") from None

    def expire() -> None:
        expired.set()
        process.kill()

    timer = threading.Timer(seconds, expire)
    timer.start()
    try:
        return _exchange(process, {"code": code, "parameters": parameters}, bars, universe)
    except BrokenPipeError:
        raise _StrategyFailed(_TIMED_OUT if expired.is_set() else _ENDED) from None
    except _StrategyFailed as failed:
        # However the end looked from here, a killed strategy's came from the limit.
        raise _StrategyFailed(_TIMED_OUT) if expired.is_set() else failed from None
    finally:
        timer.cancel()
        process.kill()
        process.wait()
        for pipe in (process.stdin, process.stdout):
            with contextlib.suppress(OSError):
                pipe.close()  # type: ignore[union-attr]


def _exchange(process: subprocess.Popen, configuration: dict, bars: list[dict], universe: list[str]) -> list[dict[str, float]]:
    try:
        ready = _read_message(process)
    except _StrategyFailed:
        ready = None
    if ready != {"ready": True}:
        raise _NoConfinement("confinement-failed")
    _send(process, configuration)
    positions = []
    for item in bars:
        _send(process, item)
        positions.append(_positions(_read_message(process), universe))
    return positions


def _returns(bars: list[dict], positions: list[dict[str, float]], cost_per_turnover: float) -> list[float]:
    """Each bar's position earns the move to the next bar, less the registered costs of the change it took to reach it."""
    returns = []
    held: dict[str, float] = {}
    for item, following, target in zip(bars, bars[1:], positions, strict=False):
        turnover = sum(abs(target.get(symbol, 0.0) - held.get(symbol, 0.0)) for symbol in item["bars"])
        moved = sum(weight * (following["bars"][symbol]["close"] / item["bars"][symbol]["close"] - 1) for symbol, weight in target.items())
        returns.append(moved - turnover * cost_per_turnover)
        held = target
    return returns


def _measures(returns: list[float]) -> dict | None:
    """What a verdict reads of a run, per bar and not annualized; None if the numbers are past what a float holds."""
    count = len(returns)
    try:
        mean = math.fsum(returns) / count
        second, third, fourth = (math.fsum((value - mean) ** power for value in returns) / count for power in (2, 3, 4))
        equity, peak, drawdown = 1.0, 1.0, 0.0
        for value in returns:
            equity *= 1 + value
            peak = max(peak, equity)
            drawdown = max(drawdown, (peak - equity) / peak)
        # With no variance, or with one return, there is no spread to measure against, so these read as a normal's.
        sharpe, skew, kurtosis = (0.0, 0.0, 3.0) if second == 0 else (mean / math.sqrt(second * count / (count - 1)), third / second**1.5, fourth / second**2)
    except (OverflowError, ZeroDivisionError, ValueError):
        return None
    numbers = {"sharpe": sharpe, "skew": skew, "kurtosis": kurtosis, "total_return": equity - 1, "max_drawdown": drawdown}
    if not all(math.isfinite(value) for value in numbers.values()):
        return None
    return {"n_returns": count, **numbers, "returns_hash": hashlib.sha256(json.dumps(returns).encode()).hexdigest()}


def _result(code: str, parameters: dict, registration: dict, bars: list[dict], seconds: float) -> dict:
    """The record of one run, whichever way it went."""
    fed = bars[:-1]
    try:
        positions = _play(code, parameters, fed, registration["universe"], seconds)
    except _StrategyFailed as failed:
        return {"status": _FAILED, "failure": str(failed)[:MAX_FAILURE_CHARACTERS]}
    cost = (registration["cost_model"]["bps_per_turnover"] + registration["slippage_model"]["bps_per_turnover"]) * _BASIS_POINT
    measures = _measures(_returns(bars, positions, cost))
    if measures is None:
        return {"status": _FAILED, "failure": "not-finite"}
    return {"status": _OK, **measures}


def _answer(run: dict, registration: dict, repeat: bool) -> dict:
    """What the cell is told of a run: the record's own numbers, all of them from the in-sample bars."""
    ledger_only = ("seq", "ts", "kind", "writer", "prev")
    return {
        "event": run["seq"],
        "repeat": repeat,
        "budget": registration["max_configurations"],
        **{name: value for name, value in run.items() if name not in ledger_only},
    }


def run(arguments: dict, writer: str, seconds: float) -> dict:
    """Backtest one configuration on the in-sample bars, or return the stored result of one already run.

    Raise `Refused` if there is no registration to cite, and `Logged` once a `config-refused` has cited it.
    """
    strategy, code, parameters, digest = _checked_configuration(arguments)
    with _locked():
        ledger = Ledger()
        events = ledger.read()
        own = [event for event in _registrations(events) if _same_strategy(event, writer, strategy)]
        if not own:
            raise Refused("no-registration")
        registration = own[-1]
        seq = registration["seq"]

        def refuse(reason: str) -> Logged:
            fields = {"registration_seq": seq, "config_hash": digest, "reason": reason}
            return Logged(reason, ledger.append("config-refused", fields, "runner")["seq"])

        runs = _runs_of(events, seq)
        stored = next((event for event in runs if event["config_hash"] == digest), None)
        if stored is not None:
            return _answer(stored, registration, repeat=True)
        if len(runs) >= registration["max_configurations"]:
            raise refuse("budget-spent")
        try:
            market = _market_data(registration["data_source"])
        except Refused:
            raise refuse("data-changed") from None
        bars = _in_period(market, registration["in_sample"], registration["universe"])
        if market.digest != registration["data_hash"] or bars is None:
            raise refuse("data-changed")
        _keep_configuration(seq, digest, code, parameters)
        try:
            result = _result(code, parameters, registration, bars, seconds)
        except _NoConfinement as absent:
            raise refuse(absent.reason) from None
        fields = {"registration_seq": seq, "config_hash": digest, "budget_used": len(runs) + 1, **result}
        return _answer(ledger.append("config-run", fields, "runner"), registration, repeat=False)
