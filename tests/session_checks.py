"""What the session, kill switch and schedule tests read: the ledger's events, and whether a process still runs."""

import time
from pathlib import Path

from company.ledger import Ledger


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
