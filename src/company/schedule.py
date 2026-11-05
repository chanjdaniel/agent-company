"""The schedule: the company's jobs, listed in code, on systemd user timers installed disabled.

Only `enable`, by Daniel's command, turns a timer on, and the kill switch and `disable` turn every one off.
A timer's service runs `company schedule run <job>`, which asks the ledger again, so a timer left on still runs nothing.
`systemctl` is found on PATH, which is the seam a test or the kill switch's self-test replaces.
"""

import contextlib
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from company import kill_state, paths, treasurer
from company.ledger import Ledger

ENABLE = "company schedule enable --message <Discord id>"
_UNIT_PREFIX = "company-"
# A timer's service runs outside this shell, so it is told which home it serves.
_CARRIED = ("COMPANY_HOME", "COMPANY_CONFIG", "CLAUDE_CONFIG_DIR")
_SYSTEMCTL_SECONDS = 30


class ScheduleRefused(Exception):
    """The schedule cannot be turned on now; nothing was changed."""


class ScheduleFailed(Exception):
    """`systemctl` or the unit files failed."""


@dataclass(frozen=True)
class Job:
    """One timer: `calendar` is its `OnCalendar`, and `due`, if any, says at each firing whether there is work to do."""

    name: str
    command: tuple[str, ...]
    calendar: str
    due: Callable[[list[dict], datetime], bool] | None = None

    def is_due(self, events: list[dict], now: datetime) -> bool:
        return self.due is None or self.due(events, now)


CHARGE_JOB = "treasurer-charge"
# Each later ticket adds its own job here, and nothing else turns one on.
JOBS = (
    Job("kill-self-test", ("kill", "--self-test"), "daily"),
    # A window is counted whole only by a charge after its last session and before its reset. The launcher fires this at
    # each session's end; the timer catches a window's last minutes, and a session whose launcher died.
    Job(CHARGE_JOB, ("treasurer", "charge"), "*:0/5", treasurer.charge_due),
    # After New York's close in either season, so that the day's bar is whole; every day, since an end date may fall on any.
    Job("paper-tick", ("paper", "tick"), "*-*-* 21:30:00 UTC"),
    # After each UTC day ends, which is when a promise falls overdue.
    Job("treasurer-check", ("treasurer", "check"), "*-*-* 00:15:00 UTC"),
    # After that check, and an hour apart, so that the two passes start no session side by side on a Monday.
    Job("audit-sample", ("audit", "--sample", "--scheduled"), "*-*-* 01:00:00 UTC"),
    Job("audit-full", ("audit", "--full", "--scheduled"), "Mon *-*-* 02:00:00 UTC"),
)


def job(name: str) -> Job:
    return next(found for found in JOBS if found.name == name)


def journal_command(name: str) -> str:
    """Where a timer's output for this job went."""
    return f"journalctl --user -u {_UNIT_PREFIX}{name}"


def enabled(events: list[dict]) -> bool:
    """What the ledger's newest word says; with no word the schedule is off."""
    words = (event["kind"] for event in reversed(events) if event["kind"] in ("schedule-enabled", "schedule-disabled"))
    return next(words, None) == "schedule-enabled"


def run_refusal(events: list[dict]) -> str | None:
    """Why no job may run now, or None."""
    held = kill_state.refusal(events)
    if held:
        return held
    return None if enabled(events) else "the schedule is off"


