# AgentCompany

An experiment in agentic business: an organized company of agents collaborating toward one goal, earning a profit.

The company's design is in [`docs/design.md`](docs/design.md): its structure, its runtime on Daniel's subscription, its ledger, and the self-improving loops that seek profit.
The research behind it, with its critique, Daniel's decisions and draft tickets, is in [`docs/research/2026-11-02-org-and-profit-loops/`](docs/research/2026-11-02-org-and-profit-loops/report.md).

## The code

The first slice is being built, and so far the code holds the `company` command, the ledger and its contract, the account reading, the Treasurer's share, minutes, ladder and weekly digest, Daniel's settings and the governor, the session launcher and company tools, the kill switch and the schedule, the quant cell's registration, backtest runner and verdict, the paper account and its period, promises and the honesty checks, the test suite and CI.
It is Python 3.13 with no runtime dependency outside the standard library, and needs `uv` to run.

```sh
uv run --locked pytest                 # the test command, which reaches no network and no model
uv run company ledger verify           # check the ledger's hash chain
uv run company ledger show             # print every event
uv run company ledger append session-note --writer probe \
  --fields '{"session": "11111111-2222-4333-8444-555555555555", "text": "hello"}'
uv run company reading record --window seven_day --used-percent 41 \
  --resets-at 2026-11-08T00:00:00Z     # keep a reading from the usage page
uv run company treasurer share         # the company's share of each window, and the week's cost
uv run company treasurer charge        # write each decision's minutes and the open window's share to the ledger
uv run company minutes correct --charge 12 --minutes 6
                                       # replace a charge's minutes in every total
uv run company digest                  # the one page to read each week
uv run company settings init --company-share 0.25 --team-floor 60 --monthly-price 130 --plan-name a-plan \
  --reading-max-age-minutes 120 --session-max-minutes 60 --session-max-weight 20
                                       # write Daniel's settings; these numbers are only an example
uv run company settings set team_floor 50
                                       # change one setting
uv run company go real-sessions --message 1234 --sessions 3
                                       # Daniel's go: exactly this many real launches
uv run company governor check cell --bet alpha
                                       # whether a session may start now, and why not
uv run company session start probe --prompt "say hello"
                                       # run one session to its end, if the governor admits it; this spends real use
uv run company kill --reason "why"     # stop every session, turn off the schedule, rotate each outside account, and hold every launch
uv run company resume                  # Daniel's word that launches may start again; the schedule stays off
uv run company kill --self-test        # a whole pull on stubs, in a temporary home of its own
uv run company schedule list           # whether the schedule is on, and its jobs
uv run company schedule install        # write each job's timer, every one off
uv run company schedule enable --message 1234
                                       # Daniel's word, and the only thing that turns the timers on
uv run company schedule disable        # turn the timers off
uv run company paper check             # one read-only call to the paper account: its status and equity
uv run company paper tick              # run the open paper period once, which only code does; no real money is involved
uv run company treasurer check         # check each promise now settled, once; a broken one pauses its cell
uv run company promise kept 12 --on 2026-11-05
                                       # Daniel's word that a cell's promise was kept, which nothing else can say
uv run company cell resume --bet alpha # lift a cell's pause, which nothing else does
uv run company complaint record --source inbox --summary "what they said"
uv run company spam-flag record --source inbox
                                       # at the threshold these pause new outside actions, until:
uv run company cell resume --outside-actions
```

The share, the charge, the governor, a session and a digest of a ledger with events read `settings.json` in Daniel's config directory, and refuse without it, since no share or floor is compiled in.
Only `company settings init` and `company settings set` change that file, and a file changed any other way refuses them all, until `company settings init` writes a new one.
`company kill` needs neither the settings nor a whole ledger to stop what runs.
The two shares are fractions, such as 0.25 for 25%, and a number above 1 is refused.

Runtime state lives outside the repository.
The company home, `~/.local/state/agent-company/` or `COMPANY_HOME`, holds the ledger, session workspaces and each session's run, and will hold the replay set.
Daniel's config directory, `~/.config/agent-company/` or `COMPANY_CONFIG`, holds their settings and the paper key, `paper.key`: its key id and secret on two lines, mode 600.
The schedule's units go in systemd's own directory for the user, `~/.config/systemd/user/` or under `XDG_CONFIG_HOME`.
