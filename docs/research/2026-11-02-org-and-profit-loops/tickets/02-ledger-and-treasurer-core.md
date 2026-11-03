# 02: The ledger and the Treasurer core, on fixtures

Phase: 2

Repository: `chanjdaniel/agent-company`, base `dev`.

**What to build:** the append-only ledger with its event contract, and the Treasurer that reads it: token accounting from Claude Code transcripts weighted by the list-price table, the apportioning of the account's weekly usage between the company and the agent team, each bet's subscription-share cost, Daniel-minutes charged per approval and per outreach send from a fixed table, the three bars of the self-sufficiency ladder, and the weekly digest.
Every test runs on fixture transcripts and fixture ledgers; there is no market model and no model call.

**Blocked by:** 01

- [ ] A fixture of transcripts and an account usage reading produce the company's share of the week and each bet's cost as share times the weekly price, and the same fixture gives the same numbers every run.
- [ ] Each event kind is checked against the contract on append, and an event whose writer is not allowed is refused and logged.
- [ ] An approval and an outreach send each charge their Daniel-minutes from the table, and a correction by Daniel replaces the estimate in the ledger.
- [ ] A fixture month with known revenue, refunds, fees, dollars spent and share cost reports the bar reached (0 to 3) and the margin against the next bar.
- [ ] The weekly digest lists the bar, each bet's margin, each resource against its budget, incidents, honesty metrics and pending approvals.
- [ ] No code path takes an API key, calls an external API or enables extra usage; a test greps the repository for API-key configuration and fails on any.
- [ ] The test suite passes with no network access and no model session.
