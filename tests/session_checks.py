"""What the session, kill switch and schedule tests read: the ledger's events, and whether a process still runs."""

import os
import time
from pathlib import Path

from company.ledger import Ledger


def patch_every_company(tmp_path, monkeypatch, *lines):
    """Every `company` started from here on, and any it starts, first runs these lines, with the suite's guard kept."""
    wrapper = tmp_path / "pythonpath" / "sitecustomize.py"
    wrapper.parent.mkdir()
    keep = (f"import sys\nsys.path.insert(0, {os.environ['PYTHONPATH']!r})\n", "import audit_guard\naudit_guard.install_from_env()\n")
    wrapper.write_text("".join(keep) + "\n".join(lines) + "\n")
    monkeypatch.setenv("PYTHONPATH", str(wrapper.parent))


def events(kind=None):
    found = Ledger().read()
    return found if kind is None else [event for event in found if event["kind"] == kind]


def wait_for(condition, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.02)
    raise AssertionError("it did not happen in time")


def pid_is_running(pid):
    try:
        text = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return False
    return text.rsplit(")", 1)[1].split()[0] != "Z"
