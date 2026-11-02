# 01: The company's design document

Repository: `chanjdaniel/agent-company`, base `dev`.

**What to build:** `docs/design.md`, which turns `docs/research/2026-11-02-org-and-profit-loops/report.md` (T188's `report.md`, moved there unchanged) and Daniel's decisions in its section 7 into the design the first slice builds.
It names the structure (board, Treasurer and scheduler in code, the weekly strategy session, venture cells, an Auditor on a different Claude model with its gap recorded), the runtime (Claude Code sessions under Daniel's sign-in, no API key, no external API, extra usage off), the ledger's event kinds and fields, the three resources and their budgets, the subscription-share cost model and the self-sufficiency ladder, each of the six loops, the trading and outreach rules, the approval matrix, the token-share governor and the kill switch.
It says which parts are built in phase 2 and which wait for the first revenue bet.

**Blocked by:** None

- [ ] `report.md` lands as `docs/research/2026-11-02-org-and-profit-loops/report.md`, unchanged but for its first lines saying where it came from, and `critique.md` beside it as `docs/research/2026-11-02-org-and-profit-loops/critique.md`.
- [ ] `docs/design.md` records each of Daniel's decisions with the Discord message it came in, and lists the open items of the report's section 7 as open.
- [ ] The runtime section says the company's agents run only as unmodified Claude Code sessions signed in to Daniel's subscription, and that no API key, external API or extra usage is used anywhere.
- [ ] The cost section defines model cost as the company's share of the subscription's weekly limit times the subscription's price, says how the share is apportioned from the usage records, and defines the three bars of the ladder on that cost.
- [ ] Each of the six loops has its metric, decision rule, cadence and guardrail, and names the ground truth its metric is computed from.
- [ ] The ledger section lists every event kind with its fields and which component may write it; no agent may write the Treasurer's money, resource or decision events.
- [ ] The approval matrix, the 25% token share, the agent team's floor, the daily 15-minute batch and the kill switch match the report's section 5.
- [ ] The trading rules (pre-registration fields, trial counting, about three months of paper trading, no capital in view, nothing sold as advice) and the outreach rules (sourcing, cited claims, disclosure, Daniel sends, opt-outs, a weekly cap) match the report's sections 4.4 and 4.5, and the document names the commercial-email law of Daniel's jurisdiction.
- [ ] The language, test command and repository layout are chosen, each with its reason.
- [ ] The document is one sentence per line, uses no em dash, and refers to Daniel as they.
