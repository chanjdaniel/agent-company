"""The kill switch: `pull` stops every session, turns off the schedule and rotates each outside account.

Every action comes before any ledger write, and each failure is a reported step that stops nothing else, since a pull
has to work when the ledger cannot: `Ledger.append` raises on a broken end.
What the ledger could not take stays in the kill file, and `resume` writes it once the ledger can.
"""

import contextlib
import os
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path

from company import kill_state, launcher, schedule, settings, times
from company.ledger import AppendRefused, Ledger, LedgerBroken

STOPPED = "stopped"
FAILED = "failed"
TURNED_OFF = "turned-off"
MOVED_ASIDE = "moved-aside"
NO_KEY = "no-key"
_UNNAMED = "<unnamed>"
_LAUNCH_WAIT_SECONDS = 60
_RECORD_FAILURES = (AppendRefused, LedgerBroken, OSError, ValueError, KeyError)


@dataclass(frozen=True)
class Step:
    """One thing a pull did, as `kill-step` holds it."""

    step: str
    target: str
    result: str
    detail: str | None = None

    def fields(self) -> dict:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass(frozen=True)
class Pulled:
    """What a pull did. `seq` is its `kill-pulled`, and `unlogged` what the ledger could not take."""

    steps: tuple[Step, ...]
    seq: int | None
    unlogged: str | None

    @property
    def clean(self) -> bool:
        return self.unlogged is None and all(step.result != FAILED for step in self.steps)


class ResumeRefused(Exception):
    """Nothing was resumed, and the hold stands if there was one."""


def _stop_sweep() -> list[Step]:
    steps = []
    for found in launcher.running_sessions():
        try:
            stopped = launcher.stop_session(found)
            steps.append(Step("stop-session", found.session, STOPPED if stopped else FAILED, None if stopped else "something is still running in its process group"))
        except Exception as error:  # noqa: BLE001 - one session's failure must not spare the next.
            steps.append(Step("stop-session", found.session, FAILED, str(error)))
    return steps


def _last_sweep() -> list[Step]:
    """Wait out any launch admitted before the pull, and stop what it started; the launch also stops itself on the file."""
    steps = []
    if not launcher.wait_for_launches(_LAUNCH_WAIT_SECONDS):
        steps.append(Step("stop-session", "launch-lock", FAILED, "a launch still holds its lock, and stops itself on the kill file when it starts"))
    steps += _stop_sweep()
    launcher.close_gone_sessions()
    return steps


def _schedule_off() -> list[Step]:
    return [Step("schedule", "timers", TURNED_OFF, f"{schedule.timers_off()} installed")]


def _move_key(account: dict) -> Step:
    """The key file goes aside, so nothing can use it, and only Daniel can regenerate it at the broker."""
    source = settings.key_path(account)
    aside = source.with_name(f"{source.name}.revoked-{times.now().strftime('%Y%m%dT%H%M%SZ')}")
    try:
        source.rename(aside)
    except FileNotFoundError:
        return Step("rotation", account["name"], NO_KEY, f"{source} is not there, so nothing can use it")
    return Step("rotation", account["name"], MOVED_ASIDE, f"moved to {aside.name}: regenerate the key at the provider")


_ROTATIONS: dict[str, Callable[[dict], Step]] = {settings.MOVE_KEY: _move_key}


def _rotate(account) -> Step:
    target = account.get("name") if isinstance(account, dict) else None
    target = target if isinstance(target, str) and target else _UNNAMED
    problem = settings.account_problem(account)
    if problem:
        return Step("rotation", target, FAILED, problem)
    try:
        return _ROTATIONS[account["rotation"]](account)
    except Exception as error:  # noqa: BLE001 - one account's failure must not spare the next.
        return Step("rotation", target, FAILED, str(error))


def _rotate_accounts() -> list[Step]:
    accounts, problem = settings.accounts_for_kill()
    return [*([Step("rotation", "settings", FAILED, problem)] if problem else []), *map(_rotate, accounts)]


def _attempt(step: str, target: str, action: Callable[[], list[Step]]) -> list[Step]:
    try:
        return action()
    except Exception as error:  # noqa: BLE001 - one step's failure must not spare the next.
        return [Step(step, target, FAILED, str(error))]


def _record(record: dict, steps: list[Step]) -> tuple[int | None, str | None]:
    """Write the pull in the ledger, and keep in the file how far that got."""
    seq = record.get("seq")
    fields = {key: record[key] for key in ("by", "reason", "loop") if key in record}
    try:
        ledger = Ledger()
        if seq is None:
            seq = ledger.append("kill-pulled", fields, "killswitch")["seq"]
        for step in steps:
            ledger.append("kill-step", step.fields(), "killswitch")
        if schedule.enabled(ledger.read()):
            ledger.append("schedule-disabled", {"reason": f"kill-switch: event {seq}"}, "killswitch")
    except _RECORD_FAILURES as error:
        return seq, f"the ledger could not take the pull: {error}"
    return seq, None


