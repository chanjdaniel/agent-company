# 07: The outreach procedure and Daniel's daily batch

Phase: 2

Repository: `chanjdaniel/agent-company`, base `dev`.

**What to build:** the daily batch, code that assembles every pending approval sorted by expected margin per Daniel-minute inside the 15-minute budget, and the outreach procedure on top of it: targets only from public professional sources with a reason and a source each, drafts whose every factual claim cites the ledger or a checkable source, a disclosure line that the work is done by AI agents under Daniel's supervision, Daniel sending from their own account, replies and opt-outs recorded, a weekly send cap Daniel sets, and spam flags counted by the honesty loop.

**Blocked by:** 02

- [ ] The batch never exceeds the daily Daniel-minutes budget and is sorted by expected margin per minute; a fixture with more approvals than fit shows the overflow waiting.
- [ ] A target without a public source and a reason is refused; a draft with an uncited claim is refused and logged as an honesty incident candidate.
- [ ] Every draft carries the disclosure line; a test that removes it is refused.
- [ ] No code path sends a message; sending is Daniel's, and the ledger records each send only from Daniel's confirmation in the batch.
- [ ] An opt-out recorded in the ledger blocks any later draft to that contact.
- [ ] The weekly send cap is read from Daniel's settings file and a batch that would cross it holds the rest.
