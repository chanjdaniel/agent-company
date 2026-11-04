"""Where runtime state lives: always outside the repository."""

import os
from pathlib import Path


def home() -> Path:
    """The company home: the ledger, session workspaces and the replay set."""
    return Path(os.environ.get("COMPANY_HOME") or Path.home() / ".local/state/agent-company")


def config() -> Path:
    """Daniel's config directory: their settings and the paper key."""
    return Path(os.environ.get("COMPANY_CONFIG") or Path.home() / ".config/agent-company")


def claude_projects() -> Path:
    """Where Claude Code keeps its transcripts, which only Usage reads."""
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"


def workspaces() -> Path:
    """Where sessions work; the only part of the company home a session can reach."""
    return home() / "workspaces"


def runs() -> Path:
    """Each session's saved record: its settings, output and copy of its transcript."""
    return home() / "runs"
