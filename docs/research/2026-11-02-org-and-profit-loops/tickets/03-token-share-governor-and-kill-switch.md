# 03: The token-share governor and the kill switch

Phase: 2

Repository: `chanjdaniel/agent-company`, base `dev`.

**What to build:** the governor, code that reads the account's current window use and refuses to start a company session when the company has used its 25% share of the window or when the whole account is above the agent team's floor, logging each refusal; and the kill switch, one command that stops every company session, disables the company's schedule, and rotates the tokens of every outside account the company holds, undone only by Daniel's resume command.

**Blocked by:** 02

- [ ] With the share used, a launch is refused before any session starts, and the refusal is in the ledger with the share and the reading it was computed from.
- [ ] With the account above the agent team's floor, a launch is refused even when the company's own share has room.
- [ ] The share and the floor are read from a settings file the agents cannot write; a test where a cell edits it is refused.
- [ ] The kill switch stops a running session mid-way, disables the schedule, and runs the rotation step for each outside account listed in the settings, and the ledger says who pulled it and when.
- [ ] After the kill switch, every launch is refused until Daniel's resume command runs; a test covers both.
- [ ] A self-test of the kill switch runs in the test suite, with stub sessions and stub accounts.