def _keep(record: dict) -> str | None:
    try:
        kill_state.write(record)
    except OSError as error:
        return f"the kill file could not be written: {error}"
    return None


def pull(by: str, reason: str, loop: str | None = None) -> Pulled:
    """Stop everything now, and hold every launch until `resume`; a loop's red line calls this, and names itself."""
    record = {"by": by, "reason": reason, "at": times.stamp(times.now()), **({"loop": loop} if loop else {})}
    kept = _keep(record)
    steps = [Step("hold", "kill-file", FAILED, kept)] if kept else []
    steps += _attempt("stop-session", "sessions", _stop_sweep)
    steps += _attempt("schedule", "timers", _schedule_off)
    steps += _attempt("rotation", "settings", _rotate_accounts)
    # Last, since this may wait for a launch that is still deciding, and nothing above should wait with it.
    steps += _attempt("stop-session", "sessions", _last_sweep)
    seq, unlogged = _record(record, steps)
    kept = _keep({**record, "seq": seq, "unlogged": unlogged, "steps": [step.fields() for step in steps]})
    return Pulled(tuple(steps), seq, unlogged or kept)


def _late_fields(record: dict) -> dict:
    """A pull's record, when the ledger takes it only at the resume, saying when it really happened."""
    by = record.get("by") if isinstance(record.get("by"), str) else "unknown"
    reason = record.get("reason") if isinstance(record.get("reason"), str) else "unknown"
    at = record.get("at", "an unknown time")
    return {**record, "by": by, "reason": f"{reason} (pulled at {at}, and logged at the resume)"}


def _late_steps(record: dict) -> list[Step]:
    steps = record.get("steps")
    if not isinstance(steps, list):
        return []
    return [Step(**step) for step in steps if isinstance(step, dict) and {"step", "target", "result"} <= set(step) <= {"step", "target", "result", "detail"}]


def resume(message: str | None = None) -> list[dict]:
    """Daniel's word: close every open pull, and clear the hold; the schedule stays off, and a moved key stays moved."""
    ledger = Ledger()
    verification = ledger.verify()
    if not verification.ok:
        raise ResumeRefused("the ledger is broken, so see `company ledger verify`; the hold stands")
    record = kill_state.read()
    if record is not None and record.get("seq") is None:
        _, unlogged = _record(_late_fields(record), _late_steps(record))
        if unlogged:
            raise ResumeRefused(f"{unlogged}; the hold stands")
    pulls = kill_state.open_pulls(ledger.read())
    if not pulls and record is None:
        raise ResumeRefused("the kill switch is not pulled")
    fields = {"message": message} if message else {}
    resumed = [ledger.append("resumed", {"kill_seq": pull_event["seq"], **fields}, "board") for pull_event in pulls]
    kill_state.clear()
    return resumed


# The self-test: the whole pull, in a temporary home of its own, on stubs that this writes.


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str = ""


_TEST_MESSAGE = "1"
_TEST_INIT = (
    "settings", "init",
    "--company-share", "0.25",
    "--team-floor", "60",
    "--monthly-price", "1",
    "--plan-name", "self-test",
    "--reading-max-age-minutes", "120",
    "--session-max-minutes", "10",
    "--session-max-weight", "1",
)  # fmt: skip
# The first fails, since its directory is a file, so the check shows that the second still runs.
_TEST_ACCOUNTS = (
    '[{"name": "stub-blocked", "rotation": "move-key", "key_file": "blocked/key"},'
    ' {"name": "stub-account", "rotation": "move-key", "key_file": "stub.key"}]'
)
_TEST_WAIT_SECONDS = 30


def _executable(path: Path, text: str) -> None:
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _write_stubs(root: Path) -> dict[str, str]:
    """A session, a `systemctl` and an environment that reach nothing but `root`."""
    directory = root / "bin"
    directory.mkdir()
    here = shlex.quote(str(root))
    flags = "\n".join(launcher.flags_passed("probe"))
    _executable(
        directory / "stub-session",
        "#!/bin/sh\n"
        f"case \" $* \" in *' --help '*) cat <<'HELP'\n{flags}\nHELP\nexit 0;; esac\n"
        "cat > /dev/null\n"
        "sleep 600 &\n"
        f"echo $! > {here}/child.new && mv {here}/child.new {here}/child\n"
        f"echo $$ > {here}/leader.new && mv {here}/leader.new {here}/leader\n"
        "wait\n",
    )
    _executable(directory / "systemctl", f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {here}/systemctl-calls\n")
    environment = {key: value for key, value in os.environ.items() if key != launcher.SESSION_VARIABLE}
    environment.update(
        HOME=str(root / "home"),
        COMPANY_HOME=str(root / "company-home"),
        COMPANY_CONFIG=str(root / "company-config"),
        CLAUDE_CONFIG_DIR=str(root / "claude-config"),
        XDG_CONFIG_HOME=str(root / "xdg-config"),
        PATH=f"{directory}{os.pathsep}{os.environ.get('PATH', '')}",
    )
    environment[launcher.BINARY_VARIABLE] = str(directory / "stub-session")
    return environment


def _read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text())
    except (OSError, ValueError):
        return None


