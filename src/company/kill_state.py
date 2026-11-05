"""Whether the kill switch is pulled, which two records say: a file in the company home, and the ledger.

The file is written first and needs no ledger, so a pull holds every launch even on a ledger that cannot take it.
The ledger outlives the file, so either record alone refuses, and only `company resume` clears both.
"""

import json
from pathlib import Path

from company import paths

RESUME = "company resume"


def _path() -> Path:
    return paths.home() / "kill.state"


def present() -> bool:
    """Whether the file is there; one that cannot be looked at counts as there."""
    try:
        _path().stat()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return True


def read() -> list[dict] | None:
    """The record of each pull since the last resume, or None with no file; a file that is no record reads as one empty pull."""
    if not present():
        return None
    try:
        pulls = json.loads(_path().read_bytes())["pulls"]
    except (OSError, ValueError, KeyError, TypeError):
        return [{}]
    return pulls if isinstance(pulls, list) and pulls and all(isinstance(pull, dict) for pull in pulls) else [{}]


def write(pulls: list[dict]) -> None:
    paths.home().mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = _path().with_name("kill.state.new")
    temporary.write_text(json.dumps({"pulls": pulls}))
    temporary.replace(_path())


def clear() -> None:
    _path().unlink(missing_ok=True)


def open_pulls(events: list[dict]) -> list[dict]:
    """Each `kill-pulled` that no `resumed` cites."""
    resumed = {event["kill_seq"] for event in events if event["kind"] == "resumed"}
    return [event for event in events if event["kind"] == "kill-pulled" and event["seq"] not in resumed]


def refusal(events: list[dict]) -> str | None:
    """Why nothing may start because of the kill switch, or None."""
    pulls = open_pulls(events)
    if pulls:
        return f"the kill switch was pulled by event {pulls[-1]['seq']}"
    if present():
        return "the kill switch was pulled, and the ledger has not recorded it"
    return None
