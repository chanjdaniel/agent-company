# 09: The weekly retro and the replay gate on outside-facing procedures

Phase: 2

Repository: `chanjdaniel/agent-company`, base `dev`.

**What to build:** the operating and organization loops.
Each incident (an Auditor finding, a refused action, a killed experiment, a governor refusal) gets a short post-mortem in the ledger.
A weekly retro session reads the ledger since the last retro and writes ranked proposals, each with its evidence, into Daniel's batch.
An approved change to an outside-facing procedure ships only after a regression replay over a frozen set of past situations, every past incident among them; an internal tool or skill ships on its own tests.

**Blocked by:** 05, 08

- [ ] A run with a planted incident produces a post-mortem and a retro proposal that cites it.
- [ ] A proposal ships only after Daniel's approval is in the ledger; without it the old procedure stays.
- [ ] The replay set and its grader are outside the agents' write access; a test where a cell edits them is refused.
- [ ] A changed outside-facing procedure that fails a past incident in the replay is refused, and the refusal is in the ledger; an internal skill change ships without the replay once its tests pass.
- [ ] A proposal that changes a metric, a grader, a budget, the token share or an approval rule is marked as Daniel's alone and never ships by the operating loop.
- [ ] The retro reports the bar reached and the margin per Daniel-minute, and every procedure version is kept with its reason and the proposal it came from.
