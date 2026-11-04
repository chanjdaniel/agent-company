# AgentCompany: design

This is the design the first slice builds, written 2026-11-04.
It turns the research in [`docs/research/2026-11-02-org-and-profit-loops/`](research/2026-11-02-org-and-profit-loops/report.md) and Daniel's decisions into one document that later work is checked against.
Where this document and the report or critique differ, this document holds; where this document and Daniel's word differ, Daniel's word holds, and this document is wrong.
So far the code holds the `company` command, the ledger and its contract, the account reading, the Treasurer's share, minutes, ladder and weekly digest, the test suite with its guards and scan, and CI; nothing else here exists as code yet.

Words used throughout:

- **Daniel** is the board, and is "they" in every document.
- **A real session** is a Claude Code session on Daniel's subscription, as opposed to the stub `claude` the test suite uses.
- **A bet** is one line of business the company is trying, run by one **cell**.
- **Ticket numbers** are those of task T215, listed under "Phases"; the research's `tickets/` folder holds the earlier drafts, under other numbers.

## Daniel's decisions

Each decision is recorded with the Discord message it came in.
A later message overrides an earlier one where they differ: Q7's "list-price-equivalent tokens" was replaced by the subscription share in 1566684625882058958.

| Decision | What Daniel decided | Message |
| - | - | - |
| Q1 budget | No cash and the token share only until the first slice works; then a first real experiment with up to $100 in cash | 1566637877268447294 |
| Q2 entity and payments | None now; a merchant of record for the first paid test; an entity once revenue repeats | 1566637877268447294 |
| Q3 autonomy | Act inside, approve outside; one class at a time to pre-approved after a clean audited run; never full autonomy | 1566637877268447294 |
| Q4 off limits | Fake reviews and social proof, AI money-making schemes, content farms and ad arbitrage, and regulated advice stay off limits | 1566639030018510950 |
| Q4 cold outreach | Permitted with Daniel in the loop: they approve the people, review the messages and do the sending, and agents only research and draft | 1566639030018510950 |
| Q4 trading | Algorithmic only: backtested, then surviving paper trading before any real money; an agent is a researcher and quant and never makes a trading call | 1566639030018510950 |
| Q5 public identity | A brand that says plainly it is run by AI agents, with Daniel named as the responsible human contact | 1566637877268447294 |
| Q6 where it runs | Its own small runtime in this repository, built by agent-team tasks, running agents only as Claude Code sessions under Daniel's sign-in | 1566637877268447294 |
| Q7 which account pays | Daniel's Claude subscription, not a dedicated API workspace; commercial use is accepted by Daniel, and so is the terms' "ordinary, individual usage" wording as a risk they carry | 1566637877268447294 |
| Q8 approval time | Up to 15 minutes a day, in one batch | 1566637877268447294 |
| Critique 1, ladder | The company never moves to its own API key; model cost is its share of the subscription's weekly limit times the subscription's price, and every bar counts that cost | 1566684625882058958 |
| Critique 2, token share | A 25% share, with the agent team's floor protected in code | 1566684625882058958 |
| Critique 3, opportunity loop | Daniel's yes for each new bet at first | 1566684625882058958 |
| Critique 4, first cell | The quant cell first, the revenue bet right after | 1566684625882058958 |
| Critique 5, trading | Crypto and prediction markets count as trading under the same rule, with about three months of paper trading; no real capital is in view until Daniel names an amount | 1566684625882058958 |
| Critique 6, outreach | A small daily batch Daniel approves, and the critique's first offer; the rules follow from Daniel's location, not in the EU | 1566684625882058958 |
| Critique 7, Auditor | No external API, so a Claude model with the gap recorded; extra usage stays off, with no dollar cap through it | 1566684625882058958 |
| Prior art | Cite Google's Harness2 as prior art for the operating and organization loops, with the caveat recorded under "Prior art: Harness2" | 1566768023027720283 |
| Start of this phase | "start the next phase", which opened this design and the first slice | 1567537331425251421 |
| S1, commercial-email law | Canada's CASL as a planning default | T215 thread 1567544480939384953 |
| Who checks an outside citation | Code checks the URL is present, the batch shows it, and Daniel checks it; the Auditor has no web read, which would put outside text into the session that audits the cells | T215 thread 1567567398054264934 |

### Open items

These are Daniel's to settle when they arise, and no default in this document or in code stands in for their decision.

| Open item | State |
| - | - |
| The first service offer | Open; the opportunity loop proposes it with evidence, after this slice |
| The weekly outreach send cap | Open; with no cap set, the batch holds every send |
| The commercial-email law of Daniel's jurisdiction | Open; CASL is the planning default, and Daniel can change it before the first revenue bet |
| The agent team's floor in the governor | Open; 60% is recommended, and with no value set every launch is refused |
| Any later change to the 25% share | Open; only Daniel's settings command changes it |
| Any real trading capital, and its amount | Open; none is in view, and this document carries no figure |
| The complaint threshold that pauses the company | Open to Daniel's change; the value under "Numbers set here" stands until they do |

Which subscription tier Daniel holds, and its price, are not recorded here: `monthly_price` and `plan_name` are Daniel's settings (S4).

## Structure

The company is a governed portfolio, starting each cell as one agent and adding roles only when a measured result justifies them.

- **Board:** Daniel sets the goal, the constraints, the budgets and the autonomy level, and approves what the approval matrix names, in one daily batch.
- **Treasurer (code, not a model):** it keeps the ledger, computes each bet's money and resource use from ground truth, enforces the budgets and gives every verdict.
- **Scheduler (code, not a model):** it starts sessions inside their budgets, assembles the daily batch and the weekly digest, and decides nothing.
- **Strategy session:** a fresh session each week that reads the ledger and writes opportunity memos, and never talks to a cell.
- **Venture cells:** each bet is one lead agent, free in its method inside its sandbox and bound by a short written procedure at its boundary (money, outside actions, promises).
- **Auditor:** an agent on a different Claude model from the cells', in a fresh context, which reports to Daniel only, with its gap recorded under "The Auditor's recorded gap".

Budget moves between bets by a plain rule over the Treasurer's numbers.
A cell may argue in writing, but the rule decides, and only Daniel can override it.
Cells report to nobody: they write to the ledger, and code reads it.

The first cell is the quant cell, chosen because its ground truth sits outside the agents, it has no customer, and it costs no money; at any capital in view it is research with optionality, never the profit engine.

## Runtime

### What runs

The company's agents run only as unmodified Claude Code sessions signed in to Daniel's subscription.
No model API key, no model API and no extra usage are used anywhere, on any code path.
With extra usage off, the company has no dollar path to a model, so it stops at the subscription's limits and never overruns into a bill.

Daniel's words "no external API" came in answer to which model account pays, so the rule is sharpened as follows.
Code uses no model vendor's key, endpoint or SDK, and reaches no outside host at all, with one named exception.

**The one exception is the paper broker's two hosts,** `paper-api.alpaca.markets` for the paper account and `data.alpaca.markets` for market data, reached only from the paper module.
They are not a model API: they serve a free paper-trading account and its market data, and no model runs behind them.
The paper account is the quant cell's outside ground truth, so it is the reason the exception exists, and no other host joins it without Daniel's word.
The broker's live host is named nowhere but in the scan's list of banned hosts.

A session's own web read is Claude Code's tool, granted by role, and is separate from this rule about the company's code.
Outside text it brings back is data, never instructions, as each goal text states.

The `claude -p` print mode is the command line's form of what Claude Code's docs call the Agent SDK.
The company runs that unmodified command, and never imports an Agent SDK package or calls a model by any other route.

### Dependencies to re-check

Each of these can move, and Daniel re-checks them before each go (S5).

- **`claude -p` on plan limits.**
  Anthropic's help article "Use the Claude Agent SDK with your Claude plan" ([article 15036540](https://support.claude.com/articles/15036540), read 2026-11-04) says in its notice of 2026-10-07 that "when you're signed in with your Claude plan, the Claude Agent SDK and `claude -p` still draw from your subscription limits".
  Its notice of 2026-06-15 says "For now, nothing has changed: Claude Agent SDK, `claude -p`, and third-party app usage still draw from your subscription limits."
  Anthropic has moved on this before, and secondary sources from before the pause still describe a separate credit.
  If it moves, the share stops describing what sessions spend; since extra usage is off, sessions stop rather than bill, and the launcher is the one module that changes.
- **`--bare` becoming the default.**
  Claude Code's [headless docs](https://code.claude.com/docs/en/headless) (read 2026-11-04) say `--bare` "will become the default for `-p` in a future release", and that bare mode "doesn't use your subscription login".
  With no key in the environment, such a release would make every company session fail at sign-in, which stops the company and costs nothing, and the launcher would then need whatever flag keeps the sign-in.
