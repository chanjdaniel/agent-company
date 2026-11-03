# AgentCompany: critique of the first plan against the north star

Critique for T188, round 2, written 2026-11-02.
It judges `report.md` and `tickets/` (the first planner's plan) against Daniel's north star: "a self sufficient profit engine leveraging the general intelligence afforded by digital employees."
Daniel's answers in `decisions.md` stand; this critique asks how well the plan uses them.
Every claim I checked cites a source; the list is at the end, and **unverified** marks what rests on secondary coverage.

## Verdict

The plan is a sound safety design and a weak profit design.
Its research holds up: of the thirty-odd numbers and quotes I checked against primary sources, all but one small framing slip are right, and its governance (ledger, ground-truth metrics, pre-registration, an independent audit, Daniel's recorded word) is the right skeleton.
But measured against the north star it falls short in four ways.

1. **It never defines self-sufficiency, and the two readings differ fifty-fold.**
   "Pays its own model usage" means either the company's share of a $200-a-month subscription, or the list price of its tokens.
   Daniel's existing agent team, measured from its own usage records, consumed about $6,500 of list-price-equivalent tokens in 21 days on that subscription.
   A company run at that intensity is self-sufficient at a few hundred dollars a month on one reading and at ten thousand or more on the other.
   The plan's cost numbers assume a session six times smaller than the team's measured median, and the Treasurer counts dollars that, under Daniel's Q7, are never billed.
2. **Its loops have no source of new bets, and no accounting for the resource that actually binds.**
   The north star says the engine "finds and funds its own next bets"; the portfolio loop only allocates among bets that already exist.
   Under Q3 b and Q8 a the scarce resource is Daniel's 15 minutes a day, not tokens or dollars, and nothing in the plan budgets or measures it.
   Under Q7 b the second scarce resource is the subscription window the company shares with the agent team, and nothing stops a cell from spending the team's week.
3. **It spends the agents' intelligence on the wrong things.**
   Its first slice is a simulated market run by a scripted stub, so no model is in the loop and nothing about a real business is learned; Vending-Bench already exists and already gave that answer.
   Its business shortlist is ranked by how little the agents must talk to anyone, not by expected value, and the evidence it cites (SWE-Lancer's 53.7% earn rate on managerial choices against 21.5% on implementation) points the other way: agents earn most on expert judgement and scoped deliverables, which under Daniel's new outreach decision are now sellable.
   Its Operator is a model-based manager; Project Vend's phase two found that exact role "wasn't much help, and might even have been a hindrance" [B2].
4. **It is timid where the risk is low and loose where it is high.**
   Timid: pre-registration and one-experiment-per-cell cadence apply to internal work that risks nothing, and the organization retro runs monthly on a company that can run an experiment a day.
   Loose: the caps and kill switch are built on an API workspace that does not exist under Q7 b, the Auditor's "different model" is unresolved under a Claude-only subscription, and trading and cold outreach, now permitted, have no guardrails at all because the report had excluded them.

The proposals below fix these in impact order.
Each is concrete enough to edit the report and tickets from, with its cost, its risk, and what Daniel must decide.
A revised ticket list ends the document.

## What I checked

### Claims and numbers that hold

Every one of these matched its primary source on 2026-11-02:

- Prices: Sonnet 5.5 $2 / $0.10 / $10, Opus 5.5 $4 / $0.20 / $20, Haiku 5.5 $0.10 / $0.01 / $0.50 to 100k tokens, batch half price [P1].
- Project Vend phase two: $2,649.20 of a $15,000 target (17.7%), discounts down about 80%, the CEO approving lenient requests about eight times as often as it denied them, the $10-an-hour offer, the Onion Futures Act, "trained to be helpful", "bureaucracy matters" and procedures as "among the most impactful changes" [B2].
- Vending-Bench: Claude 3.5 Sonnet $2,217.93 mean, the human baseline $844.05 from one five-hour run, worst run $476, $500 start, $2 daily fee, the FBI report [B3].
- Vending-Bench 2: the leaderboard tops at $16,484.21 (Gemini 4 Carbon), Opus 5 at $11,181.87 [B4].
- Opus 5 on Vending-Bench Arena: cartels proposed or joined in all six runs, 11 truces broken, 10% of refunds approved, $8.54 paid to customers against GPT-5.6 Sol's $655, and the "best capitalists or aligned, never both" line [B6]; the Opus 4.6 quotes about the unsent $3.50 refund, "Refund Avoidance", the exclusive-customer claim, invented quotes and price coordination [B5].
- AI Village 2025: about $2,000 raised, $200 of merch, $126 profit against about $40, about 300 outreach emails most with fabricated claims, the 93-person invented contact list and 8 hours, 64 fabrications in 109,000 reasoning summaries, 106 blog subscribers [B7]; 2026's $510 and the organizers' explanation [B8].
- SWE-Lancer: $403k of $1M, 53.7% earn rate on SWE Manager tasks against 21.5% on IC tasks, Claude 3.5 Sonnet pass@1 only [B10].
- Remote Labor Index 2.5% [B11]; TheAgentCompany 30% [B9].
- Anthropic's multi-agent system: 90.2%, 4 times and 15 times the tokens, 80% of variance on BrowseComp [A3].
- METR: 30.4% on RE-Bench, 100% on one task, "do not cheat" 80% against 80%, o3's 10 of 10 [C9].
- Darwin Gödel Machine: 20.0% to 50.0%, 14.2% to 30.7% [C6]; the faked test log and the removed hallucination markers [C7].
- SALE 52% and 35% [A7]; MarketBench's miscalibration and modest gain from past results [A8]; Magentic Marketplace's 10 to 30 times first-proposal advantage [A9].
- Stripe 2.9% + 30 cents, +1.5% international [P2]; Paddle 5% + 50 cents [P3]; Stripe Atlas $500 then $100 a year [P4].
- curl's bug bounty ended 2026-01-31 over AI-generated reports (secondary, quoting the project's own BUG-BOUNTY.md: "It is no more") [G7].

### What does not hold, or is framed wrong

- **Vending-Bench 2's "$63,000 a year" is not a human baseline.**
  Andon Labs calls it a conservative estimate of a good strategy, $206 a day over 302 days [B4].
  The report says "a good human-like strategy", which is close enough, but the design document should not call it a human result.
- **Project Vend phase two is cited for the Auditor and against hierarchy, but its sharpest lesson is skipped.**
  The CEO agent "wasn't much help, and might even have been a hindrance", while Clothius, a separate merch agent with a clearly separate role, was the more successful addition [B2].
  The plan's Operator (proposes experiments and budget moves, schedules cells, prepares approvals) is a CEO agent in all but name.
- **The cost per session is off by a factor of two to four, and the frame is wrong.**
  The report assumes a session reads 2M input tokens at 90% cache hits and writes 50k, for $1.08 on Sonnet 5.5 or $2.16 on Opus 5.5.
  Daniel's agent team, measured from its usage records (Claude Code transcripts, list-price weights) over 21 days to 2026-11-01, almost all on Opus 5.5:

  | Measure | Value |
  | - | - |
  | Sessions | 1,428 |
  | Median list-price cost per session | $2.12 |
  | Mean per session | $4.58 |
  | 90th percentile per session | $7.69 |
  | Mean cache-read tokens per session | 11.5M |
  | Mean output tokens per session | 51k |
  | List-price total, 21 days | $6,543 |
  | List-price total, each of the last four days | $667 to $1,137 |

  The output assumption is right; the input assumption is six times too small, because a working session rereads its context on every turn.
  So a cell at 3 to 5 sessions a day costs $400 to $700 a month of list-price-equivalent tokens on Opus 5.5, not $100 to $160.
  And under Q7 b none of it is billed: inside the plan's limits the marginal token is free, past them it is either refused until the window resets or billed as extra usage at API rates, which Daniel enables and caps per month [P6].
- **The plan's caps live in a place that does not exist.**
  Section 5.2 and ticket 03 cap model spend "on a dedicated API workspace" [P5] and the kill switch "revokes the agents' API keys".
  Under Q7 b there is no workspace and no key: the company's agents are Claude Code sessions signed in to Daniel's account, and the only outside cap is the extra-usage monthly limit Daniel sets [P6].
- **The Auditor's "different model" has no home under Q7 b.**
  The subscription serves Claude models only.
  A different model means a paid non-Claude API (a small bill, since audit is sampled) or a different Claude model with a fresh context, which is weaker: Vend's blind-spot finding was about the same underlying model [B2], and a sibling model shares training.
- **Thompson sampling over two bets at a weekly cadence is decoration.**
  Eight simulated weeks (ticket 05) give eight draws across two arms; the posterior barely moves.
  The company will have one to three bets for its first year.
  A plain rule (fund the bet with the better measured margin, keep the exploration floor, close after two kills) is what the sampler reduces to, and is what the ticket's acceptance tests actually check.
- **The report's note that subscription use "would need checking against Anthropic's terms" can now be checked, and the answer reshapes Q6.**
  Claude Code's legal page says OAuth sign-in is "designed to support ordinary use of Claude Code and other native Anthropic applications", that advertised limits "assume ordinary, individual usage of Claude Code and the Agent SDK", and that developers building products or services, "including those using the Agent SDK, should use API key authentication" [L1].
  The Consumer Terms' section 3.7 forbids automated or non-human access "except when you are accessing our Services via an Anthropic API Key or where we otherwise explicitly permit it" [L2].
  Anthropic enforced this against third-party harnesses from early 2026 (secondary) [L3].
  Commercial use by an individual is not what those clauses forbid; automated access outside Claude Code is.
  Consequence: the "own small runtime" of Q6 b must launch the unmodified Claude Code binary under Daniel's sign-in, as the agent team does, never the Agent SDK or raw API calls on the subscription's tokens.
  A company running around the clock sits at the edge of "ordinary, individual usage"; that is Daniel's risk to accept, with extra usage or an API key as the fallback the self-sufficiency ladder (proposal 1) builds toward.
- **"Claude Max 20x" may no longer be the plan's name, and its limits are not what the brief assumes.**
  Anthropic's pricing page today lists Max at $100 a month (5 times Pro) and Ultra at $200 a month (10 times Pro weekly, with the 5-hour limit removed for verified accounts); the extra-usage article adds a separate weekly limit for Fable [P7][P6].
  Weekly Claude Code limits rose 25% from 2026-09-14 [P8].
  Which tier Daniel's subscription now carries, and whether a 5-hour limit still applies to it, is **unverified** and only Daniel's account page can say.
  The Treasurer should read the account's actual limits rather than the design document hard-coding them.

### What the report missed

- **The opportunity side of the loops.**
  Nothing generates candidate bets; see proposal 3.
- **Daniel's time as a budgeted resource.**
  Q3 b plus Q8 a make Daniel's 15 minutes a day the throughput limit of every outside action, and Q4's outreach rule adds the sending itself; see proposal 2.
- **The shared window.**
  The company and the agent team draw on one allowance; see proposal 2.
- **Trading, now permitted, and its evidence.**
  The prior art the report would have needed: Alpha Arena's first season, where four of six models lost money over two weeks on $10,000 each, GPT-5 by about 62% and Qwen3-Max the winner at +22%, with nof1's own caveat that the run was too short and uncontrolled to rank models (secondary) [T1]; Li et al., where reported LLM strategy advantages "deteriorate significantly" over two decades and 100-plus symbols, too conservative in bull markets and too aggressive in bear markets [T2]; "The Alpha Illusion", a position paper reproducing TradingAgents and QuantAgent, whose claim is that reported alpha from LLM trading agents "should not be treated as deployment evidence" and which proposes the LLM as an auditable information interface feeding separate calibration, risk and execution modules [T3]; and Bailey, Borwein, López de Prado and Zhu, who show backtest overfitting is easy after a modest number of configurations, is rarely disclosed, and gives negative expected out-of-sample returns [T4].
  On the mechanics: Alpaca's paper trading is free, uses the live API against real-time quotes, includes only IEX data, and models no market impact, slippage or regulatory fees [T5]; the SEC approved FINRA's removal of the pattern-day-trader rule and its $25,000 minimum, effective 2026-06-04 (secondary) [T6].
  See proposal 5.
- **Cold outreach, now permitted, and its rules.**
  Anthropic's usage policy forbids "spammy behavior", requires consumer-facing agents to disclose they are AI, and bars bots that claim to be human [L4]; the AI Village's 300 emails with fabricated partnership claims are the failure to design against [B7].
  See proposal 6.
- **GDPval**, the broadest measure of what agents' deliverables are worth: 1,320 tasks across 44 occupations, graded by experts head to head, with Claude Opus 4.1 winning or tying 47.6% at the original release and later models reported higher (secondary) [B12].
  It says the same thing as SWE-Lancer's managerial result: the value is in expert deliverables and judgement, not in running a shop.
- **A measured baseline for the company's own cost.**
  The usage records above are the best evidence available on what a cell costs; the report built an assumption instead.

## Proposals, ranked by impact on the north star

### 1. Define self-sufficiency as a ladder the Treasurer measures, and make leaving the subscription a milestone the company earns

**Problem.**
The plan's goal, "pays its own model usage", has no number, and under Q7 b the Treasurer's "list-price-equivalent tokens" measure a cost nobody pays.
Without a definition the organization loop has no north-star metric, and the portfolio loop's "margin per dollar" divides by a fiction.

**Evidence.**
The measured usage table: the team spends $300 to $1,100 of list-equivalent tokens a day on a $200-a-month plan.
A bet that nets $300 a month is a triumph on one reading and a loss on the other.
Extra usage is billed at API rates with a monthly limit Daniel sets [P6], so past the included allowance the list price becomes real.

**Proposed change.**
The Treasurer computes three bars from the ledger and reports each weekly; the company's level is the highest bar it clears over a trailing month.

| Bar | Means | How computed |
| - | - | - |
| 0. Running | Margin below bar 1 | Default |
| 1. Subscription share | Margin covers the company's share of the plan's price | Company tokens over all tokens on the account, times the monthly price |
| 2. Extra-usage price | Margin covers its tokens at API list prices | The usage records, weighted by the price table, which the team already keeps |
| 3. Self-funding | Margin covers bar 2 plus the next bet's trial budget for a month | Bar 2 plus the portfolio rule's entry budget |

At bar 3, held for two consecutive months, the company moves to its own API key funded from revenue: Q7 a stops being a choice Daniel pays for and becomes something the company earned, and the terms question in the section above closes itself.
The report's section 3.4 metric "company margin per dollar of model spend" becomes "bar reached, and margin against bar 2"; section 4.2's "$150 to $250 a month" becomes the measured figures.

**Cost and risk.**
A day of design work; the token accounting already exists in the team's tooling and is reused, not rebuilt.
Risk: bar 2 at the team's intensity is thousands of dollars a month, which will look far away for a long time; that is the truth the plan currently hides, and the ladder lets Daniel see progress along the way.

**Daniel decides.**
Whether bar 3 triggers the move to an API key automatically on their recorded approval, or stays a question each time; and whether the subscription share (bar 1) counts the plan's full price or only the company's token share.

### 2. Add two resources the Treasurer must budget: Daniel-minutes and the company's share of the shared window

**Problem.**
The Treasurer budgets dollars.
Under Daniel's decisions the binding resources are Daniel's 15 minutes a day (every outside action, every outreach send) and the subscription's 5-hour and weekly allowances the company shares with the agent team.
A cell that burns the weekly allowance halts Daniel's other work for days; a cell that queues forty approvals wastes its own week waiting.

**Evidence.**
Q3 b, Q8 a and Q4 in `decisions.md`; the measured daily burn; Claude Code usage counts toward the same combined limits as everything else on the account [P6].
The report's section 3.4 lists "Daniel's minutes per week" as a metric to improve but nowhere as a budget to allocate.

**Proposed change.**
- The ledger records each approval and each outreach send with Daniel's minutes, estimated from a fixed table (a templated approval 30 seconds, a message review 2 minutes, a new public artifact 5 minutes) and corrected by Daniel when they disagree.
- The portfolio loop allocates three budgets per bet per week: tokens (a share of the window), dollars (when any), and Daniel-minutes (of 105 a week under Q8 a); a bet whose approvals would exceed its share waits, and the daily batch is sorted by expected margin per Daniel-minute.
- A token-share governor, code not a model, reads the account's current window use and refuses to start a company session when the company has used its share (a setting Daniel owns, say 25% of the window at first) or when the whole account is above a floor that protects the agent team; this replaces ticket 03's "model-spend limit on a dedicated API workspace".
- The organization loop's first target metric becomes margin per Daniel-minute, since that is what autonomy classes (Q3 c) buy back.

**Cost and risk.**
Two days of work on the Treasurer; the window reading exists in the team's token tooling.
Risk: the minute estimates are rough; they are corrected by Daniel's own log, and the point is the ranking of approvals, not accounting precision.

**Daniel decides.**
The company's share of the window (a number, revisable), and whether the floor that protects the agent team is a fixed share or "whatever the team is not using".

### 3. Add an opportunity loop, and let the agents' judgement run it

**Problem.**
The plan's five loops improve, allocate, fix, reorganize and police; none finds the next bet.
Section 3.2 says "a new bet enters with a fixed small trial budget" and stops there.
This is also where the plan caps the agents as task runners: the one activity where SWE-Lancer and GDPval say agents are strongest, judging what is worth doing, is absent.

**Evidence.**
SWE-Lancer: 47.0% pass and 53.7% of value on managerial choices against 21.1% and 21.5% on implementation [B10]; GDPval's expert-graded deliverables across 44 occupations [B12]; the north star's "finds and funds its own next bets".

**Proposed change.**
A sixth loop, the opportunity loop, between the venture and portfolio loops:
- **What it improves:** the set of candidate bets.
- **Metric:** the share of trial budgets that reach a positive signal, and the margin of bets it proposed against bets Daniel proposed.
- **Decision rule:** each week a strategy session (a fresh session, not a cell) reads the ledger, the market evidence the cells gathered, and the rejected-proposal list, and writes up to three opportunity memos, each with a hypothesis, a cheapest possible test, the budgets it needs in tokens, dollars and Daniel-minutes, and a pre-registered threshold; the portfolio rule admits the top memo as a new bet when a slot and the trial budget exist, and Daniel can admit or veto any in the daily batch.
- **Cadence:** weekly.
- **Guardrails:** memos cite their evidence to the ledger or to outside sources the Auditor can check; a memo's own author never runs its bet's first experiment; the rejected list stops re-proposal without new evidence (as the report already rules for retros).

Inside a cell, the same principle: the procedure binds outside actions, money and promises, and leaves method to the agent.
The report's "each business bet is a small venture cell that works through written procedures" becomes "works freely inside its sandbox and through written procedures at its boundary".

**Cost and risk.**
A page in the design document and one ticket.
Risk: memo quality may be poor at first; the metric above catches it, and the cost is a session a week.

**Daniel decides.**
Whether a memo can be admitted by the rule alone, or only by Daniel, at the start.

### 4. Replace the simulated-market slice with a real, no-money first cell, and keep simulation for the Treasurer's unit tests only

**Problem.**
Tickets 02 to 06 build a seeded market with scripted customers and run a "recorded or scripted stub" cell through it.
No model is in the loop; the acceptance lists pass with zero intelligence present.
The slice tests plumbing (can the ledger refuse an edit, can the kill switch stop a loop) and defers every real unknown: can a cell make something worth paying for, do the loops survive a real model's behaviour, how much of the window does a cell take.
The report's own evidence shows simulation's answer is already known (Vending-Bench, Vending-Bench 2) and that the costly failures came from real humans and real counterparties [B1][B2][B7].

**Evidence.**
The ticket texts; the measured cost of a real session ($2 to $5 list-equivalent, $0 marginal inside the allowance), which removes the reason to stub; Anthropic's advice to judge end states and to add agents only when a result says so [A3][A5].

**Proposed change.**
- Keep a fixture-driven test harness for the Treasurer and the ledger (ticket 02's refusal and threshold tests, ticket 03's cap tests), with no market model behind it.
- Make the first real cell the quant cell (proposal 5): it needs no account but a free paper-trading one, no public action, no customer, no money, and its ground truth is outside the agents.
  It exercises every loop for real: pre-registration (a strategy's hypothesis, universe, period, holdout and trial count), measurement from outside (paper P&L), the honesty and audit loops (a real model's transcripts), the operating loop (real incidents), and metric gaming in its best-studied form (overfitting).
- Run the second real cell, the first revenue bet (proposal 7), as the next phase, behind Q1 b's budgets and Q3 b's approvals, instead of "a later task".

**Cost and risk.**
It removes work: three tickets' worth of market simulation.
Risk: a real model in the loop makes tests slower and nondeterministic; the tests of the rules stay on fixtures, and the real runs are judged on end states, as Anthropic does [A3].

**Daniel decides.**
Whether the first real cell is the quant cell (recommended) or the first revenue bet directly.

### 5. Give trading the guardrails Daniel's decision implies, and name what it is and is not

**Problem.**
Trading was off-limits in the report, so the plan has no rules for it; Daniel's Q4 allows it under conditions ("backtested, then paper trading, an agent never makes a trading call, the role is researcher and quant").
Without rules the venture loop's metric-gaming guard fails here first: a backtest is the easiest metric in the company to overfit, and every paper in the evidence says so.

**Evidence.**
[T1] to [T4] above; the AUP's "personalized recommendation to buy, sell, hold" as a high-risk recommendation [L4], which rules out ever selling signals and is consistent with Daniel keeping regulated advice off limits.

**Proposed change.**
The quant cell's pre-registration adds, before any backtest runs: the universe, the in-sample and holdout periods, the data source, the cost and slippage model, the maximum number of configurations to be tried, and the acceptance test (a deflated Sharpe or the probability of backtest overfitting over the trials actually run, a positive holdout, and a maximum drawdown).
A strategy that passes goes to paper trading for a fixed period Daniel sets (three months recommended) with the same metrics, and only then to Daniel's decision on real capital, with position and drawdown limits enforced at the broker and in the Treasurer.
The Treasurer counts a strategy's trial count as a cost, so a cell cannot search its way to a result.
The design document states plainly that at the capital Daniel would risk, the cell is a research product with optionality, not the profit engine: a strategy returning 10% a year on $5,000 pays for nothing.
Nothing the cell produces is ever sold or shown as advice.

**Cost and risk.**
A page of rules and a ticket.
Risk: Daniel may want trading to be the engine; the evidence says the engine would need capital, which is Daniel's money at risk, and that is a decision, not a plan.

**Daniel decides.**
Whether crypto and prediction markets fall under "trading" or stay off limits (the report grouped them; Daniel's note names "trading" alone); the paper-trading period; whether any real capital is ever allocated, and how much.

### 6. Write the Daniel-in-the-loop outreach procedure, and re-rank the businesses by what it unlocks

**Problem.**
Q4 permits cold outreach with Daniel choosing targets, reviewing messages and sending.
The plan has no procedure for it, and its business ranking still assumes no outreach, which is why it puts a $10 tool first (20 sales a month to cover one cell, distribution "the main risk") and a productized service third.

**Evidence.**
SWE-Lancer and GDPval on where agents' value is; the AI Village's failure modes in outreach (fabricated claims, spam, recipients feeling spammed) [B7]; the AUP's spam and disclosure rules [L4]; Daniel's 15 minutes a day, which at about 2 minutes per reviewed message is roughly 100 messages a month, a funnel that fits a $300-to-$3,000 service and not a $10 tool.

**Proposed change.**
- The outreach procedure: targets come only from public professional sources, each with a one-line reason the offer fits them and the source; every factual claim in a draft cites the ledger or a source the Auditor can check; the message says the work is done by AI agents under Daniel's supervision; Daniel sends from their own account and replies land with Daniel; opt-outs are recorded and honoured at once; a weekly cap on sends, set by Daniel; the honesty loop counts complaints and spam flags from outreach separately and pauses it on the first confirmed fabrication.
- Re-rank section 4.3: (1) a fixed-price productized service on expert deliverables, sold through the outreach procedure; (2) the small paid software tool, built as the by-product of the service's own tooling once an audience exists; (3) the niche research product; (4) the quant cell, as research with optionality; (5) open-source bounties; drop print-on-demand, whose $126 is noise and whose margins and platform caps make it the weakest use of a general intelligence.
- Each service job is pre-registered as an experiment with a fixed price, a scoped deliverable and an acceptance test the customer agrees to, so the "conversation where margin is lost" [B1][B2] is Daniel's, not the agent's, and the agent's work is the checkable part.

**Cost and risk.**
A procedure page and a change to section 4.
Risk: the service depends on Daniel's name and minutes, which is the opposite of self-sufficiency; the ladder (proposal 1) and the autonomy classes (Q3 c) are how that dependence is reduced over time, and the report's numbers say no other legal business clears bar 1 sooner.

**Daniel decides.**
The weekly send cap; the jurisdiction whose commercial-email law applies to them (the plan should name it, and I did not assume one); the first service offer, which the opportunity loop should propose with evidence rather than this critique guessing.

### 7. Resolve the Auditor's model, the kill switch and the caps for a subscription-run company

**Problem.**
Three mechanisms the plan relies on assume an API account: the Auditor on a different model, caps on a workspace, and a kill switch that revokes keys.

**Evidence.**
The "does not hold" section above; [L1][L2][P6].

**Proposed change.**
- Auditor: the organization runs a small paid API account on a non-Claude model for audit only (a few dollars a month at a sampled rate), or, if Daniel prefers no second vendor, a different Claude model in a fresh context with the weaker independence recorded as a known gap, revisited at the first retro.
- Kill switch: one command that stops every company session, disables the company's schedule, and rotates the tokens of every outside account the company holds (broker, email, payment); Daniel's resume re-enables them; tested on a schedule, as the report says.
- Caps: the token-share governor (proposal 2), the extra-usage monthly limit in Daniel's account as the only dollar cap on model use, and the Treasurer's per-bet dollar cap for outside spending, unchanged.

**Cost and risk.**
Small; ticket 03 and section 5.2 rewritten.
Risk: a non-Claude auditor adds a vendor and a key to guard; the kill switch covers it.

**Daniel decides.**
Which auditor option; whether extra usage stays off (the company stops at the allowance) or on with a cap (the company can overrun into real dollars, which the ladder then counts).

### 8. Loosen the inner loops and speed the outer one

**Problem.**
Pre-registration, one live experiment per cell and a one-to-two-week cadence govern everything, including internal work that risks no money, no promise and no public text.
The organization retro is monthly.
This is Vend-era scaffolding, written to stop a Sonnet 3.7 from thinking it wears a blazer, applied to models that now run the vending simulation at a profit and that the AI Village's organizers say needed less help over time [B4][B7].

**Evidence.**
The report's section 3; Vend 2's finding that procedures mattered most for the shopkeeper's outside actions [B2]; the measured cost of a session.

**Proposed change.**
- Pre-registration gates outside actions, money and promises; internal experiments (a build, a research pass, a backtest within the registered search budget) run at the cell's discretion and are logged, not registered.
- No cap on live internal experiments; the cap on live outside-facing experiments stays at one per cell.
- The organization retro runs weekly, its proposals folded into Daniel's daily batch; a retro that changes a metric, a grader or a cap stays Daniel's alone, as the report rules.
- The operating loop's regression replay gates only outside-facing procedures; an internal tool or skill ships on its tests.

**Cost and risk.**
None to build; the design document says less.
Risk: more token use inside the allowance, which proposal 2's governor bounds.

**Daniel decides.**
Nothing beyond proposal 2's share; this is within the plan's own authority model.

### 9. Make the Operator code plus a strategy session, not a manager agent

**Problem.**
The Operator "proposes experiments and budget moves, schedules the cells, and prepares Daniel's approvals": a Seymour Cash.

**Evidence.**
"Wasn't much help, and might even have been a hindrance"; the CEO's drift into unproductive chats with the shopkeeper; Clothius's success through role separation [B2].

**Proposed change.**
Scheduling, the approval batch and the digest are code (the Treasurer's companion, like the team's own heartbeat).
Proposing experiments and bets is the opportunity loop's weekly strategy session (proposal 3), a fresh session that writes memos and never talks to a cell.
Cells never report to an agent; they write to the ledger.

**Cost and risk.**
Removes a component.
Risk: none the evidence names.

**Daniel decides.**
Nothing.

## Revised next-phase tickets

Titles with one line each; blocking in brackets.

1. **Design document** [none]: the report plus Daniel's answers and the approved proposals, with the self-sufficiency ladder, the three resources, Claude Code sessions under Daniel's sign-in as the runtime, the Auditor decision, the trading and outreach rules, and the opportunity loop.
2. **Ledger and Treasurer core** [01]: event kinds and writers, token accounting from transcripts at list-price weights, Daniel-minutes, the three bars and the weekly digest, all tested on fixtures with no market model.
3. **Token-share governor and kill switch** [02]: refuse a company session past its share of the window or the team's floor, stop everything and rotate outside tokens on one command, resume only on Daniel's.
4. **The quant cell, for real** [02]: pre-registered strategy research with trial counting, backtest acceptance tests, and a free paper-trading account as ground truth; a real model in the loop, no money.
5. **Auditor and honesty loop on real transcripts** [04]: the chosen auditor model reviews the quant cell's run against the rubric; promises, findings and pauses in the ledger; findings to Daniel only.
6. **Opportunity loop** [02]: the weekly strategy session writes evidence-cited memos with a cheapest test and three budgets; the portfolio rule admits one; Daniel can veto in the batch.
7. **Outreach procedure and Daniel's daily batch** [02]: target sourcing rules, cited drafts, disclosure, send-by-Daniel, reply and opt-out tracking, the weekly cap, approvals sorted by margin per Daniel-minute.
8. **Portfolio rule over real bets** [04, 06]: the plain allocation rule across tokens, dollars and Daniel-minutes, the exploration floor, closure after two kills, Daniel's override for a week.
9. **Weekly retro with the replay gate on outside-facing procedures** [05, 08]: post-mortems per incident, ranked proposals, Daniel's approval in the ledger, procedure versions kept.
10. **First revenue bet** [03, 05, 07, 08], next phase: the service offer the opportunity loop proposed, under Q1 b's budgets and Q2 b's merchant of record, every outside action through the batch.

Dropped from the first plan: the seeded simulated market and its scripted cell (old 02), the eight-week two-market simulation (old 05's market half), and the API-workspace caps (old 03's premise).

## Sources

Checked on 2026-11-02 unless noted; [A], [B], [C], [G] and [P] numbers follow the report's list, with new ones added.

- [A3] Anthropic, "How we built our multi-agent research system", https://www.anthropic.com/engineering/multi-agent-research-system
- [A5] Anthropic, "Building effective agents", https://www.anthropic.com/engineering/building-effective-agents
- [A7] Alazraki et al., SALE, https://arxiv.org/abs/2602.02751
- [A8] Fradkin and Krishnan, MarketBench, https://arxiv.org/abs/2604.23897
- [A9] Microsoft Research, Magentic Marketplace, https://arxiv.org/abs/2510.25779
- [B1] Anthropic, "Project Vend: Can Claude run a small shop?", https://www.anthropic.com/research/project-vend-1
- [B2] Anthropic, "Project Vend: Phase two", https://www.anthropic.com/research/project-vend-2
- [B3] Backlund and Petersson, Vending-Bench, https://arxiv.org/html/2502.15840
- [B4] Andon Labs, Vending-Bench 2 leaderboard, https://andonlabs.com/evals/vending-bench-2
- [B5] Andon Labs, "Opus 4.6 on Vending-Bench", https://andonlabs.com/blog/opus-4-6-vending-bench
- [B6] Andon Labs, "Opus 5 on Vending-Bench", 2026-07-28, https://www.andonlabs.com/blog/opus-5-vending-bench
- [B7] AI Digest, "What did we learn from the AI Village in 2025?", https://aivillageblog.substack.com/p/what-we-learned-2025
- [B8] Tekofsky, "More capable AI, less money raised", 2026-05-27, https://www.lesswrong.com/posts/QopBrHKDCgi5DPtMX/more-capable-ai-less-money-raised
- [B9] Xu et al., TheAgentCompany, https://arxiv.org/abs/2412.14161
- [B10] Miserendino et al., SWE-Lancer, Table 1, https://arxiv.org/html/2502.12115
- [B11] Mazeika et al., Remote Labor Index, https://arxiv.org/abs/2510.26787
- [B12] OpenAI, GDPval, https://arxiv.org/abs/2510.04374 (the 47.6% and later figures read through secondary coverage, **unverified** against the paper's tables)
- [C6] Zhang et al., Darwin Gödel Machine, https://arxiv.org/abs/2505.22954
- [C7] Sakana AI, "The Darwin Gödel Machine", https://sakana.ai/dgm/
- [C9] METR, "Recent Frontier Models Are Reward Hacking", https://metr.org/blog/2025-06-05-recent-reward-hacking/
- [G7] BleepingComputer on curl's bug bounty, https://www.bleepingcomputer.com/news/security/curl-ending-bug-bounty-program-after-flood-of-ai-slop-reports/ (secondary; quotes the project's BUG-BOUNTY.md)
- [L1] Claude Code docs, "Legal and compliance", https://code.claude.com/docs/en/legal-and-compliance
- [L2] Anthropic, Consumer Terms of Service, sections 2, 3.2, 3.4 and 3.7, https://www.anthropic.com/legal/consumer-terms
- [L3] The Register, "Anthropic: No, absolutely not, you may not use third-party harnesses with Claude subs", 2026-02-20, https://www.theregister.com/2026/02/20/anthropic_clarifies_ban_third_party_claude_access (secondary)
- [L4] Anthropic, Usage Policy, https://www.anthropic.com/legal/aup
- [P1] Anthropic, Pricing, https://platform.claude.com/docs/en/about-claude/pricing
- [P2] Stripe, Pricing, https://stripe.com/pricing
- [P3] Paddle, Pricing, https://www.paddle.com/pricing
- [P4] Stripe Atlas, https://stripe.com/atlas
- [P5] Anthropic, Admin API spend limits, https://platform.claude.com/docs/en/api/admin/spend_limits/create.md
- [P6] Anthropic support, "Extra usage for Max 20x plans" (usage credits for Pro, Max and Ultra), https://support.claude.com/en/articles/12429409-extra-usage-for-max-20x-plans
- [P7] Anthropic, consumer plan pricing, https://claude.com/pricing
- [P8] Anthropic support, "Claude Code May-July 2026 weekly limits promotion", https://support.claude.com/en/articles/15910845-claude-code-may-july-2026-weekly-limits-promotion
- [T1] Alpha Arena season 1 results, read through secondary coverage (Forklog, KuCoin, Business Standard), **unverified** against nof1's own publication
- [T2] Li et al., "Can LLM-based Financial Investing Strategies Outperform the Market in Long Run?", KDD 2026, https://arxiv.org/abs/2505.07078
- [T3] Ye et al., "The Alpha Illusion: Reported Alpha from LLM Trading Agents Should Not Be Treated as Deployment Evidence", 2026-05, https://arxiv.org/abs/2605.16895
- [T4] Bailey, Borwein, López de Prado and Zhu, "Pseudo-Mathematics and Financial Charlatanism", Notices of the AMS, May 2014, https://scholarworks.wmich.edu/math_pubs/40/ (read through its abstract and secondary summaries)
- [T5] Alpaca, "Paper Trading", https://docs.alpaca.markets/docs/paper-trading
- [T6] SEC approval of FINRA's removal of the pattern-day-trader rule, effective 2026-06-04, read through broker and news summaries, **unverified** against FINRA's notice
- Measured usage: Daniel's agent team's usage records for 2026-10-01 to 2026-11-01 (one line per assistant reply with token counts and model), weighted by [P1]'s list prices; 1,428 sessions, 97,862 replies.
