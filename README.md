# AgentCompany

An experiment in agentic business: an organized company of agents collaborating toward one goal, earning a profit.

The company's design is in [`docs/design.md`](docs/design.md): its structure, its runtime on Daniel's subscription, its ledger, and the self-improving loops that seek profit.
The research behind it, with its critique, Daniel's decisions and draft tickets, is in [`docs/research/2026-11-02-org-and-profit-loops/`](docs/research/2026-11-02-org-and-profit-loops/report.md).

## The code

The first slice is being built, and so far the code holds the `company` command, the ledger and its contract, the test suite and CI.
It is Python 3.13 with no runtime dependency outside the standard library, and needs `uv` to run.

```sh
uv run --locked pytest                 # the test command, which reaches no network and no model
uv run company ledger verify           # check the ledger's hash chain
uv run company ledger show             # print every event
uv run company ledger append session-note --writer probe \
  --fields '{"session": "11111111-2222-4333-8444-555555555555", "text": "hello"}'
```

Runtime state lives outside the repository.
The company home, `~/.local/state/agent-company/` or `COMPANY_HOME`, holds the ledger, session workspaces and the replay set.
Daniel's config directory, `~/.config/agent-company/` or `COMPANY_CONFIG`, holds their settings and the paper key.
