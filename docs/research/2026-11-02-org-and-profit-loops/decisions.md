# T188 decisions from Daniel

Daniel's answer to the eight decisions in the report's section 7, T188 thread message 1566637877268447294 (2026-11-02).

- Q1 budget: a, then b (recommended).
- Q2 entity and payments: a now, b for the first paid test, c once revenue repeats (recommended).
- Q3 autonomy: b, a class at a time to c after a clean audited run; never d (recommended).
- Q4 off-limits list: option b, except cold outreach and trading, which are permitted under strict conditions (1566639030018510950, after the justification in ask q4).
  - Cold outreach is human-in-the-loop: Daniel checks and approves the people to contact, reviews the messages, and does the sending themselves; agents only research and draft.
  - Trading is algorithmic only: strategies are backtested, then must survive paper trading before any real money; an agent never makes a trading call.
    An LLM call may be part of the algorithm, but the agent's role is researcher and quant, not trader.
  - Still off limits: fake reviews and social proof, AI money-making schemes, content farms and ad arbitrage, regulated advice.
- Q5 public identity: a (recommended).
- Q6 where it runs: b (recommended).
- Q7 which model account pays: b, Daniel's Claude Max 20x subscription, not a dedicated API workspace.
  Daniel: "commercial use is fine since we are not located in the EU."
  So the Treasurer counts model cost as list-price-equivalent tokens, not billed dollars, and the company shares the subscription's 5-hour and weekly limits with the agent team.
- Q8 approval time: a, up to 15 minutes a day in one batch (recommended).

## The critique's seven decisions (Daniel, T188 thread, 2026-11-02, message 1566684625882058958)

Daniel's words: "it will all run under claude code sessions. keep it on the subscription and track cost as proportion of the subscription usage divided by subscription cost. base it on the weekly limit. no external api usage. yes on the trading question. else, recommendations look good."

1. Ladder: the company never moves to its own API key; it runs only as Claude Code sessions on Daniel's subscription.
   Its model cost is its share of the subscription's weekly limit times the subscription's price, and every bar of the ladder counts that cost.
2. Token share: as recommended, a 25% share, with the agent team's floor protected in code.
3. Opportunity loop: as recommended, Daniel's yes for each new bet at first.
4. First cell: as recommended, the quant cell first, the revenue bet right after.
5. Trading: yes, crypto and prediction markets count as trading under Daniel's rule, with the recommended paper period of about three months; no real capital is named yet, so none is in view until Daniel names an amount.
6. Outreach: as recommended (a small daily batch Daniel approves, and the critique's first offer); the jurisdiction's rules follow from Daniel's location, not in the EU.
7. Auditor: no external API, so a Claude model with the gap recorded; extra usage stays off, and no dollar cap through extra usage.

## Prior art from T189 (2026-11-02)

- Cite Google's Harness2 (arXiv:2610.14224; T189's report, section 5) in the design document (ticket 01) as prior art for the operating and organization loops, with that section's caveat: the company's loops have outside ground truth, so Harness2's no-answer-key method is only the fallback for unmeasured work. Daniel agreed in the T189 thread (message 1566768023027720283).
