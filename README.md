# AgentCompany

An experiment in agentic business: an organized company of agents collaborating toward one goal, earning a profit.

The company's design is in [`docs/design.md`](docs/design.md): its structure, its runtime on Daniel's subscription, its ledger, and the self-improving loops that seek profit.
The research behind it, with its critique, Daniel's decisions and draft tickets, is in [`docs/research/2026-11-02-org-and-profit-loops/`](docs/research/2026-11-02-org-and-profit-loops/report.md).

## The code

The first slice is being built, and so far the code holds the `company` command, the ledger and its contract, the account reading, the Treasurer's share, minutes, ladder and weekly digest, Daniel's settings and the governor, the session launcher and company tools, the test suite and CI.
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
```

The share, the charge, the governor, a session and a digest of a ledger with events read `settings.json` in Daniel's config directory, and refuse without it, since no share or floor is compiled in.
Only `company settings init` and `company settings set` change that file, and a file changed any other way refuses them all, until `company settings init` writes a new one.
The two shares are fractions, such as 0.25 for 25%, and a number above 1 is refused.

Runtime state lives outside the repository.
The company home, `~/.local/state/agent-company/` or `COMPANY_HOME`, holds the ledger, session workspaces and each session's run, and will hold the replay set.
Daniel's config directory, `~/.config/agent-company/` or `COMPANY_CONFIG`, holds their settings, and will hold the paper key.
