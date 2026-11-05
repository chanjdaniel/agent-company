"""The quant cell's rules: registration, the search budget, and the runner that backtests a strategy outside its session.

The company tools call this, so it runs in their process, outside the session's sandbox, where the agent's shell cannot reach.
A strategy is code a cell wrote, so it runs in its own `bwrap` with no network, no writes and a time limit, and there is no other way to run one.
A backtest gives it the in-sample bars one at a time. Only the Treasurer's verdict gives it the holdout's too, once per registration,
and what comes back of those is a run's figures, never its returns or a word the strategy wrote.
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
from typing import IO

from company import paths, treasurer
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
# A model past this would charge more than all a unit of turnover trades.
_MAX_BPS = 10_000
# A position line past this is rubbish, whether or not it ever ends.
_MAX_LINE_BYTES = 1_000_000
_TOLERANCE = 1e-9
_CHILD_PATH = "/runner/child.py"
_ROOT_DIRECTORIES = ("bin", "sbin", "lib", "lib32", "lib64")
_OK, _FAILED = "ok", "failed"
_TIMED_OUT = "timed-out"
_ENDED = "ended-early"
_BAD_OUTPUT = "bad-output"
_NOT_FINITE = "not-finite"
_LEDGER_ONLY = ("seq", "ts", "kind", "writer", "prev")


class Refused(Exception):
    """Nothing happened, and the caller logs why; `reason` is a code naming no rejected value."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class Logged(Exception):
    """A run of a registration's configuration did not happen, and event `seq`, a `config-refused`, says why."""

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
    data_hash: str


@dataclass(frozen=True)
class _Configuration:
    """One thing a cell may try: its code and parameters, and the hash that is its identity."""

    code: str
    parameters: dict
    identity: str