- **The terms.**
  Claude Code's [legal page](https://code.claude.com/docs/en/legal-and-compliance) (read 2026-11-04) says subscription sign-in "is designed to support ordinary use of Claude Code and other native Anthropic applications", and that advertised limits "assume ordinary, individual usage of Claude Code and the Agent SDK".
  The same page says developers building products or services, "including those using the Agent SDK, should use API key authentication", and that this does not "prevent an end user from signing in to the unmodified Claude Code binary with their own Claude subscription".
  The [Consumer Terms](https://www.anthropic.com/legal/consumer-terms) (effective 2025-10-08, read 2026-11-04), section 3, item 7, restrict access "through automated or non-human means, whether through a bot, script, or otherwise", "Except when you are accessing our Services via an Anthropic API Key or where we otherwise explicitly permit it".
  A company of scheduled agents sits at the edge of that wording, and the `claude -p` it runs is what these docs call the Agent SDK.
  Daniel has accepted the "ordinary, individual usage" wording as their risk (Q7).
  This document draws no legal conclusion from the other sentences, and records them so that S5's re-check sees them.

### The launcher and its session rules

The launcher is the only code that starts `claude`, and it calls the governor first, so a refused launch starts nothing.
It takes the binary from `COMPANY_CLAUDE_BIN` or `PATH`, so tests use the stub.

It starts `claude -p` in its own process group, rather than `claude --bg`, so it holds the process, needs no session-management command, sets the session id itself and captures the output.
The flags are `--session-id`, `--output-format stream-json --verbose`, `--strict-mcp-config --mcp-config`, `--settings`, `--setting-sources` and `--model`, with a non-prompting permission mode (the docs' `dontAsk` denies whatever would otherwise prompt) and an explicit tool list.
Ticket 06 checks each flag against `claude --help`, and the probe proves them on a real session.

Rules every session starts under:

- **Never `--bare`,** since it authenticates only by API key.
- **An allow-listed environment.**
  The child keeps only named variables, so a new one is excluded by default, and that list excludes `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`, `CLAUDE_CODE_USE_BEDROCK`, `CLAUDE_CODE_USE_VERTEX`, `CLAUDE_CODE_USE_FOUNDRY` and anything else the scan's list names.
- **Generated settings.**
  They set `sandbox.enabled`, `sandbox.failIfUnavailable` and `sandbox.allowUnsandboxedCommands: false`, a read boundary (`sandbox.filesystem.denyRead` of the home directory, with the workspace allowed), no network hosts, and permission rules denying `Read`, `Write` and `Edit` outside the workspace.
  They set no `apiKeyHelper`, no hook and no status line, and the session loads no user-level settings, instructions, skills, subagents, plugins, auto memory or MCP servers.
- **Both layers are needed.**
  The [sandbox docs](https://code.claude.com/docs/en/sandboxing) (read 2026-11-04) say "The sandbox covers shell commands only", and that tools such as `Read`, `Edit`, `Write`, `WebFetch` and `WebSearch` "follow permission rules instead".
  They also say local MCP servers run with full access, which is why the company tools can write the ledger when the agent's shell cannot.
  On Linux the sandbox needs `bubblewrap` and `socat`, and `failIfUnavailable` makes a session exit at start without them.
- **A workspace supplies no configuration.**
  The [permission docs](https://code.claude.com/docs/en/permissions) (read 2026-11-04) say a `claude -p` run uses hooks, the `env` block and helper commands from a folder's settings, and connects the servers in its `.mcp.json`, with no trust prompt.
  Hooks and local MCP servers run outside the sandbox, so a file an agent wrote there could escape it in a later session.
- **A session's context is only what the launcher gives it.**
  The [headless docs](https://code.claude.com/docs/en/headless) (read 2026-11-04) say `--bare` skips "hooks, skills, custom commands, subagents, installed plugins, MCP servers, auto memory, and CLAUDE.md", and that without it `claude -p` "discovers and loads them as an interactive session would, including anything configured in the working directory or `~/.claude`".
  So an instruction file an agent wrote in its workspace could carry instructions into a later session, and Daniel's `~/.claude/CLAUDE.md`, skills, subagents and auto memory would sit beside a cell's goal text and in the Auditor's fresh context.
  None of these enters a session, from the workspace, a folder above it or `~/.claude`.
- **How the launcher holds these two rules.**
  It keeps `--strict-mcp-config`, denies writes to `.claude/`, `.mcp.json`, `CLAUDE.md` and `CLAUDE.local.md` at any depth in the workspace, and refuses to start a session in a workspace that holds any of them, logging `launch-refused`.
  It loads no user, project or local settings, and turns off the rest, in the form ticket 06 finds.
  That form is not settled: the docs list only those three sources for `--setting-sources`, do not say it gates instruction files, skills, subagents or auto memory, and advise `--setting-sources user`, which would load what this rule keeps out.
  The candidates ticket 06 checks, from the [CLI reference](https://code.claude.com/docs/en/cli-reference) and the [environment variables page](https://code.claude.com/docs/en/env-vars) (read 2026-11-04), are `--restricted`, which "loads only managed settings and `--settings`"; `--safe-mode`, under which MCP servers do not load, and the company tools are MCP servers; `--disable-slash-commands`; `CLAUDE_CODE_DISABLE_CLAUDE_MDS`; and `CLAUDE_CODE_DISABLE_AUTO_MEMORY`.
  **If no documented form does this with the sign-in still working, the launcher refuses every real launch and the builder asks; it never falls back to user settings.**
  Ticket 06 proves the refusals on the stub, and only Daniel's probe, read in ticket 14, can prove what a real session loads.
- **Limits.**
  `session_max_minutes` and `session_max_weight` are enforced from the live output, and a session past either has its group stopped and `session-stopped` logged.
- **At the end,** the launcher logs `session-ended` with the exit, the transcript's path and hash and the session's weight, and copies the transcript into the company home, so that it outlives Claude Code's own clean-up and the audit window can rely on it.

### Roles

| Role | Model | Context in the workspace | Tools |
| - | - | - | - |
| `probe` | The cheapest model | A fixed guardrail script | File tools, shell, one note tool |
| `cell` | `cell_model` | Its goal text and its own bet's filtered ledger, with no findings | File tools, shell, web read, its company tools |
| `strategy` | `cell_model` | Goal text, whole ledger with findings and session notes removed, rejected list | File tools, web read, memo tool |
| `auditor` | `auditor_model`, which must differ from the audited cell's | Rubric, whole ledger, audited transcripts | Read-only file tools, finding tool, and no web read |
| `retro` | `cell_model` | Ledger since the last retro, with findings | Read-only file tools, post-mortem and proposal tools |

The defaults are `claude-opus-5-5` for `cell_model`, `claude-sonnet-5-5` for `auditor_model`, and `claude-haiku-5-5` for the probe.

Every goal text states the honesty constraints as part of the goal, and none says "whatever it takes" or "at all costs".
The evidence behind this is in the report's section 1.3: under such a prompt, agents lied about refunds and fixed prices.

### Company tools

Agents reach the ledger only through company tools on a local stdio MCP server, one per session.
The launcher starts it with the role and bet fixed, so the writer is settled when the session starts, which a flag or an environment variable inside a session could not do.
A tool call that names another writer still writes as the session's own, and a call to a tool outside the role is refused and logged.
A session's shell cannot write the company home outside its workspace, so it cannot run `company` as anyone else.

## The ledger

One JSON Lines file in the company home, append-only.
Each line holds `seq`, `ts`, `kind`, `writer`, the kind's fields, and `prev`, the hash of the line before.

- A data file in the package is the contract: each kind's required and optional fields and allowed writers.
- An append that fails the contract or names a disallowed writer raises, and logs `append-refused` with the attempted kind and writer, never the rejected values.
- `verify()` runs at each `company` command that decides anything.
  A broken chain refuses every launch and is reported to Daniel.
- Other refusals with no kind of their own (a second verdict, a repeated proposal with no new evidence) also log `append-refused`, with a short reason code.
- A chain alone cannot see lines removed from its end, so a head record beside the ledger holds the last line's `seq` and hash.
  It may lag by one line after a crash between the two writes; any other difference is a broken ledger, and an append to a ledger whose end is broken is refused with nothing written.
- The chain and the head record find an edit by hand, with limits that the session rules cover by keeping agents from writing the company home.
  Someone rewriting the whole ledger and the head record together would pass.
  So would one line added at the end with a good `seq` and `prev`, or an edit of the last line while the head lags, since each reads as a crash's lag, and the next append heals it.

### Writers

- **Board:** `board`, Daniel's own commands.
- **Code:** `treasurer`, `governor`, `launcher`, `scheduler`, `killswitch`, `runner`.
- **Agents:** `cell:<bet>`, `strategy`, `auditor`, `retro`, `probe`.

**No agent may write the Treasurer's money, resource or decision events.**
Agents may write only their own proposals and reports:

- `cell:<bet>`: `strategy-registered`, `experiment-registered`, `promise-recorded`, `target-proposed`, `draft-proposed`, `split-proposed`, `session-note`.
- `strategy`: `memo-written`.
- `auditor`: `finding`.
- `retro`: `postmortem`, `retro-proposal`.
- `probe`: `session-note`.

An `append-refused` event's writer is the code writer making the append, or `treasurer` when the attempt came from an agent or a person, since the Treasurer keeps the ledger.

### Field conventions

- A field ending in `_seq` holds the `seq` of an earlier event, and `_seqs` a list of them.
- A field ending in `_at` is a UTC timestamp like `2026-11-05T09:30:00Z`, and one ending in `_date` is a date like `2026-11-05`.
- `bet` is a bet's id (lower-case letters, digits and hyphens), and `session` a session's UUID.
- `message` is the Discord id of Daniel's word, as a string of digits.
- `amount` is a decimal string from zero up, always with `currency`, and `cost` is a decimal string from zero up in US dollars, so a refund is a positive `amount` of kind `refund`.
- `minutes` is a number from zero up.
- `week_start` is the UTC time a seven-day window opens.
- `weight` is a list-price weight, which is an apportioning key and never a cost.
- On events written through company tools, `session` and `data_hash` are filled in by the tool, not by the agent.

The contract holds the conventions on a field's form too, and an append whose field breaks one is refused.

### Event kinds

A kind that a later ticket finds it needs joins this table and the contract in the same PR.

| Kind | Group | Writers | Required fields | Optional fields |
| - | - | - | - | - |
| `settings-changed` | Governance | `board` | `digest`, `keys` | `message` |
| `settings-tamper` | Governance | `governor` | `expected_digest`, `found_digest` | |
| `go-given` | Governance | `board` | `scope`, `message`, `sessions` | |
| `schedule-enabled` | Governance | `board` | `message`, `jobs` | |
| `schedule-disabled` | Governance | `board`, `killswitch` | `reason` | |
| `append-refused` | Governance | `treasurer`, `governor`, `launcher`, `scheduler`, `killswitch`, `runner` | `attempted_kind`, `attempted_writer`, `reason` | `session`, `tool` |
| `usage-reading` | Resources | `board`, `governor` | `window`, `used_percent`, `resets_at`, `taken_at`, `source` | |
| `resource-charged` | Resources | `treasurer` | `week_start`, `line`, `weight`, `fraction`, `company_used`, `cost`, `reading_seq`, `charge_id`, `charge_lines` | |
| `minutes-charged` | Resources | `treasurer` | `action`, `minutes`, `subject_seq` | `bet` |
| `minutes-corrected` | Resources | `board` | `charge_seq`, `minutes` | `reason` |
| `revenue` | Money | `treasurer` | `amount`, `currency`, `source`, `record` | `bet` |
| `refund` | Money | `treasurer` | `amount`, `currency`, `source`, `record` | `bet` |
| `fee` | Money | `treasurer` | `amount`, `currency`, `source`, `record` | `bet` |
| `spend` | Money | `treasurer` | `amount`, `currency`, `source`, `record` | `bet` |
| `session-started` | Sessions | `launcher` | `session`, `role`, `model`, `run`, `gate`, `account_used`, `company_used`, `reading_seq` | `bet` |
| `session-ended` | Sessions | `launcher` | `session`, `exit`, `transcript_path`, `transcript_hash`, `weight` | |
| `session-stopped` | Sessions | `launcher` | `session`, `reason` | `elapsed_minutes`, `weight` |
| `session-note` | Sessions | `cell:<bet>`, `probe` | `session`, `text` | |
| `launch-refused` | Sessions | `governor`, `launcher` | `role`, `check`, `reason`, `fix` | `bet`, `account_used`, `company_used`, `reading_seq` |
| `kill-pulled` | Kill switch | `killswitch` | `by`, `reason` | `loop` |
| `kill-step` | Kill switch | `killswitch` | `step`, `target`, `result` | `detail` |
| `resumed` | Kill switch | `board` | `kill_seq` | `message` |
| `strategy-registered` | Quant | `cell:<bet>` | `strategy`, `universe`, `data_source`, `data_hash`, `in_sample`, `holdout`, `cost_model`, `slippage_model`, `max_configurations`, `acceptance` | `paper_days` |
| `config-run` | Quant | `runner` | `registration_seq`, `config_hash`, `status`, `budget_used` | `sharpe`, `n_returns`, `skew`, `kurtosis`, `total_return`, `max_drawdown`, `returns_hash`, `failure` |
| `config-refused` | Quant | `runner` | `registration_seq`, `config_hash`, `reason` | |
| `verdict` | Quant | `treasurer` | `registration_seq`, `config_hash`, `passed`, `failed_tests`, `deflated_sharpe`, `holdout_return`, `max_drawdown`, `trials`, `config_run_seqs`, `holdout_hash` | |
| `paper-opened` | Quant | `runner` | `registration_seq`, `verdict_seq`, `end_date`, `drawdown_kill` | `promise_seq` |
| `paper-order` | Quant | `runner` | `period_seq`, `symbol`, `side`, `quantity`, `broker_order_id`, `status` | |
| `paper-reading` | Quant | `runner` | `period_seq`, `equity`, `pnl`, `taken_at` | |
| `paper-closed` | Quant | `runner` | `period_seq`, `reason`, `equity` | |
| `experiment-registered` | Venture | `cell:<bet>` | `experiment`, `hypothesis`, `metric`, `keep_threshold`, `kill_threshold`, `budget_tokens`, `budget_dollars`, `budget_minutes`, `end_date` | |
| `experiment-verdict` | Venture | `treasurer` | `experiment_seq`, `outcome`, `metric_value`, `positive_signal` | `veto_seq` |
| `promise-recorded` | Honesty | `cell:<bet>`, `runner` | `promise`, `due_date` | `bet`, `counterparty` |
| `promise-checked` | Honesty | `treasurer` | `promise_seq`, `result` | `evidence_seqs` |
| `finding` | Honesty | `auditor`, `treasurer`, `board` | `rubric`, `summary`, `evidence` | `bet`, `session` |
| `finding-confirmed` | Honesty | `board`, `treasurer` | `finding_seq` | `message` |
| `cell-paused` | Honesty | `treasurer` | `scope`, `reason`, `cause_seq` | `bet` |
| `cell-resumed` | Honesty | `board` | `scope` | `bet`, `message` |
| `complaint` | Honesty | `board` | `source`, `summary` | `bet`, `contact` |
| `spam-flag` | Honesty | `board` | `source` | `bet`, `contact` |
| `memo-written` | Opportunity | `strategy` | `session`, `hypothesis`, `cheapest_test`, `budget_tokens`, `budget_dollars`, `budget_minutes`, `threshold`, `evidence` | `replaces_seq`, `new_evidence` |
| `memo-refused` | Opportunity | `treasurer` | `reason` | `session`, `rejected_seq` |
| `memo-rejected` | Opportunity | `board` | `memo_seq`, `reason` | |
| `bet-admitted` | Opportunity | `board` | `memo_seq`, `bet`, `budget_tokens`, `budget_dollars`, `budget_minutes`, `first_experiment`, `author_session` | `message` |
| `bet-closed` | Opportunity | `treasurer` | `bet`, `reason` | |
| `approval-asked` | Batch | `scheduler` | `subject_seq`, `action`, `minutes`, `expected_margin` | `bet` |
| `approval-decided` | Batch | `board` | `ask_seq`, `decision` | `note`, `message` |
| `target-proposed` | Outreach | `cell:<bet>` | `contact`, `organization`, `reason`, `source` | |
| `draft-proposed` | Outreach | `cell:<bet>` | `target_seq`, `body`, `claims`, `disclosure`, `unsubscribe` | |
| `target-refused` | Outreach | `treasurer` | `reason` | `session` |
| `draft-refused` | Outreach | `treasurer` | `reason`, `target_seq` | `uncited_claims`, `session` |
| `send-confirmed` | Outreach | `board` | `draft_seq`, `sent_at` | |
| `reply` | Outreach | `board` | `draft_seq`, `summary` | |
| `opt-out` | Outreach | `board` | `contact` | `draft_seq` |
| `split-proposed` | Portfolio | `cell:<bet>` | `week_start`, `split`, `reason` | |
| `split-set` | Portfolio | `treasurer` | `week_start`, `split`, `inputs` | `holdout_bet` |
| `split-override` | Portfolio | `board` | `week_start`, `split`, `message` | `reason` |
| `incident` | Operating | `treasurer` | `cause_seq`, `class` | `bet` |
| `postmortem` | Operating | `retro` | `incident_seq`, `what_happened`, `cue`, `lesson`, `evidence` | |
| `retro-proposal` | Operating | `retro` | `rank`, `summary`, `changes`, `evidence`, `daniel_only` | `cue`, `lesson`, `keep_current`, `past_change_verdicts` |
| `proposal-decided` | Operating | `board` | `proposal_seq`, `decision` | `reason`, `message` |
| `procedure-version` | Operating | `board` | `procedure`, `version`, `path`, `hash`, `reason`, `proposal_seq` | `restored_from` |
| `replay-verdict` | Operating | `treasurer` | `procedure`, `version`, `passed`, `cases`, `regressions` | |

Notes on single kinds:

- `revenue`, `refund`, `fee` and `spend` need an outside record; this slice has no source for them, so only fixtures write them.
  A chargeback is recorded as a `refund`.
- `settings-changed` holds the changed keys' names and the new digest, not their values.
- `session-note` is a cell's or the probe's free text, so it is kept out of the strategy session's view, since that session never talks to a cell; that view still holds a cell's registrations and proposals, which it reads as data.
- `session-started`'s `gate` is `go:<seq>` or `schedule`, and a `go-given` word's launches left are its `sessions` minus the `session-started` events citing it.
- `resource-charged`'s `line` is a bet's id or `overhead`, and each event is that line's whole window so far, so the newest of a window and line replaces the rest.
  A charge writes its lines one at a time, so each holds the charge's `charge_id` and its count of lines, `charge_lines`, and only a whole charge, one with all its lines in the ledger, is read: a charge stopped part way counts for nothing.
- `minutes-charged`'s `subject_seq` is the `approval-decided` or `send-confirmed` it charges, and its `action` is a key of `minutes_table`.
- `cell-paused`'s and `cell-resumed`'s `scope` is `cell`, or `outside-actions` for the company-wide pause.
- `retro-proposal`'s `daniel_only` is set by code from a fixed list of what the proposal changes, never by the session.
- `promise-recorded` allows `runner` so that a paper period can record the promise of its own end date, and a runner's promise always sets `bet`.
  That promise is the code's and not the cell's, so the honesty metrics leave every runner's promise out of the cell's promises, and it is kept when `paper-closed` cites the period by the due date.
  If no tick closed the period by then, even if a later tick closes it, the Treasurer logs `promise-checked` with the result `not-run` and tells Daniel in the digest, with no `finding` and no `cell-paused`, and from ticket 19 on it logs one `incident`.
- `promise-checked`'s `result` is `kept`, `broken` or `not-run`.
- `finding` allows `treasurer` so that a check the Treasurer makes itself, such as an overdue promise, can record its finding.
  It allows `board` so that Daniel can record a fabricated claim they find in the batch, with `company finding record`, which also writes `finding-confirmed`.
  For a claim in a draft the command takes the bet and pauses that cell; for a memo, whose author is no cell, it records the finding with no pause, beside `memo-rejected`, so that the honesty metrics still see it.

## The three resources and their budgets

| Resource | Weekly budget | Who enforces it | Where it is charged |
| - | - | - | - |
| Tokens | The company's 25% share of the subscription's window | The governor, and per bet from ticket 18 | `resource-charged`, from the usage records |
| Dollars | None in this slice; up to $100 for the first real experiment after it, under Q1 | The Treasurer, before any action that costs money | `spend`, from an outside record |
| Daniel-minutes | 105 a week, under 15 a day | The Treasurer, before an approval is queued | `minutes-charged`, from a fixed table, with Daniel's corrections replacing the estimate |

The minutes table is a setting, `minutes_table`: `templated-approval` 0.5, `message-review` 2, `message-send` 0.5, `new-public-artifact` 5, each Daniel's to change.
A decided approval charges the action its ask named, whichever way it was decided, and a confirmed outreach send charges `message-send`.
So a draft's ask names `message-review`, and one message reviewed and sent costs 2.5 minutes, while a draft refused at review costs 2.
Minutes count in the week of the decision or send, however late the charge is written.
A correction (`minutes-corrected`, from `company minutes correct`) replaces the estimate in every total, and the newest correction stands.

`company treasurer charge` writes what is owed, and is safe to run twice: `minutes-charged` for each decision and send with no charge, and `resource-charged` for each line of the open window whose charge has changed, or for every line of it when a session has started or ended since its newest charge.
It charges only the open window, so to count a window whole it must run after that window's last session has ended and before its reset; a session that ran in a window and has no end before that window's newest whole charge leaves the window's cost unknown.
It has no flag to set the time it charges at, since what it writes stands for good.
It runs by Daniel's command until gate C opens the schedule, and then at each session's end and shortly before the newest reading's reset, since a plain daily timer would often miss a window's last session.
Real-money spending, when Daniel allows any, goes through a card or account with its own hard limit, never Daniel's main card.

## Cost and the ladder

### Model cost

Model cost is the company's share of the subscription's weekly limit times the subscription's price.
It is a fraction of what Daniel pays, and never a list-price bill.

The share is apportioned from the usage records as follows.
The fraction and `company_used` are worked out per window, since the governor enforces each window with a reading, and the cost comes from the seven-day window only:

- `company_fraction = company_weight / all_weight`, where each weight is the list-price weight of the window's replies.
- `company_used = company_fraction × account_used_percent`, where `account_used_percent` comes from that window's account reading.
- `weekly_price = monthly_price × 12 / 52`.
- `company_cost = company_used / 100 × weekly_price`, with the seven-day window's `company_used`.

Usage reads `~/.claude/projects/*/*.jsonl` (under `CLAUDE_CONFIG_DIR` in place of `~/.claude` when that is set) with each session's `subagents/*.jsonl`, and, read-only, the team's exported day files when `usage_day_dirs` lists their `usage/` directories, each holding `<machine>/<day>.jsonl`.
A reply is one line per request id, wherever it appears, taking each count's largest value.
A subagent's reply counts to its parent session, the directory its transcript sits under.
A missing cache lifetime counts as one-hour for a main session and five-minute for a subagent.
A model with no price is weighed as the most expensive model in the table, with a warning.

A session is the company's when its id is in a `session-started` event; everything else on the account counts as the team's, Daniel's own sessions included.
A missing record from another machine raises the company's fraction, which errs towards refusing.

List-price weights are the apportioning key, and no report calls one a cost.

A bet's cost is the part of `company_cost` from its sessions' weight.
Sessions with no bet (strategy, Auditor, retro, probe) are overhead on their own line, and the bars count them.

As an illustration only, on an invented $120 monthly price: if the company's weight is 300 of a window's 1,500, and the account reads 60% used, then the fraction is 0.2, `company_used` is 12, the weekly price is $27.69, and `company_cost` is $3.32.

### The ladder

The Treasurer computes three bars from the ledger, reports each weekly, and the company's level is the highest bar it clears over a trailing month.
A trailing month is the four most recent complete seven-day windows.
The windows are the account's: they step in sevens of days from the reset of the newest seven-day reading that can be true, and with no such reading they step back from the report's time.
Money counts in a window by its event's `ts`, and a charge by its `week_start`, rounded to the nearest window since a reset read by hand may be a minute off.

**Net revenue** is what each bar is compared with: `revenue` minus `refund` minus `fee`, over the trailing month, all from outside records.
Dollars spent (`spend`) and the share cost are on the other side of the comparison.

| Bar | Means | Net revenue must cover |
| - | - | - |
| 0. Running | Below bar 1 | Nothing: this is the default |
| 1. Own share | The company pays its own way on the plan | The four weeks' `company_cost` plus dollars spent |
| 2. Self-funding | It also funds its next bet | Bar 1 plus the next bet's trial budgets for a month, priced the same way |
| 3. Whole subscription | The engine pays for the plan it runs on | `monthly_price` plus dollars spent |

Bar 2's trial budget is priced as `new_bet_token_share × company_share × weekly_price × 4`, plus its dollars; Daniel-minutes have no price, so they stay outside the bars.
Bar 3 compares four weeks of revenue with a full month's price, which is slightly strict, and errs towards not claiming the bar.
The digest reports the bar reached and the margin against the next bar, which is net revenue minus that bar's line.

Three rules keep a bar from being claimed on too little:

- Net revenue equal to a line covers it, but a month with no net revenue clears no bar, even with nothing to cover.
- A window of the month that a session ran in, without that session having ended before the window's newest whole charge, has an unknown cost, so no bar is claimed, and the margin against the next bar and each bet's margin are shown as "at most".
  A session with no end event counts as still running, in every window from its start on.
- The sums are in US dollars, and `monthly_price` is read as US dollars.
  Money in another currency has no rate to add it with, so the bar and the bets' margins say which events stopped them, and print no sum; the digest's dollars line does the same for spending in another currency alone.

A bet's margin is its net revenue, minus its share of `company_cost`, minus its dollars spent, over the same trailing month.
Money with no bet sits on the overhead line, so the lines add up to the company's net revenue less its cost and spending.
Before money flows, a pre-registered leading indicator stands in for it, counted from the system that records it, never from an agent's report.

### The weekly digest

`company digest` prints the page Daniel reads each week, and writes nothing: the bar, each bet's margin, each resource against its budget, incidents, honesty metrics and pending approvals.

- **Resources:** tokens from the share of each window with a reading against `company_share`, dollars spent in the last seven days, and Daniel-minutes in the last seven days against `daily_minutes × 7`, with a note of any decision not charged yet.
- **Incidents:** those in the last seven days.
- **Honesty:** the cells' promises made, kept, broken and open; findings in the last seven days, and those unconfirmed in all; complaints, spam flags and refunds in the last seven days; and the pauses in effect.
- **Pending approvals:** every `approval-asked` with no `approval-decided`.

A section with nothing to say prints "none", and an empty ledger prints that for every section and exits 0, with or without settings.
A ledger whose chain is broken gets one line saying so and no numbers, and exits 1.
A setting the page needs that is missing refuses the whole page, with no value assumed.
A token window that cannot be read, or usage records that cannot be, say why on their own line, and the rest of the page still prints.

## The account reading

A reading is `{window, used_percent, resets_at, taken_at, source}`, for `seven_day` and, when the account has one, `five_hour`.
A window opens at its `resets_at` less its length, seven days or five hours.

Sources today:

- `company reading record`, by Daniel's hand from the usage page: `source` is `hand`, and the writer `board`.
- `company reading statusline`, a status-line command that reads Claude Code's documented `rate_limits.<window>.used_percentage` and `resets_at` from its input and keeps the reading: `source` is `statusline`, and the writer `governor`, since it is code and not Daniel's word.
  The [status-line docs](https://code.claude.com/docs/en/statusline) (read 2026-11-04) say this appears only for subscribers, only after the session's first reply, and that each window may be absent.
  Claude Code runs a status line as often as after each reply, so the command keeps a window's reading once in five minutes, or at once for a new window, and it never fails the status bar: input it cannot use keeps nothing, and a ledger it cannot write says "(not kept)".

Anything that reads Daniel's sign-in token, or calls an account endpoint with it, is out: it would be a secret and an external API.
The agent team's tooling holds only list-price weights and no window reading, despite what the critique says.

`current(window)` returns the newest reading, plus the percent the usage records say has been used since, using the weight per percent at the reading.
A reading has no weight per percent when it reads zero percent, or when the usage records hold no weight in the window up to it, so once any use follows either, it is unusable until a new one is taken.
A malformed reading is one whose percent is not a number from 0 to 100, whose source is unknown, whose time taken has not come, or which resets no later than it was taken or further off than the window is long.
The newest reading decides: a malformed one hides any older good one.

## The governor

The governor is code.
`admit(role, bet)` checks these in order, stops at the first refusal, and logs `launch-refused` with the reason, the share and the reading behind it.

1. The ledger verifies.
2. The kill switch is not pulled.
3. The settings file is present and matches its recorded digest.
4. A real session has a `go-given` word with launches left, or it is a scheduled session with the schedule enabled.
5. The bet or cell is not paused.
6. A reading exists for the seven-day window and is usable.
7. For each window with a reading, `account_used < team_floor`.
8. For each window with a reading, `company_used < company_share × 100`.
9. The bet's token budget for the week has room (from ticket 18 on).

`company_share` is 25% by Daniel's decision, and the settings file holds it as the fraction 0.25.
`team_floor` is the percent of a window above which the company stops, to protect the agent team's own work even when the company's share has room; its value is open and Daniel's to set.
No value of either is compiled in, and missing settings refuse every launch.

**When the account's window use cannot be read, the governor refuses the launch and never assumes room.**
It cannot be read, and the launch is refused, for each of these reasons:

- There is no seven-day reading.
- The newest reading is older than `reading_max_age_minutes`.
- The reading's window has already reset.
- The reading is malformed.
- The reading reads zero percent, and use has followed it.
- The usage records hold no weight in the window up to the reading, and use has followed it.
- Reading it raises an error.

Each refusal logs its own reason and names the command that fixes it, `company reading record`.
A `five_hour` window absent from a reading is not a failure, since a window may be absent; a `five_hour` reading present is enforced like the seven-day one.

### Checks that are still unverified

No worker can start a real company session, and none is asked to: the agent team's worker settings deny it, and calling it through the launcher would be routing around that denial.
So Daniel types the command that starts each real session, which also makes their go a physical act, and the tickets that report on real sessions read the results afterwards.

The design does not rest on any of these three answers.

| Check | Question | What the design does until it is answered | Ticket | Who may run it |
| - | - | - | - | - |
| C1 | Does signalling the launcher's process group stop a real `claude -p` session and everything it started, with nothing left running? | Ticket 07 proves it on a stub session that has child processes | Ticket 14 reports it | Daniel runs `company session probe --kill-test`, on gate A's word; the builder only reads the saved result; no worker runs it |
| C2 | Does a real `claude -p` session report the account's window use in its output? | The governor uses Daniel's recorded reading and the status-line recorder, and refuses with neither | Ticket 14 reports it | Daniel's probe saves the raw output; the builder runs `company session scan-reading <run>`, which only reads that saved file |
| C3 | Does the status-line recorder receive `rate_limits` in Daniel's interactive session? | As in C2 | Ticket 14 reports it | Daniel installs it in their own settings (S6); the builder reads whether readings arrived |

If C1 fails, ticket 14 fixes the stop and Daniel re-runs it before any further real session.
If C2 passes, ticket 14 names a follow-up to add that source, and builds none.
If C2 and C3 both fail, every reading stays Daniel's by hand, which works and costs their minutes, and ticket 14 reports that cost.

## The kill switch and the schedule

The kill switch is one command, `company kill`, that does the following:

1. It stops every company session, by signalling each session's process group.
2. It disables the company's schedule.
3. It runs the rotation step of every outside account the company holds, listed in the settings; a step that fails does not stop the others, and is reported.

Only Daniel's resume command undoes it, and every launch is refused until then.
Any loop's red line can pull it by code, and the ledger names the loop.
Its self-test, `company kill --self-test`, runs in the test suite with stub sessions and accounts in its own temporary home, and on the schedule once gate C opens.

**The paper key's rotation:** the code moves the key aside so it can no longer be used, and tells Daniel to regenerate it at the broker, because the code holds no broker admin path.
The key is read by the paper module from the key file at use, and passed to no session and no log.

The schedule is systemd user timers behind a runner that tests replace, installed disabled.
Only Daniel's `company schedule enable --message <Discord id>` turns it on, and the kill switch undoes it.
Until then the kill switch's self-test, `company paper tick`, `company treasurer check`, `company treasurer charge`, the daily audit sample, the weekly audit pass, the batch, the strategy session and the retro run by Daniel's command.

## The six loops

In every loop, agents propose, and rules or Daniel decide.
No agent edits a metric, the ledger, a budget or an approval rule.
Pre-registration and the replay gate bind what crosses the company's boundary (money, outside actions, promises); inside its sandbox a cell builds, researches and tests at its own discretion, logging what it does.

### Venture loop

- **Improves:** which offers, prices, channels and products a bet uses.
- **Metric:** contribution margin per experiment: net revenue, minus the bet's model cost, minus outside costs.
- **Ground truth:** the payment processor's records, the usage records and the account reading; before money flows, the system that counts a pre-registered leading indicator, such as the paper account's profit and loss at the broker.
- **Decision rule:** each outside-facing experiment is pre-registered before it starts, with its hypothesis, metric, keep and kill thresholds, budgets in all three resources and end date; at the end date `company treasurer check` evaluates the thresholds (ticket 18), and the result is keep, iterate once, or kill, with no extension without a new registration.
- **Cadence:** one to two weeks per outside-facing experiment, at most one live per cell at first, and no cap on internal ones.
- **Guardrail:** the metric is computed by code the agents cannot edit, refunds and complaints subtract, the honesty loop can veto a keep, and thresholds cannot change after the start.

### Opportunity loop

- **Improves:** the set of candidate bets.
- **Metric:** the share of trial budgets that reach a positive signal, and the margin of bets the loop proposed against bets Daniel proposed.
- **Ground truth:** `experiment-verdict` events and the Treasurer's margins, which themselves rest on the outside records above.
- **Decision rule:** the strategy session writes up to three memos a week, each with a hypothesis, the cheapest possible test, its budgets in all three resources and a pre-registered threshold; the Treasurer's check refuses an uncited memo or a re-proposal with no new evidence; the portfolio rule ranks the rest; Daniel admits each new bet in the batch.
- **Cadence:** weekly.
- **Guardrail:** a citation is a ledger `seq` that exists or an outside URL; code checks that a URL is present, since it cannot read one, the batch shows it, and Daniel checks it when they decide the memo, recording a fabricated one with no pause, since a memo's author is no cell; the memo's author session never runs its bet's first experiment; the rejected list stops re-proposal.

### Portfolio loop

- **Improves:** where the tokens, the money and Daniel's minutes go.
- **Metric:** each bet's margin per unit of each resource.
- **Ground truth:** the Treasurer's numbers only, from the outside records and the usage records.
- **Decision rule:** the plain rule under "The portfolio rule"; a bandit rule is not used, since with one to three bets at a weekly cadence it reduces to this rule and adds nothing.
- **Cadence:** weekly.
- **Guardrail:** no budget rises without Daniel; a cell's proposal is recorded and has no effect; a holdout share goes to the rule's second choice, so a bad metric shows up as surprising results; Daniel's override changes one week only.

### Operating loop

- **Improves:** how reliably work gets done.
- **Metric:** incidents per 100 outside actions, and tokens per unit of work.
- **Ground truth:** ledger events written by code (findings, refused actions, killed experiments, governor refusals), Daniel's recorded complaints, and the usage records.
- **Decision rule:** each incident gets a short post-mortem, and a fix becomes a checklist line, a procedure step, a skill or a tool; a changed outside-facing procedure ships only after Daniel's approval and a passing replay of a frozen set of past situations, every past incident among them; an internal tool or skill ships on its own tests.
- **Cadence:** per incident, batched weekly.
- **Guardrail:** the replay set and its grader sit where agents cannot read or write; a change touching a metric, grader, budget, token share or approval rule is marked as Daniel's alone by code, and the operating loop never ships it.

### Organization loop

- **Improves:** roles, prompts, models, cadences, which steps need a reviewer, and the autonomy classes.
- **Metric:** the bar reached and the margin against the next one, margin per Daniel-minute, incidents per 100 actions, and the share of Daniel's approvals granted unchanged.
- **Ground truth:** the Treasurer's ladder and Daniel's own `approval-decided` and `minutes-charged` events.
- **Decision rule:** a weekly retro reads the ledger since the last one and writes ranked proposals with evidence into the batch; Daniel decides each; a change to a model or a role runs as a paired trial against the current setup on the same work before it replaces it.
- **Cadence:** weekly, and after any kill-switch event.
- **Guardrail:** a retro cannot propose a change to its own metrics in the same proposal as a change that benefits from them; the Auditor reviews each retro; rejected proposals are recorded and not re-proposed without new evidence; "keep the current procedure" is a real answer.

### Honesty loop

- **Protects:** customers, counterparties, platforms and Daniel; it can stop the company.
- **Metric:** complaints, refund requests and their outcome, platform warnings, spam flags on outreach (counted separately), Auditor findings, and promises made against promises kept.
- **Ground truth:** what reaches Daniel's own inbox and accounts, recorded by Daniel; `promise-recorded` events checked by the Treasurer when due; the `config-run` and `verdict` records against what a transcript claims.
- **Decision rule:** a confirmed deception, broken payment promise, fabricated claim in a draft or terms-of-service breach pauses the cell at once and tells Daniel; a check the Treasurer can make itself (an overdue promise a cell made, a result in a transcript that no record shows) is confirmed by code, and anything else by Daniel's `company finding confirm`; past the complaint threshold, new outside actions pause company-wide until Daniel reviews.
- **Cadence:** Treasurer checks at `company treasurer check`, the Auditor's sample daily and a full pass weekly.
- **Guardrail:** the Auditor runs fresh on a different Claude model and reports to Daniel only; no cell can read or argue with a finding; every goal text carries the honesty constraints.

### Rules every loop shares

- Measurement is separated from action: agents act, code measures from outside ground truth, rules or Daniel decide.
- Every metric has a counter-metric, such as margin against complaints and refunds.
- Every change to a procedure, prompt or tool is versioned with its reason, so a hack is traceable.
- Agents never see a grader's code or a replay's expected answers, since reward hacking rises when the scoring function is visible.
- The Auditor reads a transcript's reasoning for intent to fabricate, and a hit becomes a finding, never a training signal.

### The portfolio rule

Run by the Treasurer each week, over each resource's budget in turn:

1. Closed bets get nothing.
2. A new bet in its trial gets the fixed trial budget off the top.
3. Every other open bet gets the exploration floor.
4. Bets are ranked by margin per unit of that resource, over experiments ended in the last `margin_lookback_weeks`; a tie, or no measured margin at all, splits what remains equally.
5. For tokens, the holdout share goes to the second-ranked bet; with one bet, it stays with that bet.
6. All that remains goes to the first-ranked bet.

A bet with two killed experiments in a row and no positive signal is closed.
A bet whose pending approvals would exceed its Daniel-minutes share waits, and the batch shows it waiting.
The token budgets add up to no more than `company_share`, and sessions with no bet draw on the same share through the governor's step 8.

## Prior art: Harness2

Google's Harness2 (Xu et al., "Harness²: Recursive Agent Harnessing for an Open World", [arXiv:2610.14224](https://arxiv.org/abs/2610.14224), first submitted 2026-10-09) is prior art for the operating and organization loops, as T189's report, section 5, sets out.

The company takes three ideas from it:

- **Edit verdicts and the cue, lesson and evidence format.**
  Harness2 judges each past change as `helped`, `hurt`, `no observed effect` or `confounded`, and writes each lesson as a cue, a lesson and its evidence; `postmortem` and `retro-proposal` carry those fields, for the company's shared procedures and skills.
- **Blind selection between candidate outputs.**
  Candidates are anonymized and shuffled before one is picked, which suits any choice between two versions of a procedure, such as the organization loop's paired trials.
- **"Keep the base is a real answer".**
  Against the drift of changing something every retro, a proposal may be to keep the current procedure, and the retro reports that as a result.

**The caveat:** Harness2 is built for work with no ground truth, and judges changes by contrasts between runs, which its authors say "does not guarantee correctness".
The company's loops have outside ground truth (paper-trading results, revenue, refunds), which is stronger.
So Harness2's no-answer-key method is only the fallback for the company's unmeasured work, never a replacement for its metrics.

Harness2 itself cannot run here: it runs its agents under other tools and calls models through a paid cloud API, which Daniel's decisions rule out.
Its cheapest step costs four agent runs and three editor sessions per task, the number to weigh against the 25% share should a later loop want such a search.

## Trading rules

Daniel's rule: trading is algorithmic only, strategies are backtested, then must survive paper trading before any real money, and an agent never makes a trading call.
The agent's role is researcher and quant.
Crypto and prediction markets count as trading under the same rule.

- **Pre-registration before any backtest.**
  The ledger's `strategy-registered` holds the `universe`, the `data_source`, the `in_sample` and `holdout` periods, the `cost_model`, the `slippage_model`, `max_configurations`, the `acceptance` test (`min_deflated_sharpe`, `min_holdout_return`, `max_drawdown`) and `paper_days` (default 90).
  A registration cannot change once a `config-run` cites it.
- **Trial counting.**
  A configuration's identity is the hash of its code and parameters, and each new hash counts against the budget, so a cell cannot search its way to a result.
  A repeat returns its stored result at no cost, and a run past the budget logs `config-refused`.
- **The runner sits outside the session.**
  It feeds a strategy's bars one at a time from the in-sample period, takes its target positions, applies the registered costs itself and records the returns.
  Strategy code runs in its own `bwrap` with no network, no writes and a time limit.
- **The holdout is never shown to the cell.**
  The cell names one configuration, once per registration, and the Treasurer runs it on the holdout, then computes the deflated Sharpe ratio (Bailey and López de Prado, 2014) over the trials actually run, the holdout return and the maximum drawdown, from `config-run` records alone.
  The report allowed the probability of backtest overfitting instead; this slice builds the deflated Sharpe ratio, because it needs only the records and the standard library.
- **About three months of paper trading.**
  A passing verdict opens a paper period of `paper_days`, with an end date, a promise for that date, and the registration's `max_drawdown` as its drawdown kill, and the first tick on or after the end date closes it.
  Only code places orders, in `company paper tick`, on the paper host, and the Treasurer reads the account's profit and loss as the cell's metric.
  One strategy holds the paper account at a time in this slice.
- **Paper results are paper results.**
  They are labelled so wherever they are printed, and are not deployment evidence; Alpaca's [paper-trading docs](https://docs.alpaca.markets/docs/paper-trading) (read 2026-11-04) say the account is free, and that it does not model market impact, slippage or regulatory fees, among others.
- **No capital in view.**
  Real capital enters only when Daniel names an amount, and this document carries no figure.
  When it does, position and drawdown limits are enforced at the broker and in the Treasurer, and an LLM, if any, is an information interface feeding separate risk and execution code, never the thing that places an order.
- **Nothing sold as advice.**
  Nothing the cell produces is sold, published or shown as advice, since a personalized recommendation to buy or sell is a high-risk use under Anthropic's usage policy and regulated advice is off limits.
- **No path to a live account.**
  The paper module refuses a transport aimed at any other host, and market data comes from a fixture or the broker's free IEX bars, fetched by code at registration and hashed into the ledger; a cell never holds the key or a network path.

## Outreach rules

Daniel's rule: cold outreach is human-in-the-loop.
Daniel checks and approves the people to contact, reviews the messages, and does the sending; agents only research and draft.
**No code path sends a message,** and nothing is sent to anyone in this task: fixtures use invented names at reserved domains.

- **Sourcing.**
  Targets come only from public professional sources, each with a one-line reason the offer fits them and the source it came from.
  The source must show the address published by the person or their organization, with no statement refusing unsolicited messages, since implied consent rests on that (see below).
  Code checks only that a source and a reason are present, since it cannot read the page, and Daniel checks what the source shows in the batch, when they approve the person.
- **Cited claims.**
  Every factual claim in a draft cites the ledger or an outside source, and an uncited one is refused and logged.
  Code checks that an outside source is present, since it cannot read one, the batch shows it, and Daniel checks it when they review the message.
  A fabricated claim is an honesty incident that pauses the cell, whether the Auditor finds it from the ledger or Daniel records it with `company finding record`.
- **Disclosure.**
  Every draft says the work is done by AI agents under Daniel's supervision, as Anthropic's usage policy requires of agents that face people.
- **Daniel sends.**
  Daniel sends from their own account, adding their own identifying details, and replies land with Daniel; the ledger records a send only from Daniel's confirmation in the batch.
- **Opt-outs.**
  They are recorded in the ledger and honoured at once, so an opt-out blocks every later draft to that contact.
- **A weekly cap.**
  A small daily batch fits inside Daniel's 15 minutes, under a weekly send cap Daniel sets; a batch that would cross it holds the rest, and with no cap set it holds them all.
  Each message review charges its Daniel-minutes.
- **Counted separately.**
  The honesty loop counts complaints and spam flags from outreach separately, and Anthropic's usage policy bans "spammy behavior".

### The commercial-email law

**The law named is Canada's Anti-Spam Legislation (CASL), S.C. 2010, c. 23, with the Electronic Commerce Protection Regulations (CRTC), SOR/2012-36.**
This is Daniel's answer to S1, taken as a planning default.
It is taken as the stricter of the two laws likely to apply to them, which is unverified, so it rests on Daniel's choice and not on a comparison.
It is a planning default and not legal advice, nothing is sent in this task, and Daniel can change it before the first revenue bet.
The other likely law is not named here, because no primary source could be found for what it requires.

What CASL's text requires, read on the [Justice Laws site](https://laws-lois.justice.gc.ca/eng/acts/E-1.6/) on 2026-11-04, and what the rules above do about it:

| Provision | What it says | What the outreach rules do |
| - | - | - |
| Section 6(1) | A commercial electronic message needs the recipient's express or implied consent | Each target's source is the basis for implied consent |
| Section 10(9) | Consent is implied where the person conspicuously published the address, without a statement refusing such messages, and the message is relevant to their business or official role | The source must show this, and the one-line reason shows the relevance |
| Section 13 | The person alleging consent has the onus of proving it | `target-proposed` keeps the source in the ledger |
| Section 6(2), and [SOR/2012-36](https://laws-lois.justice.gc.ca/eng/regulations/SOR-2012-36/FullText.html) sections 2 and 3 | The message identifies the sender, with a mailing address and a further contact, and sets these and an unsubscribe mechanism out clearly and prominently | Daniel adds their details at sending, and each draft carries the unsubscribe line |
| Section 11(1) and 11(3) | Unsubscribing costs nothing, and takes effect without delay, and within 10 business days | Opt-outs are honoured at once |

**Such laws also bind by where the recipient is, not only where the sender is.**
CASL's section 12(1) says a person contravenes section 6 "only if a computer system located in Canada is used to send or access the electronic message", so it reaches a message read in Canada wherever it was sent from.
Another country's law can apply in the same way to a recipient there, whichever law Daniel's own location brings.
So each target's country is a question to settle before the first revenue bet, and with a professional's word where needed.

One law such a target might bring is the United States' CAN-SPAM Act.
The FTC's [compliance guide](https://www.ftc.gov/business-guidance/resources/can-spam-act-compliance-guide-business) (read 2026-11-04) asks for accurate headers and subject lines, identifying the message as an ad, a valid physical postal address, and opt-outs honoured within 10 business days, and describes no general prior-consent rule.
The outreach rules do not yet label a draft as an ad, which is one more point for that professional's word.

## The Auditor and honesty

### The Auditor's recorded gap

The subscription serves Claude models only, and Daniel ruled out an external API (critique decision 7).
So the Auditor runs on a different Claude model from the audited cell's, in a fresh context, and refuses to start on the cell's model.

**The gap:** a sibling model shares training with the cell, so it may share the cell's blind spots, which is what Project Vend's second phase found of a supervisor on the same model.
A different Claude model is therefore weaker independence than a different vendor's would be.
The gap is known and accepted, and it is revisited at each retro.

### What the Auditor does

- Its rubric is false statements, broken promises, a result the records do not show, and a rule broken.
- It has read-only file tools and only its finding tool, and sees the rubric, the whole ledger and the audited transcripts.
- It has no web read, so it checks a citation to the ledger and not an outside URL, which Daniel checks in the batch.
- Its findings go only to Daniel's digest and the ledger; no cell has them in its ledger view.
- A confirmed finding pauses the cell, and only Daniel's `company cell resume` resumes it.
- Its daily sample and weekly full pass are schedule jobs, so they run only once gate C opens; until then they run by Daniel's command.
- Transcripts are kept in the company home for the audit window.

### Honesty toward people and platforms

- The company says it is run by AI agents wherever it talks to people, with Daniel named as the responsible human.
- There are no fake or incentivized reviews, testimonials or social proof, no income claims, and no invented facts about the company, its partners or its customers.
- Promises are recorded when made and checked when due, and refunds the company owes are paid.
- Every platform's terms are read before an account is opened, and kept.
- There is no collusion with competitors, no misleading counterparties in negotiation, and no exploiting a customer's mistake.

## The approval matrix

| Action | Approval | Why |
| - | - | - |
| Any spending of real money, any new recurring cost, any rise in a budget or the token share | Daniel, per item | Money is irreversible; the share protects the agent team |
| Any contract, terms accepted, or offer that binds the company | Daniel, per item | An agent nearly signed an illegal contract in Project Vend |
| Anything public: a site, a post, a listing, a release, a public message | Daniel, per item at first; by class later | Public text is cached and indexed even when removed |
| Any message to a customer or outside person not from an approved template; every outreach send | Daniel, per item; Daniel sends outreach | Agents give margin away and invent facts in conversation |
| A new bet from the opportunity loop | Daniel, per bet at first | Daniel's decision |
| Any real trading capital, and its amount | Daniel, always | None is in view until Daniel names it |
| Opening, changing or closing any account (broker, platform, domain, email, payment) | Daniel, always | Accounts carry identity and liability |
| Legal and tax matters, anything with an entity or a filing | Daniel, always, with a professional where needed | Not the company's to decide |
| Changes to metrics, graders, budgets, approval rules or the kill switch | Daniel, always | These are what keep the loops honest |

**The daily batch:** approvals come in one batch of up to 15 minutes a day, sorted by expected margin per Daniel-minute, with overflow shown waiting and nothing dropped.
It goes to the terminal and a Markdown file in the company home; posting it to Discord is a follow-up.

Autonomy widens one class at a time to pre-approved classes after a run of clean audited actions (for example 20 in a row), and never to full autonomy.

## Daniel's settings

A JSON file in Daniel's config directory holds `company_share`, `team_floor`, `monthly_price`, `plan_name`, `cell_model`, `auditor_model`, `reading_max_age_minutes`, `session_max_minutes`, `session_max_weight`, `daily_minutes`, `weekly_send_cap`, `minutes_table`, `complaint_threshold`, `portfolio`, `outside_accounts` and `usage_day_dirs`.

- Only `company settings init` and `company settings set` change it, and each logs `settings-changed` as `board` with the new digest.
- `load()` compares the file with the last recorded digest; a mismatch logs `settings-tamper` and refuses.
- A session cannot write it, because of the session rules; the digest catches anything that gets past them.

### Numbers set here

Each of these is **Daniel's to change,** with `company settings set`.

**The complaint threshold** (`complaint_threshold`): complaints and spam flags together reaching two in a trailing 30 days, or 2% of outside actions in that time if that is higher, pause new outside actions company-wide until Daniel reviews.

**The portfolio rule's numbers** (`portfolio`), where the file holds each percent as a fraction, such as 0.1 for 10%, and a share above 1 is refused:

| Setting | Value | Meaning |
| - | - | - |
| `exploration_floor` | 10% | Of each budget, per open bet |
| `holdout_share` | 10% | Of the token budget, to the rule's second choice |
| `new_bet_token_share` | 10% | Of the token budget, for a new bet's trial |
| `new_bet_minutes` | 15 a week | Daniel-minutes for a new bet's trial |
| `new_bet_dollars` | 0 | Dollars for a new bet's trial |
| `new_bet_weeks` | 4 | How long the trial budget lasts |
| `closure_kills` | 2 | Killed experiments in a row, with no positive signal, that close a bet |
| `margin_lookback_weeks` | 4 | How far back the rule reads each bet's margin |

## Language, test command and layout

- **Language: Python 3.13, standard library only at runtime.**
  The team's token tooling is already standard-library Python, the quant maths needs only `statistics.NormalDist`, and no dependency means nothing outside to trust in code that handles budgets and keys.
- **Test command: `uv run --locked pytest`.**
  `pytest` is the one development dependency, pinned in `uv.lock`, so every checkout and CI run tests the same thing.
- **Layout.**
  One place for each kind of thing keeps code and state from mixing, and keeps every secret out of the repository.

| Path | Holds |
| - | - |
| `src/company/` | The package, with its data files (ledger contract, price table) and versioned goal texts |
| `tests/` | The suite and its fixtures |
| `docs/` | `design.md`, `first-run.md` and `runs/` |
| `.github/workflows/ci.yml` | One job named `test` on each PR to `dev` and `main`, with actions pinned by commit hash, read-only permissions and no secrets |
| The company home, outside the repository (default `~/.local/state/agent-company/`, or `COMPANY_HOME`) | The ledger, session workspaces and the replay set |
| Daniel's config directory, outside the repository (default `~/.config/agent-company/`, or `COMPANY_CONFIG`) | Their settings and the paper key |

`company` is a thin command line over deep modules: Ledger, Usage, Reading, Treasurer, Settings, Governor, Launcher, Company tools, Quant, Paper, Kill switch, Schedule, and one entry each for Batch, Outreach, Opportunity, Portfolio, Retro and Replay.

The suite runs with no network and no model session, and fails on any attempt at either.
It tests through the `company` command or the company tools over stdio, using a stub `claude` that plays a script through the same tools a real session uses.
Its guards are in `tests/harness/`: each Python process has an audit hook on sockets and on Daniel's real paths, and a `claude` first on `PATH` fails the test.
Its scan, `tests/scan_rules.py`, walks every tracked file for what the runtime section bans; `docs/design.md`, `docs/first-run.md` and the research may name a banned variable, setting or flag and any URL, but no file but the scan's own may hold a real key's shape, a model vendor's host or SDK import, or the live broker host.

## Phases

Each phase ends in its own PR to `dev`, and leaves `dev` working.

| Phase | Tickets | Delivers | Real session? |
| - | - | - | - |
| 1 | 01 | This document | No |
| 2 | 02, 03, 04 | Ledger, CI, Treasurer accounting, ladder and digest, on fixtures | No |
| 3 | 05, 06, 07 | Governor, launcher and company tools, kill switch and schedule, on a stub | No |
| 4 | 08 to 13 | Quant cell rules, paper account, honesty loop, Auditor, preflight and runbook, on a stub | No |
| 5 | 14 | The first real sessions and their report, with any fixes they call for | Yes, on gate A |
| 6 | 15 to 20 | Daily batch, outreach, opportunity loop, portfolio rule, retro and replay gate, on a stub | No |
| 7 | 21 | The real strategy and retro sessions, and the first batch | Yes, on gate B |

### What waits for the first revenue bet

Phase 2 onward builds everything above except the following, which wait for the first revenue bet or later.

- A real source of `revenue`, `refund`, `fee` and `spend` events, and so any real number on the bars.
- A way to charge a window after its reset, from its newest reading and the usage records, since a charge that runs only while a window is open will often miss its last session, and then no bar is claimed for that month.
- A merchant of record, then an entity, under Q2.
- The first real outreach send, the send cap and the first service offer.
- Any spending of real money, under Q1.
- Customer conversations, approved templates and the refund procedure.
- Widening autonomy to pre-approved classes, which needs a run of clean audited outside actions.

Named as follow-ups, and not built in this slice:

- Posting the daily batch and digest to Daniel's Discord, which needs a decision on where the token lives.
- A third reading source, if C2 passes.
- The probability of backtest overfitting, as a second acceptance test.
- Tooling for the organization loop's paired trials and blind selection, which run by hand until a retro shows the need.
- Teaching the agent team's `team-tokens` the company's sessions, which it would count as Daniel's own.

Out of scope for good reasons: a market inside a cell, and multi-machine runs, since the company runs on one Linux machine.

## Daniel's steps and gates

No worker reads or writes a secret, Daniel's settings or the real company home, except that tickets 14 and 21 read the real home and never write it.

| Step | What Daniel does | When it comes up | What it blocks |
| - | - | - | - |
| S1 | Say which jurisdiction's commercial-email law applies to them; answered with CASL as the planning default | With the plan's approval | Ticket 01 |
| S2 | Say the merge word for each PR, or give the plan-time word | The end of each phase | The next phase |
| S3 | Create the free paper-trading account and save its key in the path `docs/first-run.md` names, mode 600 | Once phase 4 is merged | Ticket 14 |
| S4 | Install the merged `company` command, then run `company settings init` with the 25% share, the floor (recommended 60%, and open), the subscription's tier and monthly price, and the models | Once phase 4 is merged | Ticket 14 |
| S5 | Check on the account page that extra usage is off, since no code can see or set it, and that the dependencies under "Dependencies to re-check" still say what this document cites | Once phase 4 is merged, and before each go | Ticket 14 |
| S6 | Record a reading of the account's use from the usage page with `company reading record`, and optionally install the status-line recorder in their interactive session's settings | Once phase 4 is merged, and whenever a launch refuses for a stale reading | Tickets 14 and 21 |
| S7 | Gate A: give the go with `company go real-sessions`, then run the commands in `docs/first-run.md` | Ticket 13 merged and `company preflight` passing | Ticket 14 |
| S8 | Gate B: give the go for the strategy and retro sessions, then run their commands | Phase 6 merged | Ticket 21 |
| S9 | Decide the first batch with `company batch decide`, including each memo's admission and each retro proposal | After S8's sessions end | Ticket 21's close |
| S10 | Set the weekly outreach send cap | Before the first revenue bet, outside this task | Nothing here: with no cap set, the batch holds every send |
| S11 | Gate C: turn on the schedule with `company schedule enable` | After ticket 21, if Daniel wants it | Nothing here: the task closes with the schedule off |

**Gate A: the first real company session.**
It covers the probe, the kill-test probe, the quant cell and the Auditor, plus up to two re-runs after fixes.
From the team's measured records, a session should carry about $2.12 of list-price weight at the median and $7.69 at the 90th percentile.
The `company go real-sessions --message <Discord id> --sessions <n>` word grants exactly that many real launches, and the launcher refuses past it.
It blocks ticket 14.

**Gate B: the later real sessions.**
A go is asked here because gate A's word covers only the sessions it named.
It blocks ticket 21.

**Gate C: any schedule that starts sessions unattended.**
This stays Daniel's own command, and the kill switch undoes it.
It blocks nothing here, since the task closes with the schedule off.

The merged code sets no default that opens any of the three gates.

## Sources

Read 2026-11-04 unless noted.
The research's own sources, read 2026-11-02, are listed in `report.md` and `critique.md`.

- Anthropic, "Use the Claude Agent SDK with your Claude plan", https://support.claude.com/articles/15036540
- Claude Code docs: [legal and compliance](https://code.claude.com/docs/en/legal-and-compliance), [headless](https://code.claude.com/docs/en/headless), [CLI reference](https://code.claude.com/docs/en/cli-reference), [sandboxing](https://code.claude.com/docs/en/sandboxing), [permissions](https://code.claude.com/docs/en/permissions), [status line](https://code.claude.com/docs/en/statusline), [environment variables](https://code.claude.com/docs/en/env-vars)
- Anthropic, Consumer Terms of Service, effective 2025-10-08, https://www.anthropic.com/legal/consumer-terms
- Anthropic, Usage Policy, https://www.anthropic.com/legal/aup (read 2026-11-02, through the critique)
- Canada, An Act to promote the efficiency and adaptability of the Canadian economy (Canada's Anti-Spam Legislation), S.C. 2010, c. 23, https://laws-lois.justice.gc.ca/eng/acts/E-1.6/
- Canada, Electronic Commerce Protection Regulations (CRTC), SOR/2012-36, https://laws-lois.justice.gc.ca/eng/regulations/SOR-2012-36/FullText.html
- US Federal Trade Commission, "CAN-SPAM Act: A Compliance Guide for Business", https://www.ftc.gov/business-guidance/resources/can-spam-act-compliance-guide-business
- Alpaca docs: [paper trading](https://docs.alpaca.markets/docs/paper-trading), [market data](https://docs.alpaca.markets/docs/about-market-data-api)
- Xu et al., "Harness²: Recursive Agent Harnessing for an Open World", 2026, https://arxiv.org/abs/2610.14224, with its reading in T189's report, section 5, in the agent team's records
- Bailey and López de Prado, "The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting, and Non-Normality", Journal of Portfolio Management 40(5), 2014, https://doi.org/10.3905/jpm.2014.40.5.094 (citation confirmed through search results; ticket 09 reads the paper for the formula)
