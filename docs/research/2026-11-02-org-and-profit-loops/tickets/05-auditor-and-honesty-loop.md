# 05: The Auditor and the honesty loop on real transcripts

Phase: 2

Repository: `chanjdaniel/agent-company`, base `dev`.

**What to build:** the honesty loop on the quant cell's real runs.
Every promise a cell records (a delivery date, a refund, a paper-trading end date) is a ledger event with its due date, and the Treasurer checks it is kept when due.
An Auditor session, on a different Claude model from the cell's and in a fresh context, reviews the run's ledger and transcripts against a rubric (false statements, broken promises, a result reported that the records do not show, a rule broken) and writes findings for Daniel, never to a cell.
A confirmed finding pauses the cell.

**Blocked by:** 04

- [ ] A promise not kept by its due date is a finding and pauses the cell; a test with a planted overdue promise shows both.
- [ ] The Auditor's model setting must differ from the cell's; starting with the same model is refused, and the design's recorded gap is cited in the refusal text.
- [ ] The Auditor's findings go to Daniel's digest and the ledger; no cell has write access to them.
- [ ] A finding that the cell reported a backtest result its records do not show is produced on a planted transcript.
- [ ] The rule tests use a recorded Auditor; one real Auditor session runs on the quant cell's real transcript inside the governor's share.