def _is_number(value) -> bool:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _is_whole(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _days(period: dict) -> tuple[date, date]:
    return date.fromisoformat(period["start"]), date.fromisoformat(period["end"])


def _is_period(value) -> bool:
    if not isinstance(value, dict) or set(value) != {"start", "end"}:
        return False
    try:
        start, end = _days(value)
    except (TypeError, ValueError):
        return False
    return start <= end


def _is_model(value) -> bool:
    if not isinstance(value, dict) or set(value) != {"bps_per_turnover"} or not _is_number(value["bps_per_turnover"]):
        return False
    return 0 <= value["bps_per_turnover"] <= _MAX_BPS


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
    "in_sample": _is_period,
    "holdout": _is_period,
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
    if _days(arguments["holdout"])[0] <= _days(arguments["in_sample"])[1]:
        raise Refused("holdout-not-after-in-sample")
    return {"paper_days": DEFAULT_PAPER_DAYS, **arguments}


def _is_bar(bar) -> bool:
    if not isinstance(bar, dict) or not isinstance(bar.get("symbols"), dict) or not isinstance(bar.get("date"), str):
        return False
    return all(isinstance(fields, dict) and _is_number(fields.get("close")) and fields["close"] > 0 for fields in bar["symbols"].values())


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
        days = [date.fromisoformat(bar["date"]) for bar in bars]
    except (ValueError, KeyError, TypeError, RecursionError):
        raise Refused("data-unavailable:unreadable") from None
    if not bars or not all(_is_bar(bar) for bar in bars) or any(later <= earlier for earlier, later in itertools.pairwise(days)):
        raise Refused("data-unavailable:unreadable")
    return _Market(bars, hashlib.sha256(content).hexdigest())


def _in_period(market: _Market, period: dict, universe: list[str]) -> list[dict] | None:
    """The bars of a period, holding the universe alone; None if a bar lacks a symbol or the period has too few to give a return."""
    start, end = _days(period)
    chosen = [bar for bar in market.bars if start <= date.fromisoformat(bar["date"]) <= end]
    if len(chosen) < _MIN_BARS or any(symbol not in bar["symbols"] for bar in chosen for symbol in universe):
        return None
    return [{**bar, "symbols": {symbol: bar["symbols"][symbol] for symbol in universe}} for bar in chosen]


def _overlap(one: dict, other: dict) -> bool:
    first, second = _days(one), _days(other)
    return first[0] <= second[1] and second[0] <= first[1]


def _registrations(events: list[dict]) -> list[dict]:
    return [event for event in events if event["kind"] == "strategy-registered"]


def _runs_of(events: list[dict], seq: int) -> list[dict]:
    return [event for event in events if event["kind"] == "config-run" and event["registration_seq"] == seq]


def _same_strategy(event: dict, writer: str, strategy: str) -> bool:
    return event["writer"] == writer and event["strategy"] == strategy


def _check_periods_unspent(events: list[dict], fields: dict, writer: str) -> None:
    """Keep each holdout unseen and one registration's: else a new name would reset a budget on it, or read it as in-sample.

    A registration that was replaced ran nothing, so only the newest of each strategy holds its periods, and this one replaces its own.
    """
    standing = {(event["writer"], event["strategy"]): event for event in _registrations(events)}
    for earlier in standing.values():
        if earlier["data_source"] != fields["data_source"] or _same_strategy(earlier, writer, fields["strategy"]):
            continue
        if _overlap(fields["in_sample"], earlier["holdout"]) or _overlap(fields["holdout"], earlier["holdout"]):
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
        return ledger.append("strategy-registered", {**fields, "data_hash": market.data_hash}, writer)


def config_hash(code: str, parameters: dict) -> str:
    """A configuration's identity: the hash of its code and parameters, whichever order they were written in."""
    canonical = json.dumps({"code": code, "parameters": parameters}, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _checked_configuration(code, parameters) -> _Configuration:
    if not isinstance(code, str) or not code or len(code) > MAX_CODE_CHARACTERS or not isinstance(parameters, dict):
        raise Refused("bad-arguments")
    try:
        return _Configuration(code, parameters, config_hash(code, parameters))
    except (ValueError, RecursionError):
        raise Refused("bad-arguments") from None


def _keep_configuration(registration_seq: int, configuration: _Configuration) -> None:
    """Keep what the verdict will run on the holdout, where no session can reach it, before any record cites it."""
    folder = paths.configurations() / str(registration_seq)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(folder / f"{configuration.identity}.json", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as file:
        json.dump({"code": configuration.code, "parameters": configuration.parameters}, file)


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
        # A standalone Python, as uv's and so CI's is, reads this to start at all; a write to it changes no file.
        "--dev-bind", "/dev/urandom", "/dev/urandom",
        "--chdir", "/",
        "--remount-ro", "/",
        python, "-I", "-S", "-B", _CHILD_PATH,
    ]  # fmt: skip


def _read_message(output: IO[bytes]) -> dict | None:
    """The strategy's next line as an object, or None if it ended first; anything else is rubbish."""
    line = output.readline(_MAX_LINE_BYTES)
    if not line:
        return None
    if not line.endswith(b"\n"):
        if len(line) < _MAX_LINE_BYTES:
            return None
        raise _StrategyFailed(f"{_BAD_OUTPUT}: a line too long")
    try:
        message = json.loads(line)
    except (ValueError, RecursionError):
        raise _StrategyFailed(f"{_BAD_OUTPUT}: not JSON") from None
    if not isinstance(message, dict):
        raise _StrategyFailed(f"{_BAD_OUTPUT}: not an object")
    return message


def _send(given: IO[bytes], message: dict) -> None:
    given.write((json.dumps(message) + "\n").encode())
    given.flush()


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
        # NaN and the infinities read as JSON numbers, and fail this too.
        if not isinstance(value, int | float) or isinstance(value, bool) or not abs(value) <= 1:
            raise _StrategyFailed(f"{_BAD_OUTPUT}: a position that is not a weight from -1 to 1")
    if sum(abs(value) for value in positions.values()) > 1 + _TOLERANCE:
        raise _StrategyFailed(f"{_BAD_OUTPUT}: positions past the account's whole value")
    return {symbol: float(value) for symbol, value in positions.items()}


def _play(configuration: _Configuration, bars: list[dict], universe: list[str], seconds: float) -> list[dict[str, float]]:
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
    assert process.stdin is not None and process.stdout is not None
    try:
        return _exchange(process.stdin, process.stdout, configuration, bars, universe)
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
                pipe.close()


def _exchange(given: IO[bytes], output: IO[bytes], configuration: _Configuration, bars: list[dict], universe: list[str]) -> list[dict[str, float]]:
    try:
        ready = _read_message(output)
    except _StrategyFailed:
        ready = None
    if ready != {"ready": True}:
        raise _NoConfinement("confinement-failed")
    _send(given, {"code": configuration.code, "parameters": configuration.parameters})
    positions = []
    for bar in bars:
        _send(given, bar)
        positions.append(_positions(_read_message(output), universe))
    return positions


def _returns(bars: list[dict], positions: list[dict[str, float]], cost_per_turnover: float) -> list[float]:
    """Each bar's position earns the move to the next bar, less the registered costs of the change it took to reach it."""
    returns = []
    held: dict[str, float] = {}
    for bar, following, target in zip(bars, bars[1:], positions, strict=False):
        turnover = sum(abs(target.get(symbol, 0.0) - held.get(symbol, 0.0)) for symbol in bar["symbols"])
        moved = sum(weight * (following["symbols"][symbol]["close"] / bar["symbols"][symbol]["close"] - 1) for symbol, weight in target.items())
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
            # An account that has lost everything stays lost: two losses past the whole must not multiply back to a gain.
            equity *= max(0.0, 1 + value)
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


def _run_once(configuration: _Configuration, registration: dict, bars: list[dict], seconds: float) -> dict:
    """The record of one run, whichever way it went. No position is taken on the last bar, since no return follows it."""
    try:
        positions = _play(configuration, bars[:-1], registration["universe"], seconds)
    except _StrategyFailed as failed:
        return {"status": _FAILED, "failure": str(failed)[:MAX_FAILURE_CHARACTERS]}
    measures = _measures(_returns(bars, positions, _cost_per_turnover(registration)))
    if measures is None:
        return {"status": _FAILED, "failure": _NOT_FINITE}
    return {"status": _OK, **measures}


def _cost_per_turnover(registration: dict) -> float:
    return (registration["cost_model"]["bps_per_turnover"] + registration["slippage_model"]["bps_per_turnover"]) * _BASIS_POINT


def _answer(run: dict, registration: dict, repeat: bool) -> dict:
    """What the cell is told of a run: the record's own numbers, all of them from the in-sample bars."""
    return {
        "event": run["seq"],
        "repeat": repeat,
        "budget": registration["max_configurations"],
        **{name: value for name, value in run.items() if name not in _LEDGER_ONLY},
    }


def _refusal(ledger: Ledger, registration_seq: int, identity: str, reason: str) -> Logged:
    fields = {"registration_seq": registration_seq, "config_hash": identity, "reason": reason}
    return Logged(reason, ledger.append("config-refused", fields, "runner")["seq"])


def run(arguments: dict, writer: str, seconds: float) -> dict:
    """Backtest one configuration on the in-sample bars, or return the stored result of one already run.

    Raise `Refused` if there is no registration to cite, and `Logged` once a `config-refused` has cited it.
    """
    strategy = arguments.get("strategy")
    if not isinstance(strategy, str):
        raise Refused("bad-arguments")
    configuration = _checked_configuration(arguments.get("code"), arguments.get("parameters", {}))
    with _locked():
        ledger = Ledger()
        events = ledger.read()
        own = [event for event in _registrations(events) if _same_strategy(event, writer, strategy)]
        if not own:
            raise Refused("no-registration")
        registration = own[-1]
        seq = registration["seq"]

        def refuse(reason: str) -> Logged:
            return _refusal(ledger, seq, configuration.identity, reason)

        runs = _runs_of(events, seq)
        stored = next((event for event in runs if event["config_hash"] == configuration.identity), None)
        if stored is not None:
            return _answer(stored, registration, repeat=True)
        if len(runs) >= registration["max_configurations"]:
            raise refuse("budget-spent")
        try:
            market = _market_data(registration["data_source"])
        except Refused:
            raise refuse("data-changed") from None
        bars = _in_period(market, registration["in_sample"], registration["universe"])
        if market.data_hash != registration["data_hash"] or bars is None:
            raise refuse("data-changed")
        _keep_configuration(seq, configuration)
        try:
            result = _run_once(configuration, registration, bars, seconds)
        except _NoConfinement as absent:
            raise refuse(absent.reason) from None
        fields = {"registration_seq": seq, "config_hash": configuration.identity, "budget_used": len(runs) + 1, **result}
        return _answer(ledger.append("config-run", fields, "runner"), registration, repeat=False)


def _kept_configuration(registration_seq: int, identity: str) -> _Configuration | None:
    """What the record's hash names, as kept when it ran; None if the file is gone or holds anything else, which then never runs."""
    try:
        kept = json.loads((paths.configurations() / str(registration_seq) / f"{identity}.json").read_text())
        configuration = _checked_configuration(kept["code"], kept["parameters"])
    except (OSError, ValueError, RecursionError, KeyError, TypeError, Refused):
        return None
    return configuration if configuration.identity == identity else None


def _holdout_run(configuration: _Configuration, registration: dict, in_sample: list[dict], holdout: list[dict], seconds: float) -> dict:
    """The holdout's figures for one configuration, or `{failure}`; raise `_NoConfinement` if no sandbox started.

    The strategy is fed the in-sample bars first and the holdout's after them, as one run, so that what it looks back on is there:
    a fresh start would leave a look-back flat through a short holdout, and flat passes a floor of zero. Only the holdout's positions earn.
    It has the time per bar its backtest had. A failure keeps only its kind, since a strategy's own words could quote a holdout bar.
    """
    fed = [*in_sample, *holdout[:-1]]
    limit = seconds * len(fed) / (len(in_sample) - 1)
    try:
        positions = _play(configuration, fed, registration["universe"], limit)
    except _StrategyFailed as failed:
        return {"failure": str(failed).partition(":")[0]}
    measures = _measures(_returns(holdout, positions[len(in_sample) :], _cost_per_turnover(registration)))
    return measures if measures is not None else {"failure": _NOT_FINITE}


def _trials(events: list[dict], registration: dict) -> list[dict]:
    """Every `config-run` of this cell's on these bars: a registration whose in-sample period overlaps this one's is the same search."""
    related = {
        event["seq"]
        for event in _registrations(events)
        if event["writer"] == registration["writer"]
        and event["data_source"] == registration["data_source"]
        and _overlap(event["in_sample"], registration["in_sample"])
    }
    return [event for event in events if event["kind"] == "config-run" and event["registration_seq"] in related]


def verdict(arguments: dict, writer: str, seconds: float) -> dict:
    """The Treasurer's verdict on the one configuration a cell names, once per registration, and what the cell may see of it.

    Raise `Refused` if it may not be asked, with no verdict spent, and `Logged` once a `config-refused` has said why it cannot be given.
    """
    if set(arguments) - {"strategy", "configuration"}:
        raise Refused("unknown-fields")
    strategy, identity = arguments.get("strategy"), arguments.get("configuration")
    if not isinstance(strategy, str) or not isinstance(identity, str):
        raise Refused("bad-arguments")
    with _locked():
        ledger = Ledger()
        events = ledger.read()
        own = [event for event in _registrations(events) if _same_strategy(event, writer, strategy)]
        if not own:
            raise Refused("no-registration")
        registration = own[-1]
        seq = registration["seq"]
        if any(event["kind"] == "verdict" and event["registration_seq"] == seq for event in events):
            raise Refused("verdict-given")
        chosen = next((event for event in _runs_of(events, seq) if event["config_hash"] == identity), None)
        if chosen is None:
            raise Refused("configuration-not-run")
        if chosen["status"] != _OK:
            raise Refused("configuration-failed")
        try:
            market = _market_data(registration["data_source"])
        except Refused:
            raise _refusal(ledger, seq, identity, "data-changed") from None
        in_sample = _in_period(market, registration["in_sample"], registration["universe"])
        holdout = _in_period(market, registration["holdout"], registration["universe"])
        if market.data_hash != registration["data_hash"] or in_sample is None or holdout is None:
            raise _refusal(ledger, seq, identity, "data-changed")
        configuration = _kept_configuration(seq, identity)
        if configuration is None:
            raise _refusal(ledger, seq, identity, "configuration-lost")
        try:
            figures = _holdout_run(configuration, registration, in_sample, holdout, seconds)
        except _NoConfinement as absent:
            raise _refusal(ledger, seq, identity, absent.reason) from None
        event = ledger.append("verdict", treasurer.verdict(registration, chosen, _trials(events, registration), figures), "treasurer")
    return {"event": event["seq"], **{name: value for name, value in event.items() if name not in _LEDGER_ONLY}}