def _wait_for_pids(root: Path, launch: subprocess.Popen) -> tuple[int, int] | None:
    deadline = time.monotonic() + _TEST_WAIT_SECONDS
    while time.monotonic() < deadline and launch.poll() is None:
        leader, child = _read_pid(root / "leader"), _read_pid(root / "child")
        if leader and child:
            return leader, child
        time.sleep(0.02)
    return None


def _kill_checks(root: Path, company, group: int, launch: subprocess.Popen) -> list[Check]:
    company("kill", "--reason", "the kill switch's self-test")
    try:
        launch.wait(_TEST_WAIT_SECONDS)
        launcher_gone = True
    except subprocess.TimeoutExpired:
        launcher_gone = False
    events = Ledger(home=root / "company-home").read()

    def of_kind(kind: str) -> list[dict]:
        return [event for event in events if event["kind"] == kind]

    results = {event["target"]: event["result"] for event in of_kind("kill-step")}
    calls = (root / "systemctl-calls").read_text().splitlines()
    held = company("governor", "check", "probe")
    resumed = company("resume")
    admitted = company("governor", "check", "probe")
    return [
        Check("the session and its child stopped, with nothing left running", not launcher.group_alive(group)),
        Check("its launcher ended and logged the stop", launcher_gone and any(event["reason"] == "kill-switch" for event in of_kind("session-stopped"))),
        Check("the ledger says who pulled it", [event["by"] for event in of_kind("kill-pulled")] == ["daniel"]),
        Check("the schedule was turned off", any(" disable " in f" {call} " for call in calls) and len(of_kind("schedule-disabled")) == 1),
        Check("the account that could rotate did, after the one that could not", results.get("stub-blocked") == FAILED and results.get("stub-account") == MOVED_ASIDE and not (root / "company-config/stub.key").exists()),
        Check("a launch was refused", held.returncode != 0 and "kill check" in held.stdout),
        Check("the resume opened launches again", resumed.returncode == 0 and admitted.returncode == 0, resumed.stderr + admitted.stdout),
    ]


def _run_self_test(root: Path) -> list[Check]:
    environment = _write_stubs(root)
    python = [sys.executable, "-P", "-m", "company"]

    def company(*arguments):
        return subprocess.run([*python, *arguments], env=environment, capture_output=True, text=True, timeout=120, check=False)

    resets = times.stamp(times.now() + timedelta(hours=72))
    done = company(*_TEST_INIT)
    if done.returncode == 0:
        (root / "company-config/stub.key").write_text("a stub key\n")
        (root / "company-config/blocked").write_text("a file, where a directory is needed\n")
    for arguments in (
        ("settings", "set", "outside_accounts", _TEST_ACCOUNTS),
        ("go", "real-sessions", "--message", _TEST_MESSAGE, "--sessions", "2"),
        ("reading", "record", "--window", "seven_day", "--used-percent", "1", "--resets-at", resets),
        ("schedule", "enable", "--message", _TEST_MESSAGE),
    ):
        if done.returncode == 0:
            done = company(*arguments)
    if done.returncode != 0:
        return [Check("the temporary company was set up", False, done.stdout + done.stderr)]
    launch = subprocess.Popen([*python, "session", "start", "probe"], env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    group = None
    try:
        pids = _wait_for_pids(root, launch)
        if pids is None:
            return [Check("a stub session started with a child", False)]
        group = pids[0]
        return [Check("a stub session started with a child", True), *_kill_checks(root, company, group, launch)]
    finally:
        if launch.poll() is None:
            launch.kill()
            launch.wait()
        if group is not None and launcher.group_alive(group):
            with contextlib.suppress(OSError):
                os.killpg(group, signal.SIGKILL)


def self_test() -> list[Check]:
    """A whole pull and resume in a temporary home, which never reads or changes the home this was started from."""
    root = Path(tempfile.mkdtemp(prefix="company-kill-self-test-")).resolve()
    try:
        return _run_self_test(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)


