# AgentCompany

An experiment in agentic business: an organized company of agents collaborating toward one goal, earning a profit.

## Status

The project has its design and is building its first slice: `docs/design.md` is the document later work is checked against, and it records Daniel's decisions.
So far the code holds the `company` command, the ledger and its contract, the account reading, the Treasurer's share, minutes, ladder and weekly digest, Daniel's settings and the governor, the session launcher and company tools, the test suite and CI; the research behind the design is in `docs/research/2026-11-02-org-and-profit-loops/` (`report.md`, `critique.md`, `decisions.md` and the draft `tickets/`).

## Working in the code

- The test command is `uv run --locked pytest`; `pytest` is the one development dependency, and the runtime is Python 3.13's standard library alone.
- Runtime state lives outside the repository: the company home is `~/.local/state/agent-company/` or `COMPANY_HOME`, and Daniel's config directory is `~/.config/agent-company/` or `COMPANY_CONFIG`.
- The suite moves all of that into a scratch directory and fails on any network attempt, any unchosen `claude` or any touch of the real paths (`tests/harness/`).
- `src/company/launcher.py` is the only code that may start a process or name `claude`, and a test scans for any other; a session test chooses `tests/harness/stub_session.py`'s stub, which plays a script through the real company tools.
- `tests/scan_rules.py` bans model API keys, hosts and SDKs and outside URLs in every tracked file, and says which documents may name them; the banned variables live in `src/company/banned.py`, the one package file exempt from the scan.

## Conventions

- `dev` is the default branch and every PR's base; `main` changes only by a release Daniel runs.
- Markdown puts one sentence on its own line, and uses the plain dash "-", never the em dash.
- Daniel is "they".
- The repository is private; still, no secret, credential or real personal data goes in it.
