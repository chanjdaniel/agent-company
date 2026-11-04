"""Fixtures for the whole suite, whose guards live in `harness/suite_guard.py`."""

import subprocess
import sys
from pathlib import Path

import pytest

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
