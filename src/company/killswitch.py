"""The kill switch: `pull` stops every session, turns off the schedule and rotates each outside account.

Every action comes before any ledger write, and takes no lock of the ledger's, and each failure is a reported step that
stops nothing else, since a pull has to work when the ledger cannot: `Ledger.append` raises on a broken end.
What the ledger has not taken stays in the pull's own file, and `resume` writes it before it lifts the hold.
The ledger itself says how far each pull got, by the pull's id, so writing one again writes only what is missing.
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
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path

from company import contract, kill_state, launcher, paths, schedule, settings, times
from company.ledger import AppendRefused, Ledger, LedgerBroken

HOLD = "hold"
STOP_SESSION = "stop-session"
SCHEDULE = "schedule"
ROTATION = "rotation"

STOPPED = "stopped"
FAILED = "failed"
TURNED_OFF = "turned-off"
MOVED_ASIDE = "moved-aside"
NO_KEY = "no-key"
_KILL_FILE = "kill-file"
_UNNAMED = "<unnamed>"
_UNKNOWN = "unknown"
_LAUNCH_WAIT_SECONDS = 60
_LEDGER_WAIT_SECONDS = 30
# Longer than a pull's write-up may hold `kill.lock`, so that only something frozen is refused for it.
_RESUME_LOCK_WAIT_SECONDS = _LEDGER_WAIT_SECONDS + 5
_LEDGER_FAILURES = (LedgerBroken, OSError, ValueError, KeyError, TypeError)


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
    """What a pull did. `seq` is its `kill-pulled`; `unlogged` is what the ledger has not taken, `unkept` why the file could not hold it, and `held` whether either holds the launches."""

    steps: tuple[Step, ...]
    seq: int | None
    unlogged: str | None
    unkept: str | None
    held: bool

    @property
    def clean(self) -> bool:
        return self.unlogged is None and self.unkept is None and all(step.result != FAILED for step in self.steps)


class PullRefused(Exception):
    """A pull from inside a session, which did nothing."""


@dataclass(frozen=True)
class Resumed:
    """What a resume closed, and what it has to say of a pull whose record is not whole."""

    events: list[dict]
    words: list[str]


class ResumeRefused(Exception):
    """The hold stands if there was one, and no pull was closed unless a subclass says so."""


class PartlyResumed(ResumeRefused):
    """These pulls are closed, and something still holds."""

    def __init__(self, resumed: list[dict], holds: str, words: list[str]):
        closed = ", ".join(f"event {event['kill_seq']}" for event in resumed)
        super().__init__(
            f"pulls closed, {len(resumed)}{f' ({closed})' if closed else ''}; {holds}, so every launch is still refused."
            f" See `company ledger show`, and run `{kill_state.RESUME}` again.{''.join(f' {word}' for word in words)}"
        )


def _refuse_inside_a_session() -> None:
    """A session's processes cannot see Daniel's config or reach the user's timers, so a pull there would look done and be half done.

    So a red line that a company tool sees goes in the ledger, for code outside the session to pull on.
    """
    session = os.environ.get(launcher.SESSION_VARIABLE)
    if session is None:
        return
    context = {"tool": "kill-pull", **({"session": session} if contract.UUID.fullmatch(session) else {})}
    with contextlib.suppress(LedgerBroken, OSError):
        Ledger().refuse("kill-pulled", "killswitch", "inside-a-session", context)
    raise PullRefused(
        f"a session's processes cannot pull the kill switch, and `{launcher.SESSION_VARIABLE}` says this is one, so the kill switch was not pulled."
        " Nothing was stopped or held. If this is your own shell, the variable is stray: unset it and pull again"
    )


def _stop_sweep() -> list[Step]:
    steps = []
    for found in launcher.running_sessions():
        try:
            stopped = launcher.stop_session(found)
            steps.append(Step(STOP_SESSION, found.session, STOPPED if stopped else FAILED, None if stopped else "something is still running in its process group"))
        except Exception as error:  # noqa: BLE001 - one session's failure must not spare the next.
            steps.append(Step(STOP_SESSION, found.session, FAILED, str(error)))
    return steps


def _last_sweep() -> list[Step]:
    """Wait out any launch admitted before the pull, and stop what it started; the launch also stops itself on `kill.state`."""
    steps = []
    if not launcher.wait_for_launches(_LAUNCH_WAIT_SECONDS):
        steps.append(Step(STOP_SESSION, "launch-lock", FAILED, "a launch still holds its lock, and stops itself on the hold when it starts"))
    return steps + _stop_sweep()


def _schedule_off() -> list[Step]:
    return [Step(SCHEDULE, "timers", TURNED_OFF, f"{schedule.timers_off()} installed")]


def _move_key(account: dict) -> Step:
    """The key file goes aside, so nothing can use it, and only Daniel can regenerate it at the provider."""
    source = settings.key_path(account)
    aside = source.with_name(f"{source.name}.revoked-{times.now().strftime('%Y%m%dT%H%M%SZ')}")
    try:
        if stat.S_ISDIR(source.lstat().st_mode):
            return Step(ROTATION, account["name"], FAILED, f"{source} is a directory, so it was left where it is")
        source.rename(aside)
    except FileNotFoundError:
        return Step(ROTATION, account["name"], NO_KEY, f"{source} is not there, so nothing can use it")
    return Step(ROTATION, account["name"], MOVED_ASIDE, f"moved to {aside.name}: regenerate the key at the provider")


_ROTATIONS: dict[str, Callable[[dict], Step]] = {settings.MOVE_KEY: _move_key}


def _rotate(account) -> Step:
    target = account.get("name") if isinstance(account, dict) else None
    target = target if isinstance(target, str) and target else _UNNAMED
    problem = settings.account_problem(account)
    if problem:
        return Step(ROTATION, target, FAILED, problem)
    try:
        return _ROTATIONS[account["rotation"]](account)
    except Exception as error:  # noqa: BLE001 - one account's failure must not spare the next.
        return Step(ROTATION, target, FAILED, str(error))


def _rotate_accounts() -> list[Step]:
    accounts, problem = settings.accounts_for_kill()
    return [*([Step(ROTATION, "settings", FAILED, problem)] if problem else []), *map(_rotate, accounts)]


def _attempt(step: str, target: str, action: Callable[[], list[Step]]) -> list[Step]:
    try:
        return action()
    except Exception as error:  # noqa: BLE001 - one step's failure must not spare the next.
        return [Step(step, target, FAILED, str(error))]


def _settings_step() -> list[Step]:
    """Whether the list just used is the one Daniel wrote; this reads the ledger, so it comes after every action."""
    try:
        settings.load()
    except settings.SettingsMissing:
        return []
    except (settings.SettingsRefused, LedgerBroken, OSError) as error:
        return [Step(ROTATION, "settings", FAILED, f"the settings are not checked, so their list was used as it stands: {error}")]
    return []


def _note_schedule_off(ledger: Ledger, seq: int) -> None:
    if schedule.enabled(ledger.read()):
        ledger.append("schedule-disabled", {"reason": f"kill-switch: event {seq}"}, "killswitch")


def _pull_fields(record: dict) -> dict:
    """The record as `kill-pulled` holds it; a file that was no record still gets its pull written."""
    optional = {key: record[key] for key in ("pulled_at", "loop") if key in record}
    return {"pull": record["id"], "by": record.get("by", _UNKNOWN), "reason": record.get("reason", _UNKNOWN), **optional}


def _record(ledger: Ledger, record: dict) -> None:
    """Write what the ledger lacks of this pull, going by what the ledger holds, so that this is safe to run again."""
    events = [event for event in ledger.read() if event["kind"] in ("kill-pulled", "kill-step") and event.get("pull") == record["id"]]
    written = next((event for event in events if event["kind"] == "kill-pulled"), None)
    record["seq"] = (written or ledger.append("kill-pulled", _pull_fields(record), "killswitch"))["seq"]
    logged = sum(event["kind"] == "kill-step" for event in events)
    for fields in record.get("steps", [])[logged:]:
        ledger.append("kill-step", {**fields, "pull": record["id"]}, "killswitch")
    _note_schedule_off(ledger, record["seq"])


def _record_all(records: list[dict]) -> str | None:
    """Write what the ledger lacks of these pulls, where a later record of one stands over an earlier.

    Whoever calls this holds `kill_state.recording()`.
    """
    named = "the pull"
    try:
        ledger = Ledger()
        for record in {record["id"]: record for record in records}.values():
            named = f"the pull in `kill.state/{record['id']}`"
            _record(ledger, record)
    except AppendRefused as error:
        return f"the ledger could not take {named}: {str(error).rstrip('.')}; that file is damaged, so mend it or remove it"
    except _LEDGER_FAILURES as error:
        return f"the ledger could not take {named}: {type(error).__name__}: {error}; see `company ledger verify`"
    return None


def _keep(record: dict) -> str | None:
    try:
        kill_state.write(record)
    # A write-up still waiting on the ledger's lock may change the record while this reads it.
    except (OSError, RuntimeError) as error:
        return f"the pull's record could not be kept: {error}"
    return None


def _write_up(record: dict, steps: list[Step]) -> str | None:
    """Everything after the actions that needs the ledger, whose lock may be held for good by something frozen."""
    launcher.close_gone_sessions()
    found = _settings_step()
    steps.extend(found)
    record["steps"].extend(step.fields() for step in found)
    try:
        with kill_state.recording():
            # This pull's record as it stands, in case its file could not be kept.
            return _record_all([*(kill_state.read() or []), record])
    except OSError as error:
        return f"the ledger could not take the pull: {error}"


def _within(seconds: float, work: Callable[[], str | None]) -> str | None:
    """Run `work` and give its answer, or say that it has not answered; it goes on in the background meanwhile."""
    answers: list[str | None] = []

    def answer() -> None:
        try:
            answers.append(work())
        except Exception as error:  # noqa: BLE001 - a write-up that fails must be told from one still waiting.
            answers.append(f"the pull could not be written up: {error}")

    thread = threading.Thread(target=answer, daemon=True)
    thread.start()
    thread.join(seconds)
    return answers[0] if answers else f"the ledger did not answer in {seconds} seconds, so its lock is held"


def pull(by: str, reason: str, loop: str | None = None) -> Pulled:
    """Stop everything now, and hold every launch until `resume`; a loop's red line calls this, and names itself."""
    _refuse_inside_a_session()
    # Its time first, so that the file names sort in the order the pulls began.
    # Its process, until it has done, so that a resume can tell a pull still going from one that died.
    record: dict = {"id": f"{time.time_ns():020d}-{uuid.uuid4()}", "by": by, "reason": reason, "pulled_at": times.stamp(times.now()), **({"loop": loop} if loop else {}), "steps": [], "process": launcher.this_process()}
    held = _keep(record)
    steps = [Step(HOLD, _KILL_FILE, FAILED, held)] if held else []
    # The last sweep comes last, since it may wait for a launch that is still deciding, and nothing else should wait with it.
    for name, target, action in ((STOP_SESSION, "sessions", _stop_sweep), (SCHEDULE, "timers", _schedule_off), (ROTATION, "settings", _rotate_accounts), (STOP_SESSION, "sessions", _last_sweep)):
        steps += _attempt(name, target, action)
        # After each, so that a pull ended part way leaves what it had done.
        record["steps"] = [step.fields() for step in steps]
        _keep(record)
    unlogged = _within(_LEDGER_WAIT_SECONDS, lambda: _write_up(record, steps))
    del record["process"]
    unkept = _keep(record)
    if unkept and any(found["id"] == record["id"] for found in kill_state.read() or []):
        unkept += "; its file still names this process, so a resume is refused until this process ends"
    # No read of the ledger, whose lock may be held for good.
    return Pulled(tuple(steps), record.get("seq"), unlogged, unkept, kill_state.present() or record.get("seq") is not None)


