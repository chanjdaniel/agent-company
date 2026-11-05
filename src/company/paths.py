"""Where runtime state lives: always outside the repository."""

import os
from pathlib import Path


def home() -> Path:
    """The company home: the ledger, session workspaces and the replay set."""
    return Path(os.environ.get("COMPANY_HOME") or Path.home() / ".local/state/agent-company")


def config() -> Path:
    """Daniel's config directory: their settings and the paper key."""
    return Path(os.environ.get("COMPANY_CONFIG") or Path.home() / ".config/agent-company")


def claude_directory() -> Path:
    """Claude Code's own directory, which no session may reach."""
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def claude_projects() -> Path:
    """Where Claude Code keeps its transcripts, which Usage weighs and the launcher copies."""
    return claude_directory() / "projects"


def workspaces() -> Path:
    """Where sessions work; the only part of the company home a session can reach."""
    return home() / "workspaces"


def runs() -> Path:
    """Each session's saved record: its settings, output and copy of its transcript."""
    return home() / "runs"


def market_data() -> Path:
    """Each data source's bars, which no session can reach, since a registration's holdout is among them."""
    return home() / "market-data"


def configurations() -> Path:
    """The code and parameters of each configuration run, which the verdict runs on the holdout."""
    return home() / "configurations"


def systemd_user() -> Path:
    """Where systemd keeps the user's own units."""
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd/user"
