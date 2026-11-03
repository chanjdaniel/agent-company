# 08: The portfolio rule over real bets

Phase: 2

Repository: `chanjdaniel/agent-company`, base `dev`.

**What to build:** the weekly portfolio step: the Treasurer reads each bet's margin per unit of each resource from the ledger and splits the next week's tokens (the company's share), dollars (when any) and Daniel-minutes by the plain rule in `docs/design.md`: more to the better measured margin, an exploration floor for every open bet, closure after two killed experiments in a row with no positive signal, a fixed trial budget for a new bet, and a holdout share to the rule's second choice.
A cell may write a proposal for another split; it is recorded, and only Daniel's override changes the split, for that week.

**Blocked by:** 04, 06

- [ ] Over a fixture of eight weeks with two bets, the bet with the better measured margin ends with more of each resource, and the other keeps at least the floor until it is closed.
- [ ] A bet with two killed experiments in a row and no positive signal is closed, and the ledger says why.
- [ ] No budget rises: a cell's proposal for more is recorded and has no effect, and the token budget never exceeds the governor's share.
- [ ] A bet whose pending approvals exceed its Daniel-minutes share waits, and the batch shows it waiting.
- [ ] A Daniel override, recorded in the ledger, changes the split for that week only.
