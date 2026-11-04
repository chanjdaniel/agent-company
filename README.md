# AgentCompany

An experiment in agentic business: an organized company of agents collaborating toward one goal, earning a profit.

The company's design is in [`docs/design.md`](docs/design.md): its structure, its runtime on Daniel's subscription, its ledger, and the self-improving loops that seek profit.
The research behind it, with its critique, Daniel's decisions and draft tickets, is in [`docs/research/2026-11-02-org-and-profit-loops/`](docs/research/2026-11-02-org-and-profit-loops/report.md).

## The code

The first slice is being built, and so far the code holds the `company` command, the ledger and its contract, the account reading, the Treasurer's share, minutes, ladder and weekly digest, the test suite and CI.
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
```

The share, the charge and a digest of a ledger with events read `settings.json` in Daniel's config directory, and refuse without it, since no value is compiled in.
No command writes that file yet, so for now it is written by hand.
The share reads `monthly_price` and `reading_max_age_minutes`, the charge also `minutes_table`, and the digest also `company_share`, `daily_minutes` and the `portfolio` setting's `new_bet_token_share` and `new_bet_dollars`.

Runtime state lives outside the repository.
The company home, `~/.local/state/agent-company/` or `COMPANY_HOME`, holds the ledger, and will hold session workspaces and the replay set.
Daniel's config directory, `~/.config/agent-company/` or `COMPANY_CONFIG`, holds their settings, and will hold the paper key.