def _systemctl(*arguments: str) -> None:
    binary = shutil.which("systemctl")
    if binary is None:
        raise ScheduleFailed("no systemctl is on PATH")
    try:
        done = subprocess.run([binary, "--user", *arguments], capture_output=True, text=True, timeout=_SYSTEMCTL_SECONDS, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise ScheduleFailed(f"systemctl {arguments[0]} could not run: {error}") from None
    if done.returncode != 0:
        raise ScheduleFailed(f"systemctl {arguments[0]} exited {done.returncode}: {done.stderr.strip()}")


def _quoted(value: str, expands: bool = False) -> str:
    """A value as a unit file holds it; `expands` is for a line where systemd would read `$` as a variable."""
    if "\n" in value:
        raise ScheduleFailed(f"a unit file cannot hold this value: {value!r}")
    text = value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    return '"' + (text.replace("$", "$$") if expands else text) + '"'


def _service(found: Job, unit_environment: dict[str, str]) -> str:
    command = " ".join(_quoted(part, expands=True) for part in (sys.executable, "-P", "-m", "company", "schedule", "run", found.name))
    given = {name: os.environ[name] for name in _CARRIED if os.environ.get(name)} | unit_environment
    carried = [f"Environment={_quoted(f'{name}={value}')}\n" for name, value in given.items()]
    return f"[Unit]\nDescription=AgentCompany job {found.name}\n\n[Service]\nType=oneshot\n{''.join(carried)}ExecStart={command}\n"


def _timer(found: Job) -> str:
    return (
        f"[Unit]\nDescription=AgentCompany timer for {found.name}\n\n"
        f"[Timer]\nOnCalendar={found.calendar}\nPersistent=false\n\n"
        "[Install]\nWantedBy=timers.target\n"
    )


def _timer_name(found: Job) -> str:
    return f"{_UNIT_PREFIX}{found.name}.timer"


def install(unit_environment: dict[str, str]) -> None:
    """Write each job's units, with what a job that starts a session needs told, and reload; this turns nothing on."""
    directory = paths.systemd_user()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        for found in JOBS:
            (directory / f"{_UNIT_PREFIX}{found.name}.service").write_text(_service(found, unit_environment))
            (directory / _timer_name(found)).write_text(_timer(found))
    except OSError as error:
        raise ScheduleFailed(f"the unit files cannot be written: {error}") from None
    _systemctl("daemon-reload")


def timers_off() -> int:
    """Turn off every timer of ours that is installed, from whichever job list wrote it, and say how many; needs no ledger."""
    try:
        timers = sorted(path.name for path in paths.systemd_user().glob(f"{_UNIT_PREFIX}*.timer"))
    except OSError as error:
        raise ScheduleFailed(f"the unit files cannot be read: {error}") from None
    if timers:
        _systemctl("disable", "--now", *timers)
    return len(timers)


def _turn_back_off(ledger: Ledger, reason: str) -> None:
    """The timers go first, so that a ledger that cannot take the word leaves nothing on."""
    with contextlib.suppress(ScheduleFailed):
        timers_off()
    ledger.append("schedule-disabled", {"reason": reason}, "board")


def enable(message: str, unit_environment: dict[str, str]) -> dict:
    """Daniel's word: install what is listed, log it, and turn the timers on; a failure turns them off again and logs that."""
    ledger = Ledger()
    events = ledger.read()
    held = kill_state.refusal(events)
    if held:
        raise ScheduleRefused(f"{held}, so `{kill_state.RESUME}` comes first")
    if enabled(events):
        raise ScheduleRefused("the schedule is already on")
    install(unit_environment)
    event = ledger.append("schedule-enabled", {"message": message, "jobs": [found.name for found in JOBS]}, "board")
    try:
        _systemctl("enable", "--now", *map(_timer_name, JOBS))
    except ScheduleFailed:
        _turn_back_off(ledger, "enable-failed")
        raise
    # A pull turns off what is on when it runs, so one that landed since the check above missed these.
    if kill_state.present():
        _turn_back_off(ledger, "kill-switch-pulled")
        raise ScheduleRefused(f"the kill switch was pulled during this, so `{kill_state.RESUME}` comes first")
    return event


def disable(reason: str) -> dict:
    """Daniel's word to turn it off: the timers go first, so a ledger that cannot take the word stops nothing."""
    timers_off()
    return Ledger().append("schedule-disabled", {"reason": reason}, "board")
