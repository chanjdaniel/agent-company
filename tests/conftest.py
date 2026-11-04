"""Fixtures for the whole suite, whose guards live in `harness/suite_guard.py`."""

import json
import subprocess
import sys
from pathlib import Path

import ledger_history
import pytest
import usage_records

from company import settings as settings_module
from company.ledger import Ledger

sys.path.insert(0, str(Path(__file__).resolve().parent / "harness"))

pytest_plugins = ["suite_guard"]

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def repo():
    return REPO


@pytest.fixture(autouse=True)
def company_home(tmp_path, monkeypatch):
    """Each test starts with an empty company home and config directory of its own."""
    home = tmp_path / "company-home"
    monkeypatch.setenv("COMPANY_HOME", str(home))
    monkeypatch.setenv("COMPANY_CONFIG", str(tmp_path / "company-config"))
    return home


@pytest.fixture
def company():
    """Run the installed `company` command, as a person would, and return the finished process."""
    script = Path(sys.executable).parent / "company"

    def run(*args, **kwargs):
        return subprocess.run([script, *args], capture_output=True, check=False, text=True, timeout=60, **kwargs)

    return run


@pytest.fixture
def transcripts(tmp_path, monkeypatch):
    """An empty `CLAUDE_CONFIG_DIR` of this test's own, to write transcripts into."""
    config_dir = tmp_path / "claude-config"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
    return usage_records.Transcripts(config_dir / "projects")


@pytest.fixture
def settings(tmp_path):
    """Write Daniel's settings file with what the share reads, past the checks of `company settings set` so that a
    test can hold a bad value, and record its digest as that command does; return a way to change it."""

    def write(**changes):
        path = tmp_path / "company-config" / "settings.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({**usage_records.SETTINGS, **changes}))
        fields = {"digest": settings_module.digest_of(path.read_bytes()), "keys": sorted(changes)}
        Ledger().append("settings-changed", fields, "board")

    write()
    return write


@pytest.fixture
def digest_settings(settings, transcripts):
    """The settings a digest reads, and transcripts of this test's own."""
    settings(**ledger_history.DIGEST_SETTINGS)
