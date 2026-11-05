"""The paper period's tick: the one order path there is, run by code, and never by a company tool.

Each tick reads the account, keeps that reading, and then closes the period if it is past its drawdown kill or its end date.
Otherwise it runs the strategy over every bar since its in-sample period began, as the verdict did, and places what brings the account to the strategy's newest target.
"""

import contextlib
import fcntl
import os
from collections.abc import Callable, Iterator
from datetime import datetime, time, timedelta
from decimal import ROUND_DOWN, Decimal

from company import kill_state, paper, paths, quant, times, treasurer
from company.ledger import Ledger

DRAWDOWN_KILL = "drawdown-kill"
END_DATE = "end-date"
_STRATEGY_FAILED = "strategy-failed"
_BUY, _SELL = "buy", "sell"
# New York's close in winter, and an hour after it in summer: a day's bar is not whole before this.
_DAY_WHOLE_AT = time(21, 0)

Say = Callable[[str], None]


class TickRefused(Exception):
    """This tick stopped here, for a reason that is no fault of the strategy's; what it wrote stands."""


@contextlib.contextmanager
def _one_tick() -> Iterator[None]:
    """Two ticks at once would each see the other's orders unfilled, and place them again."""
    paths.home().mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(paths.home() / "paper.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise TickRefused("another paper tick is running") from None
        yield
    finally:
        os.close(fd)


def _place(ledger: Ledger, account: paper.Account, period: dict, symbol: str, side: str, quantity: Decimal, say: Say) -> None:
    """The one place an order is sent from, and each looks once more for the kill switch."""
    if kill_state.present():
        raise TickRefused("the kill switch was pulled during this tick")
    placed = account.place_order(symbol, side, quantity)
    fields = {"period_seq": period["seq"], "symbol": symbol, "side": side, "quantity": format(quantity, "f"), "broker_order_id": placed.broker_order_id, "status": placed.status}
    ledger.append("paper-order", fields, "runner")
    say(f"PAPER order, no real money: {side} {format(quantity, 'f')} {symbol}, {placed.status}.")


def _close(ledger: Ledger, account: paper.Account, period: dict, reason: str, equity: Decimal, say: Say) -> None:
    """Every position goes first, so a failed order leaves the period open for the next tick to try again."""
    account.cancel_orders()
    for position in account.positions():
        side = _SELL if position.quantity > 0 else _BUY
        _place(ledger, account, period, position.symbol, side, abs(position.quantity), say)
    ledger.append("paper-closed", {"period_seq": period["seq"], "reason": reason, "equity": format(equity, "f")}, "runner")
    say(f"PAPER period {period['seq']} closed, no real money: {reason}.")
    opened = quant.open_waiting_period()
    if opened is not None:
        say(f"PAPER period {opened['seq']} opened, no real money: it ends on {opened['end_date']}.")


def _target_quantity(weight: float, equity: Decimal, close: float) -> Decimal:
    """Whole shares towards zero, since a short position cannot be a fraction, and a weight of the whole account must not overdraw it."""
    return (Decimal(str(weight)) * equity / Decimal(str(close))).to_integral_value(rounding=ROUND_DOWN)


def _order_for(held: Decimal, target: Decimal) -> tuple[str, Decimal] | None:
    """What moves `held` towards `target`; a position crossing zero only closes here, as the broker may refuse more against shares not yet sold."""
    if (held > 0 and target < 0) or (held < 0 and target > 0):
        target = Decimal(0)
    change = target - held
    if change == 0:
        return None
    return (_BUY if change > 0 else _SELL), abs(change)


def _rebalance(ledger: Ledger, account: paper.Account, period: dict, targets: dict[str, float], equity: Decimal, newest: dict, say: Say) -> None:
    """Replace whatever the last tick left waiting with what brings the account to `targets`, selling first to free the cash."""
    account.cancel_orders()
    held = {position.symbol: position.quantity for position in account.positions()}
    closes = {symbol: fields["close"] for symbol, fields in newest["symbols"].items()}
    wanted = {symbol: _target_quantity(weight, equity, closes[symbol]) for symbol, weight in targets.items()}
    orders = []
    for symbol in sorted(set(held) | set(wanted)):
        order = _order_for(held.get(symbol, Decimal(0)), wanted.get(symbol, Decimal(0)))
        if order is not None:
            orders.append((symbol, *order))
    if not orders:
        say("PAPER, no real money: the account already holds the strategy's target, so no order was placed.")
    for symbol, side, quantity in sorted(orders, key=lambda order: order[1] == _BUY):
        _place(ledger, account, period, symbol, side, quantity, say)


def _bars_for(registration: dict, market: paper.MarketData, now: datetime) -> list[dict]:
    """Only whole days that hold every symbol, as a backtest's do: a strategy was never tried on anything else."""
    universe = registration["universe"]
    last = now.date() if now.time() >= _DAY_WHOLE_AT else now.date() - timedelta(days=1)
    bars = market.bars(universe, registration["in_sample"]["start"], last.isoformat())
    return [bar for bar in bars if all(symbol in bar["symbols"] for symbol in universe)]


def tick(account: paper.Account, market: paper.MarketData, seconds: float, say: Say) -> None:
    """One tick of the open period, if there is one; raises `TickRefused`, `paper.PaperFailed` or a ledger's refusal, and what was written stands."""
    with _one_tick():
        ledger = Ledger()
        refusal = kill_state.refusal(ledger.read())
        if refusal:
            raise TickRefused(f"{refusal}, so `{kill_state.RESUME}` comes first")
        period = treasurer.open_period(ledger.read()) or quant.open_waiting_period()
        if period is None:
            say("PAPER, no real money: no paper period is open, so this tick did nothing.")
            return
        state = account.read()
        if state.status != paper.ACTIVE:
            raise TickRefused(f"the paper account's status is {state.status}, so this tick placed nothing")
        _run(ledger, account, market, period, state.equity, seconds, say)


def _run(ledger: Ledger, account: paper.Account, market: paper.MarketData, period: dict, equity: Decimal, seconds: float, say: Say) -> None:
    now = times.now()
    events = ledger.read()
    registration = treasurer.registration_of(events, period)
    pnl = treasurer.paper_pnl(events, period["seq"], equity)
    fields = {"period_seq": period["seq"], "equity": format(equity, "f"), "pnl": format(pnl, "f"), "taken_at": times.stamp(now)}
    ledger.append("paper-reading", fields, "runner")
    drawdown = treasurer.paper_drawdown(events, period["seq"], equity)
    say(f"PAPER results, no real money: period {period['seq']}, equity {paper.money(equity)}, profit and loss {paper.money(pnl)}, drawdown {float(drawdown) * 100:.2f}%.")
    # An account with nothing left has nothing to size a position on, whatever its registered kill.
    if equity <= 0 or treasurer.past_drawdown_kill(drawdown, period):
        _close(ledger, account, period, DRAWDOWN_KILL, equity, say)
        return
    if now.date().isoformat() >= period["end_date"]:
        _close(ledger, account, period, END_DATE, equity, say)
        return
    bars = _bars_for(registration, market, now)
    if not bars:
        raise TickRefused("the broker has no day holding every symbol of this strategy, so this tick placed nothing")
    try:
        targets = quant.paper_targets(registration, treasurer.config_hash_of(events, period), bars, seconds)
    except quant.StrategyFailed as failed:
        _close(ledger, account, period, f"{_STRATEGY_FAILED}:{failed.kind}", equity, say)
        return
    except quant.NoConfinement as absent:
        raise TickRefused(f"the strategy's sandbox did not start ({absent.reason}), so this tick placed nothing") from None
    say(f"PAPER, no real money: the strategy's target comes from the close of {bars[-1]['date']}.")
    _rebalance(ledger, account, period, targets, equity, bars[-1], say)
