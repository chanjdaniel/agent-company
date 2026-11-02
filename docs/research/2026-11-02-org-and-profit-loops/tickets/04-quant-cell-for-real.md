# 04: The quant cell, for real

Phase: 2

Repository: `chanjdaniel/agent-company`, base `dev`.

**What to build:** the first real venture cell, with a real Claude Code session in the loop and no money.
The cell pre-registers a strategy in the ledger (universe, data source, in-sample and holdout periods, cost and slippage model, the maximum number of configurations, the acceptance test with a deflated Sharpe ratio or the probability of backtest overfitting, a positive holdout and a maximum drawdown), researches and backtests inside that search budget, and sends a strategy that passes to a free paper-trading account, whose P&L the Treasurer reads as the cell's ground truth.
Crypto and prediction markets count as trading under the same rules.

**Blocked by:** 02

- [ ] A backtest cannot run before its registration is in the ledger, and a registration cannot change after the first run; a test covers both.
- [ ] Every configuration tried is counted against the registered search budget, and the run past the budget is refused and logged.
- [ ] The acceptance test is computed by the Treasurer from the backtest's own records, never from the cell's report, and a strategy that fails the holdout or the overfitting test is marked failed.
- [ ] A passing strategy opens a paper-trading period with its end date and drawdown kill in the ledger, and the Treasurer reads the paper account's P&L as the metric.
- [ ] No order path to a live account exists; a test greps for live-trading endpoints or credentials and fails on any.
- [ ] One real session of the cell runs end to end inside the governor's share, and the Auditor's transcript review in ticket 05 can read its transcript.
- [ ] The cell's goal text states the honesty constraints and the trading rules; a test checks no agent's prompt contains "whatever it takes" or "at all costs".
