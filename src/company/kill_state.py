"""Whether the kill switch is pulled, which two records say: a directory in the company home, and the ledger.

Each pull writes one file of its own there, first, with no lock and no ledger, so a pull holds every launch even on a
ledger that cannot take it, and pulls that overlap cannot overwrite each other.
The ledger outlives the directory, so either record alone refuses, and only `company resume` clears both.
"""

import contextlib
import fcntl
import json
import os
from collections.abc import Iterator
from pathlib import Path

from company import paths

RESUME = "company resume"
_WRITE_TRIES = 3


def _path() -> Path:
    return paths.home() / "kill.state"


def present() -> bool:
    """Whether it is there; one that cannot be looked at counts as there."""
    try:
        _path().stat()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return True


def _read_one(name: str) -> dict:
    """One pull's record, whose `id` is its file's name; a file that is no record reads as an empty one, and `steps_lost` says what could not be read."""
    try:
        record = json.loads((_path() / name).read_bytes())
    except (OSError, ValueError):
        record = {}
    record = record if isinstance(record, dict) else {}
    steps = record.get("steps")
    if isinstance(steps, list) and all(isinstance(step, dict) for step in steps):
        return {**record, "id": name}
    kept = [step for step in steps if isinstance(step, dict)] if isinstance(steps, list) else []
    return {**record, "steps": kept, "steps_lost": True, "id": name}


def read() -> list[dict] | None:
    """The record of each pull since the last resume, oldest first, or None with none there; anything else there reads as one empty pull."""
    if not present():
        return None
    try:
        names = os.listdir(_path())
    except FileNotFoundError:
        return None
    except OSError:
        return [{"id": _path().name, "steps_lost": True}]
    return [_read_one(name) for name in sorted(names)]


def write(record: dict) -> None:
    """Keep one pull's record, which only that pull writes, whole; a resume may take the directory away at any moment."""
    paths.home().mkdir(parents=True, exist_ok=True, mode=0o700)
    # Beside the directory and not in it, so that a write cut short leaves it nothing to hold the directory open with.
    temporary = paths.home() / f"kill.state.{record['id']}.new"
    temporary.write_text(json.dumps(record))
    for try_left in reversed(range(_WRITE_TRIES)):
        _path().mkdir(mode=0o700, exist_ok=True)
        try:
            temporary.replace(_path() / record["id"])
            return
        except FileNotFoundError:
            if not try_left:
                raise


def clear(records: list[dict]) -> None:
    """Remove these pulls' records, and the hold with them unless another pull has landed since they were read."""
    path = _path()
    if not path.is_dir():
        path.unlink(missing_ok=True)
        return
    for record in records:
        (path / record["id"]).unlink(missing_ok=True)
    # What refuses this is a pull's file that this did not read, and that pull's hold must stand.
    with contextlib.suppress(OSError):
        path.rmdir()


@contextlib.contextmanager
def recording() -> Iterator[None]:
    """One writer at a time of pulls and resumes into the ledger, which says how far each got. No action of a pull waits on this."""
    paths.home().mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(paths.home() / "kill.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


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
