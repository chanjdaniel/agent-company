"""The launcher: the only code that starts `claude`, and only after the governor admits the launch.

It runs `claude -p` in its own process group, in a workspace that supplies no configuration, with an allow-listed
environment and generated settings, watches its time and weight, and logs its start and end in the ledger.
The stub and a real session get the same command; only Daniel's probe can prove what a real session loads.
"""

import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import timedelta
from fractions import Fraction
from pathlib import Path
from typing import NamedTuple

from company import (
    banned,
    goals,
    governor,
    kill_state,
    paths,
    schedule,
    settings,
    times,
    tools,
    usage,
)
from company.ledger import AppendRefused, Ledger, LedgerBroken

BINARY_VARIABLE = "COMPANY_CLAUDE_BIN"
SESSION_VARIABLE = "COMPANY_SESSION"
PROBE_MODEL = "claude-haiku-5-5"

# What a workspace may never hold, at any depth, since each could carry configuration or instructions into a session.
CONFIG_NAMES = (".claude", ".mcp.json", "CLAUDE.md", "CLAUDE.local.md")
# The form that keeps a session's context to what the launcher gives it, with the sign-in left alone. Together:
# `--restricted` reads only managed settings and `--settings`; `--strict-mcp-config` ignores every other server;
# `--disable-slash-commands` turns off skills and commands; a `--tools` list with no Agent tool leaves no subagent to
# call; and `_FORM_ENVIRONMENT` turns off instruction files and auto memory. Safe mode would also load no MCP server.
FORM_FLAGS = ("--restricted", "--strict-mcp-config", "--disable-slash-commands", "--tools")
_FORM_ENVIRONMENT = {"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1", "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}

# Everything else is left out, so a new variable is excluded by default.
ALLOWED_ENVIRONMENT = ("HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TZ", "TMPDIR", "CLAUDE_CONFIG_DIR")
# Fixed, so that no directory of Daniel's own tools, this command's among them, is on a session's path.
CHILD_PATH = "/usr/local/bin:/usr/bin:/bin"

_FILE_TOOLS = ("Read", "Edit", "Write", "Glob", "Grep")
_READ_TOOLS = ("Read", "Glob", "Grep")
_WEB_TOOLS = ("WebFetch", "WebSearch")
ROLE_BUILT_INS = {
    "probe": (*_FILE_TOOLS, "Bash"),
    "cell": (*_FILE_TOOLS, "Bash", *_WEB_TOOLS),
    "strategy": (*_FILE_TOOLS, *_WEB_TOOLS),
    "auditor": _READ_TOOLS,
    "retro": _READ_TOOLS,
}

GRACE_SECONDS = 5
_KILLED_GONE_SECONDS = 2
_LAUNCHER_GRACE_SECONDS = 5
_TICK_SECONDS = 0.05
_WEIGHT_EVERY_SECONDS = 0.5
_HELP_TIMEOUT_SECONDS = 30
_CHARGE_TIMEOUT_SECONDS = 120
_FIX_LOAD_FORM = (
    "update Claude Code to a version whose help lists these flags, and check the design's form again; "
    "never load user settings in its place"
)
_MAX_MINUTES = "max-minutes"
_MAX_WEIGHT = "max-weight"
_SIGNALLED = "launcher-signalled"
_GONE = "launcher-gone"
_KILLED = "kill-switch"
_NO_TRANSCRIPT = "none"
_SESSION_ENDS = ("session-ended", "session-stopped")


@dataclass(frozen=True)
class Finished:
    """A session that ran. `stopped` is why the launcher stopped it, and `unlogged` what the ledger could not take."""

    session: str
    run: str
    exit: int
    weight: float
    stopped: str | None
    unlogged: str | None


class _Refuse(Exception):
    def __init__(self, check: str, reason: str, fix: str):
        super().__init__(reason)
        self.check, self.reason, self.fix = check, reason, fix


def binary() -> str | None:
    """The `claude` to run, by absolute path."""
    chosen = os.environ.get(BINARY_VARIABLE)
    found = chosen if chosen else shutil.which("claude")
    return os.path.abspath(found) if found else None


def child_environment(session: str | None = None) -> dict[str, str]:
    """What a session's process gets: the named variables, never a banned one, and the fixed values."""
    kept = {name: os.environ[name] for name in ALLOWED_ENVIRONMENT if name in os.environ and not banned.is_banned(name)}
    fixed = {"PATH": CHILD_PATH, **_FORM_ENVIRONMENT}
    return {**kept, **fixed, **({SESSION_VARIABLE: session} if session else {})}


def _absolute(path: Path) -> str:
    """A path as a permission rule writes an absolute one."""
    return "//" + str(path).lstrip("/")


def session_settings(workspace: Path) -> dict:
    """The settings a session runs under.

    A deny rule beats an allow, and the workspace sits inside the home directory, so no deny rule can say "outside the
    workspace" at the permission layer: the two `block` keys say it, and the deny rules name what matters most.
    A `Write(path)` rule never matches, as the docs say: `Edit` rules cover every tool that edits.

    On Linux a sandbox write rule takes no wildcard but a trailing `/**`, so these settings can deny the shell these
    names only at the top of the workspace, and the docs do not say how such a rule treats a path not there yet, which
    ticket 13's probe tries. A deeper one gets past the shell, and the next launch in that workspace refuses it.
    """
    protected = (paths.config(), paths.claude_directory())
    rules = [f"{_absolute(root)}/**" for root in (*protected, paths.runs())]
    rules += [_absolute(paths.home() / name) for name in ("ledger*", "*.lock", "*.state", "kill.state/**")]
    in_workspace = [f"{_absolute(workspace)}/**/{name}" for name in CONFIG_NAMES]
    deny = [f"{tool}({rule})" for tool in ("Read", "Edit") for rule in rules]
    deny += [f"Edit({rule})" for rule in in_workspace]
    deny += [f"Edit({_absolute(workspace)}/**/.claude/**)", "Bash(company *)", "Bash(claude *)"]
    return {
        "sandbox": {
            "enabled": True,
            "failIfUnavailable": True,
            "allowUnsandboxedCommands": False,
            "filesystem": {
                "denyRead": ["~/", str(paths.home()), *map(str, protected)],
                "allowRead": [str(workspace)],
                "denyWrite": [*map(str, protected), *(str(workspace / name) for name in CONFIG_NAMES)],
            },
            "network": {"allowedDomains": [], "strictAllowlist": True},
        },
        "permissions": {
            "defaultMode": "dontAsk",
            "blockReadsOutsideWorkingDirectories": True,
            "blockWritesOutsideWorkingDirectories": True,
            "deny": deny,
        },
        "disableAllHooks": True,
        "enabledPlugins": {},
        "autoMemoryEnabled": False,
        "disableClaudeAiConnectors": True,
        "syncClaudeAiSkills": False,
        "syncClaudeAiPlugins": False,
    }


def _mcp_config(role: str, bet: str | None, session: str) -> dict:
    # `-P`: this starts in the workspace, and with the working directory on its path a file there could run as this code.
    arguments = ["-P", "-m", "company.tools", "--role", role, "--session", session, *(("--bet", bet) if bet else ())]
    server = {"type": "stdio", "command": sys.executable, "args": arguments, "env": {"COMPANY_HOME": str(paths.home()), SESSION_VARIABLE: session}}
    return {"mcpServers": {"company": server}}


def _command(claude: str, role: str, session: str, model: str, mcp: Path, session_file: Path) -> list[str]:
    built_in = ROLE_BUILT_INS[role]
    company_tools = [f"mcp__company__{name}" for name in tools.ROLE_TOOLS[role]]
    # The prompt goes on stdin, so that none of these flags that take many values can swallow it.
    return [
        claude, "-p",
        "--session-id", session,
        "--output-format", "stream-json", "--verbose",
        "--restricted",
        "--strict-mcp-config", "--mcp-config", str(mcp),
        "--settings", str(session_file),
        "--disable-slash-commands",
        "--permission-mode", "dontAsk",
        "--model", model,
        "--tools", ",".join(built_in),
        "--allowedTools", ",".join((*built_in, *company_tools)),
    ]  # fmt: skip


def _model(loaded: dict, role: str) -> str:
    if role == "probe":
        return PROBE_MODEL
    return settings.text(loaded, "auditor_model" if role == "auditor" else "cell_model")


def _workspace(chosen: str | None, run: str) -> Path:
    """The session's workspace, which must lie under the company's; with none chosen, a fresh one."""
    root = paths.workspaces()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root = root.resolve()
    if chosen is None:
        fresh = root / run
        fresh.mkdir(mode=0o700)
        return fresh
    workspace = Path(chosen).resolve()
    if not workspace.is_dir() or not workspace.is_relative_to(root) or workspace == root:
        raise _Refuse("workspace", f"not-a-workspace: a session's workspace must be a directory under {root}", "start it with no --workspace, or one under that directory")
    return workspace


def _held_configuration(workspace: Path) -> str | None:
    """The first thing in the workspace that could configure a session, at any depth, or an unreadable directory."""

    def unreadable(error: OSError) -> None:
        raise error

    try:
        for folder, directories, files in os.walk(workspace, onerror=unreadable):
            for name in (*directories, *files):
                if name in CONFIG_NAMES:
                    return str(Path(folder, name).relative_to(workspace))
    except OSError as error:
        return f"an unreadable directory ({error.strerror})"
    return None


def _check_workspace(workspace: Path) -> None:
    held = _held_configuration(workspace)
    if held is not None:
        reason = f"workspace-configures: the workspace holds {held}, which a session must not load"
        raise _Refuse("workspace", reason, f"remove it from {workspace}, after reading what wrote it")


def flags_passed(role: str) -> list[str]:
    """Every flag a launch of this role passes, each of which `claude --help` must list."""
    passed = _command("claude-path", role, "session", "model", Path("mcp"), Path("settings"))
    return [argument for argument in passed if argument.startswith("-")]


def _check_form(claude: str, role: str, environment: dict[str, str]) -> None:
    """Refuse a `claude` whose help does not list what this launch passes: it never falls back to loading more."""
    try:
        done = subprocess.run([claude, "--help"], env=environment, capture_output=True, text=True, timeout=_HELP_TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise _Refuse("load-form", f"no-load-form: `claude --help` could not run: {error}", _FIX_LOAD_FORM) from None
    if done.returncode != 0:
        raise _Refuse("load-form", f"no-load-form: `claude --help` exited {done.returncode}", _FIX_LOAD_FORM)
    missing = [flag for flag in flags_passed(role) if not re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", done.stdout)]
    if missing:
        raise _Refuse("load-form", "no-load-form: its help does not list " + ", ".join(missing), _FIX_LOAD_FORM)


def _write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


class _ProcessStat(NamedTuple):
    state: str
    group: int
    started: int


def _process_stat(pid: int) -> _ProcessStat | None:
    """A process's state, process group and start time, or None if it has gone."""
    try:
        text = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    # The name may hold spaces and brackets, so the fields count from the last bracket.
    fields = text.rsplit(")", 1)[1].split()
    return _ProcessStat(fields[0], int(fields[2]), int(fields[19]))


def _is_alive(found: _ProcessStat | None, started: int | None) -> bool:
    """Whether what was read of a process shows this one, and not a later one with its number, still running."""
    return found is not None and found.state != "Z" and found.started == started


def _alive(pid: int | None, started: int | None) -> bool:
    return pid is not None and _is_alive(_process_stat(pid), started)


def this_process() -> dict:
    """What tells this process from a later one with its number, for a record that `process_running` reads."""
    found = _process_stat(os.getpid())
    return {"pid": os.getpid(), "started": found.started if found else None}


def process_running(process) -> bool:
    """Whether the process that `this_process` described is still running; anything else in its place reads as not."""
    return isinstance(process, dict) and type(process.get("pid")) is int and _alive(process["pid"], process.get("started"))


class _Processes:
    """What every process was at one moment, so that a look through many run records costs one read of the machine."""

    def __init__(self) -> None:
        found = {int(entry.name): _process_stat(int(entry.name)) for entry in Path("/proc").iterdir() if entry.name.isdigit()}
        self.stats = {pid: stat for pid, stat in found.items() if stat is not None}
        self.live_groups = {stat.group for stat in self.stats.values() if stat.state != "Z"}


def group_alive(group: int) -> bool:
    """Whether anything but a zombie is left in a process group."""
    return group in _Processes().live_groups


def _ends_within(seconds: float, holds: Callable[[], bool]) -> bool:
    """Whether `holds` stops being true in this time."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not holds():
            return True
        time.sleep(_TICK_SECONDS)
    return not holds()


def stop_group(group: int) -> bool:
    """Stop a session's whole process group: ask, wait, then kill what is left; whether it has all gone."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(group, signal.SIGTERM)
    if _ends_within(GRACE_SECONDS, lambda: group_alive(group)):
        return True
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(group, signal.SIGKILL)
    return _ends_within(_KILLED_GONE_SECONDS, lambda: group_alive(group))


def _transcript_source(session: str) -> Path | None:
    """Where Claude Code keeps this session's transcript, in whichever project directory it chose."""
    found = sorted(paths.claude_projects().glob(f"*/{session}.jsonl"), key=lambda path: path.stat().st_mtime)
    return found[-1] if found else None


def _lines(path: Path | None) -> list[str]:
    if path is None:
        return []
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def _weight(session: str, run_dir: Path) -> Fraction:
    return usage.session_weight(_lines(_transcript_source(session)), _lines(run_dir / "output.jsonl"))


def _keep_transcript(session: str, run_dir: Path) -> tuple[str, str]:
    """Copy the transcript into the company home, where it outlives Claude Code's clean-up; its path and hash."""
    source = _transcript_source(session)
    if source is None:
        return _NO_TRANSCRIPT, _NO_TRANSCRIPT
    copy = run_dir / "transcript.jsonl"
    shutil.copyfile(source, copy)
    return str(copy), hashlib.sha256(copy.read_bytes()).hexdigest()


def _open_launch_lock() -> int:
    paths.home().mkdir(parents=True, exist_ok=True, mode=0o700)
    return os.open(paths.home() / "launch.lock", os.O_RDWR | os.O_CREAT, 0o600)


@contextlib.contextmanager
def _launch_lock() -> Iterator[None]:
    """One launch decides at a time, so that two cannot both spend a word's last launch."""
    fd = _open_launch_lock()
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def wait_for_launches(seconds: float) -> bool:
    """Wait until no launch is deciding, so that what was admitted before a pull has started; whether that happened."""
    fd = _open_launch_lock()

    def deciding() -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False

    try:
        return _ends_within(seconds, deciding)
    finally:
        os.close(fd)


def _open_sessions(events: list[dict]) -> list[dict]:
    ended = {event["session"] for event in events if event["kind"] in _SESSION_ENDS}
    return [event for event in events if event["kind"] == "session-started" and event["session"] not in ended]


def _elapsed_minutes(started_ts: str) -> float | None:
    started = times.parse_stamp(started_ts)
    return None if started is None else round((times.now() - started) / timedelta(minutes=1), 3)


def _session_state(path: Path) -> dict:
    """What a run's `session.json` says, or nothing if it says nothing usable."""
    try:
        state = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def _still_its_group(state: dict, processes: _Processes) -> bool:
    """Whether the recorded group is still this session's: a leader with another start time means the number was reused."""
    group, recorded = state.get("group"), state.get("group_started")
    if type(group) is not int or group <= 0 or recorded is None or group not in processes.live_groups:
        return False
    leader = processes.stats.get(group)
    return leader is None or leader.started == recorded


@dataclass(frozen=True)
class Running:
    """A session with something still alive, as its run's `session.json` says: a process group, a launcher, or both."""

    session: str
    group: int | None
    launcher: int | None
    launcher_started: int | None
    record: Path


def running_sessions() -> list[Running]:
    """Each session still running, read from the run directories alone, so that a broken ledger hides none.

    The launcher calling this is left out, since it runs no session now if it is asking.
    """
    found = []
    processes = _Processes()
    for path in paths.runs().glob("*/session.json"):
        state = _session_state(path)
        try:
            group = state["group"] if _still_its_group(state, processes) else None
            pid = state.get("launcher")
            alive = pid is not None and pid != os.getpid() and _is_alive(processes.stats.get(pid), state.get("launcher_started"))
            if group is not None or alive:
                found.append(Running(state["session"], group, pid if alive else None, state.get("launcher_started"), path))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return found


def stop_session(found: Running) -> bool:
    """Stop a session's group, then wait until its launcher has logged the end; a launcher that does not is killed.

    A launcher that has logged it may run on, as a process that starts sessions and does other work would.
    Whether nothing is left in the group.
    """
    stopped = found.group is None or stop_group(found.group)
    pid = found.launcher

    def still_at_it() -> bool:
        return _session_state(found.record).get("launcher") == pid and _alive(pid, found.launcher_started)

    if pid is not None and not _ends_within(_LAUNCHER_GRACE_SECONDS, still_at_it):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(pid, signal.SIGKILL)
    return stopped


def _close_if_gone(ledger: Ledger, started: dict) -> None:
    run_dir = paths.runs() / Path(started["run"]).name
    state = _session_state(run_dir / "session.json")
    if _alive(state.get("launcher"), state.get("launcher_started")):
        return
    # Its launcher has gone, so nothing watches its limits: it must not run on unwatched.
    if _still_its_group(state, _Processes()):
        stop_group(state["group"])
    # With its launcher gone, nothing more can come from it, so this read is the last word on whether it ended.
    if started["session"] not in {event["session"] for event in _open_sessions(ledger.read())}:
        return
    fields = {"session": started["session"], "reason": _GONE, "weight": float(_weight(started["session"], run_dir))}
    if run_dir.is_dir():
        with contextlib.suppress(OSError):
            _keep_transcript(started["session"], run_dir)
    elapsed = _elapsed_minutes(started["ts"])
    if elapsed is not None:
        fields["elapsed_minutes"] = elapsed
    ledger.append("session-stopped", fields, "launcher")


def close_gone_sessions() -> None:
    """Log `session-stopped` for each session whose launcher died, so that it stops claiming to run.

    A ledger that does not verify is left alone: the governor refuses the launch, and says why.
    """
    ledger = Ledger()
    try:
        if not ledger.verify().ok:
            return
        for started in _open_sessions(ledger.read()):
            _close_if_gone(ledger, started)
    except (AppendRefused, LedgerBroken, OSError) as error:
        print(f"company: a gone session could not be closed: {error}", file=sys.stderr)


def _refuse(role: str, bet: str | None, refusal: _Refuse) -> governor.Refused:
    fields = {"role": role, "check": refusal.check, "reason": refusal.reason, "fix": refusal.fix}
    if bet:
        fields["bet"] = bet
    try:
        seq = Ledger().append("launch-refused", fields, "launcher")["seq"]
    except (AppendRefused, LedgerBroken, OSError):
        seq = None
    return governor.Refused(role, bet, refusal.check, refusal.reason, refusal.fix, seq)


@dataclass(frozen=True)
class _Launch:
    role: str
    bet: str | None
    session: str
    run: str
    run_dir: Path
    workspace: Path
    model: str
    command: list[str]
    max_minutes: Fraction
    max_weight: Fraction


def _prepare(admitted: governor.Admitted, prompt: str, chosen: str | None) -> _Launch:
    """Everything a launch needs short of starting it, where each thing wrong refuses and nothing has started."""
    role, bet = admitted.role, admitted.bet
    try:
        goal = goals.load(role)
    except goals.GoalRefused as refused:
        raise _Refuse("goal", str(refused), "fix the goal text in the package") from None
    try:
        loaded = settings.load()
        model = _model(loaded, role)
        max_minutes = Fraction(str(settings.positive_number(loaded, "session_max_minutes")))
        max_weight = Fraction(str(settings.positive_number(loaded, "session_max_weight")))
    except settings.SettingsRefused as refused:
        raise _Refuse("settings", f"{refused.code}: {refused}", refused.fix) from None
    claude = binary()
    if claude is None:
        raise _Refuse("binary", "no-binary: no `claude` is on PATH", f"install Claude Code, or set {BINARY_VARIABLE}")
    _check_form(claude, role, child_environment())
    session = str(uuid.uuid4())
    run = f"{times.now().strftime('%Y%m%dT%H%M%SZ')}-{session[:8]}"
    workspace = _workspace(chosen, run)
    _check_workspace(workspace)
    run_dir = paths.runs() / run
    run_dir.mkdir(parents=True, mode=0o700)
    mcp, session_file = run_dir / "mcp.json", run_dir / "settings.json"
    _write_json(mcp, _mcp_config(role, bet, session))
    _write_json(session_file, session_settings(workspace))
    (run_dir / "prompt.txt").write_text(goal.text + (f"\n{prompt}\n" if prompt else ""))
    command = _command(claude, role, session, model, mcp, session_file)
    return _Launch(role, bet, session, run, run_dir, workspace, model, command, max_minutes, max_weight)


def _log_start(launch: _Launch, admitted: governor.Admitted) -> None:
    fields = {
        "session": launch.session,
        "role": launch.role,
        "model": launch.model,
        "run": launch.run,
        "gate": admitted.gate,
        "account_used": admitted.account_used,
        "company_used": admitted.company_used,
        "reading_seq": admitted.reading_seq,
    }
    if launch.bet:
        fields["bet"] = launch.bet
    Ledger().append("session-started", fields, "launcher")


def _record_processes(launch: _Launch, group: int | None) -> None:
    """Note who runs this session, which a later launcher reads to tell whether this one died."""
    launcher_stat, group_stat = _process_stat(os.getpid()), _process_stat(group) if group else None
    value = {
        "session": launch.session,
        "launcher": os.getpid(),
        "launcher_started": launcher_stat.started if launcher_stat else None,
        "group": group,
        "group_started": group_stat.started if group_stat else None,
    }
    _write_json(launch.run_dir / "session.json", value)


def _forget_processes(launch: _Launch) -> None:
    """Note that this launcher no longer runs this session, which then is not a running one, whatever this process does next."""
    with contextlib.suppress(OSError):
        _write_json(launch.run_dir / "session.json", {"session": launch.session, "launcher": None, "group": None})


def _spawn(launch: _Launch) -> subprocess.Popen:
    with (
        (launch.run_dir / "prompt.txt").open("rb") as prompt,
        (launch.run_dir / "output.jsonl").open("wb") as output,
        (launch.run_dir / "stderr.txt").open("wb") as errors,
    ):
        return subprocess.Popen(
            launch.command,
            stdin=prompt,
            stdout=output,
            stderr=errors,
            cwd=launch.workspace,
            env=child_environment(launch.session),
            start_new_session=True,
        )


def _watch(process: subprocess.Popen, launch: _Launch, signalled: list[int]) -> str | None:
    """Wait for the session's end, or return why it must stop first."""
    began = time.monotonic()
    next_weight = began
    while process.poll() is None:
        now = time.monotonic()
        if kill_state.present():
            return _KILLED
        if signalled:
            return _SIGNALLED
        if Fraction(now - began) >= launch.max_minutes * 60:
            return _MAX_MINUTES
        if now >= next_weight:
            next_weight = now + _WEIGHT_EVERY_SECONDS
            if _weight(launch.session, launch.run_dir) >= launch.max_weight:
                return _MAX_WEIGHT
        time.sleep(_TICK_SECONDS)
    # The kill switch may have reached the session's group before this saw `kill.state`.
    return _KILLED if kill_state.present() else None


def _finish(launch: _Launch, process: subprocess.Popen, stopped: str | None, began: float) -> Finished:
    transcript_path, transcript_hash = _NO_TRANSCRIPT, _NO_TRANSCRIPT
    unlogged = None
    try:
        transcript_path, transcript_hash = _keep_transcript(launch.session, launch.run_dir)
    except OSError as error:
        unlogged = f"the transcript could not be copied: {error}"
    weight = float(_weight(launch.session, launch.run_dir))
    ledger = Ledger()
    try:
        if stopped:
            elapsed = round((time.monotonic() - began) / 60, 3)
            ledger.append("session-stopped", {"session": launch.session, "reason": stopped, "elapsed_minutes": elapsed, "weight": weight}, "launcher")
        fields = {"session": launch.session, "exit": process.returncode, "transcript_path": transcript_path, "transcript_hash": transcript_hash, "weight": weight}
        ledger.append("session-ended", fields, "launcher")
    except (AppendRefused, LedgerBroken, OSError) as error:
        unlogged = f"the ledger could not take the session's end: {error}"
    _forget_processes(launch)
    return Finished(launch.session, launch.run, process.returncode, weight, stopped, unlogged)


def _run(launch: _Launch, process: subprocess.Popen) -> Finished:
    signalled: list[int] = []
    previous = {name: signal.signal(name, lambda number, _: signalled.append(number)) for name in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
    began = time.monotonic()
    try:
        stopped = _watch(process, launch, signalled)
        # The session's own leader may be gone with children left behind, so the group is stopped either way.
        stop_group(process.pid)
        process.wait()
    finally:
        for name, handler in previous.items():
            signal.signal(name, handler)
    return _finish(launch, process, stopped, began)


def _charge_at_the_end() -> None:
    """A session's end is when the schedule's charge is due, since the timer's next firing could fall after the window's reset.

    The job makes its own check, so with the schedule off it does nothing; if this fails, the timer's next firing does the same.
    """
    command = [sys.executable, "-P", "-m", "company", "schedule", "run", schedule.CHARGE_JOB]
    try:
        subprocess.run(command, capture_output=True, timeout=_CHARGE_TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        print(f"company: the charge at this session's end did not run: {error}", file=sys.stderr)


def start(role: str, bet: str | None = None, prompt: str = "", workspace: str | None = None, scheduled: bool = False) -> Finished | governor.Refused:
    """Run one session from admission to its end; a refused launch starts nothing."""
    with _launch_lock():
        close_gone_sessions()
        admitted = governor.admit(role, bet, scheduled)
        if isinstance(admitted, governor.Refused):
            return admitted
        try:
            launch = _prepare(admitted, prompt, workspace)
        except _Refuse as refusal:
            return _refuse(role, bet, refusal)
        # Preparing takes seconds, and the kill switch may have been pulled since the governor looked.
        if kill_state.present():
            return _refuse(role, bet, _Refuse("kill", "killed: the kill switch was pulled during this launch", governor.FIX_KILL))
        _record_processes(launch, None)
        try:
            _log_start(launch, admitted)
        except (AppendRefused, LedgerBroken, OSError) as error:
            _forget_processes(launch)
            return _refuse(role, bet, _Refuse("ledger", f"unlogged: the session's start could not be logged: {error}", governor.FIX_LEDGER))
        try:
            process = _spawn(launch)
        except OSError as error:
            _forget_processes(launch)
            # If the ledger will not take this either, the next launch closes the session, since it has no group.
            with contextlib.suppress(AppendRefused, LedgerBroken, OSError):
                Ledger().append("session-stopped", {"session": launch.session, "reason": "not-started"}, "launcher")
            return _refuse(role, bet, _Refuse("binary", f"no-start: `claude` could not start: {error.strerror}", f"check {launch.command[0]}"))
        _record_processes(launch, process.pid)
    finished = _run(launch, process)
    _charge_at_the_end()
    return finished