def _say_what_is_missing(records: list[dict]) -> list[str]:
    """Add a step to each record that is not whole, for the ledger, and return the same word for Daniel.

    The step goes after the ones it can have, and the ledger counts what it holds of each pull, so a resume run again writes it once.
    """
    words = []
    for record in records:
        # Any process a record still names has ended, since `resume` refuses one that has not.
        missing = "its record of its steps could not be read" if record.get("steps_lost") else "its process ended before it had done" if "process" in record else None
        if missing:
            record["steps"] = [*record.get("steps", []), Step(HOLD, _KILL_FILE, FAILED, missing).fields()]
            words.append(f"Pull {record['id']}: {missing}, so what it did may not all be in the ledger: check that each session stopped and each key moved.")
    return words


def resume(message: str | None = None) -> Resumed:
    """Daniel's word: write what the ledger lacks of the pulls read here, close every open pull, and clear the hold.

    A pull still running is refused, since it is still stopping sessions and moving keys, and launches may not start under it.
    A pull that lands after the read is no part of this: its hold stands, and `PartlyResumed` says so.
    A lock that stays held is refused by name, since whatever holds it may be frozen for good.
    The schedule stays off, and a moved key stays moved.
    """
    paths.home().mkdir(parents=True, exist_ok=True, mode=0o700)
    for lock in ("kill.lock", "ledger.lock"):
        if not launcher.lock_free_within(paths.home() / lock, _RESUME_LOCK_WAIT_SECONDS):
            raise ResumeRefused(f"`{lock}` in the company home has stayed held for {_RESUME_LOCK_WAIT_SECONDS} seconds, so something may be frozen holding it: end that process, and resume again; the hold stands")
    ledger = Ledger()
    if not ledger.verify().ok:
        raise ResumeRefused("the ledger is broken, so see `company ledger verify`; the hold stands")
    with kill_state.recording():
        records = kill_state.read() or []
        for record in records:
            if launcher.process_running(record.get("process")):
                raise ResumeRefused(f"a pull is still running, in process {record['process']['pid']}, as `kill.state/{record['id']}` says, so wait for it to end, or end that process, and resume again; the hold stands")
        words = _say_what_is_missing(records)
        unlogged = _record_all(records)
        if unlogged:
            raise ResumeRefused(f"{unlogged.rstrip('.')}; the hold stands")
        pulls = kill_state.open_pulls(ledger.read())
        if not pulls and not kill_state.present():
            raise ResumeRefused("the kill switch is not pulled")
        if pulls:
            _note_schedule_off(ledger, pulls[-1]["seq"])
        fields = {"message": message} if message else {}
        resumed: list[dict] = []
        try:
            for event in pulls:
                resumed.append(ledger.append("resumed", {"kill_seq": event["seq"], **fields}, "board"))
            kill_state.clear(records)
        except (AppendRefused, LedgerBroken, OSError) as error:
            raise PartlyResumed(resumed, f"the hold could not be cleared: {str(error).rstrip('.')}", words) from error
    if kill_state.present():
        landed = {found["id"] for found in kill_state.read() or []} - {record["id"] for record in records} - {kill_state.UNLISTED}
        raise PartlyResumed(resumed, "another pull landed during this resume, and its hold stands" if landed else "the hold could not be cleared: `kill.state` is still there", words)
    return Resumed(resumed, words)


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
        # A signal first, since a launcher that is told stops its session, however far that session got.
        if launch.poll() is None:
            launch.terminate()
            try:
                launch.wait(_TEST_WAIT_SECONDS)
            except subprocess.TimeoutExpired:
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


