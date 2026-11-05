"""The pytest plugin that keeps the suite away from the network, any model and Daniel's real state.

At start-up it moves HOME, the company home, the config directory, Claude Code's directory, the user's timers and
the temporary directory into one scratch directory, and puts a `claude` and a `systemctl` first on PATH that fail the test.
It refuses to start if any of those is not in the scratch directory by the time the session opens.
Every process gets `audit_guard`, this one directly and each child Python through `sitecustomize`.
"""

import os
import pwd
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

import audit_guard
import pytest

HARNESS = Path(__file__).resolve().parent
ISOLATED = ("HOME", "COMPANY_HOME", "COMPANY_CONFIG", "CLAUDE_CONFIG_DIR", "XDG_CONFIG_HOME")
# What a blocker on PATH stands for, and the word the guard's log files it under.
BLOCKED = {"claude": "model", "systemctl": "schedule"}
REFUSED_START = 3

# A session must not be able to pick another provider, sign in by a token, or find a real binary, from the shell that ran pytest.
DROPPED_ENV_PREFIXES = ("ANTHROPIC_", "CLAUDE_CODE_", "AWS_BEARER_")
DROPPED_ENV = ("COMPANY_CLAUDE_BIN",)


@dataclass
class Suite:
    root: Path
    log: Path
    bin: Path
    reported: int = 0


_suite: Suite | None = None


def _real_paths():
    """Daniel's real state, by the password file and by the shell's variables, before either moves."""
    homes = {pwd.getpwuid(os.getuid()).pw_dir, os.environ.get("HOME") or ""} - {""}
    paths = {os.environ[name] for name in ("COMPANY_HOME", "COMPANY_CONFIG", "CLAUDE_CONFIG_DIR") if os.environ.get(name)}
    if os.environ.get("XDG_CONFIG_HOME"):
        paths.add(f"{os.environ['XDG_CONFIG_HOME']}/systemd")
    for home in homes:
        paths |= {f"{home}/.claude", f"{home}/.local/state/agent-company", f"{home}/.config/agent-company", f"{home}/.config/systemd"}
    return sorted(os.path.abspath(path) for path in paths)


def _write_blocker(path, log):
    path.write_text(
        "#!/bin/sh\n"
        f"printf '{BLOCKED[path.name]}: a test ran {path.name} %s\\n' \"$*\" >> '{log}'\n"
        f"echo \"the suite's guard refused it: no test may run {path.name} without choosing a stub\" >&2\n"
        "exit 97\n"
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    global _suite
    forbidden = _real_paths()
    root = Path(tempfile.mkdtemp(prefix="company-suite-")).resolve()
    for name in ("bin", "tmp", "home", "company-home", "company-config", "claude-config", "xdg-config"):
        (root / name).mkdir()
    log = root / "guard.log"
    for name in BLOCKED:
        _write_blocker(root / "bin" / name, log)

    for name in list(os.environ):
        if name.startswith(DROPPED_ENV_PREFIXES) or name in DROPPED_ENV:
            del os.environ[name]
    os.environ.update(
        HOME=str(root / "home"),
        COMPANY_HOME=str(root / "company-home"),
        COMPANY_CONFIG=str(root / "company-config"),
        CLAUDE_CONFIG_DIR=str(root / "claude-config"),
        XDG_CONFIG_HOME=str(root / "xdg-config"),
        TMPDIR=str(root / "tmp"),
        PATH=f"{root / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
        PYTHONPATH=str(HARNESS),
    )
    tempfile.tempdir = None

    # The checkout is always in reach, even when it sits under a forbidden path, as a job's scratch clone may.
    audit_guard.configure(log, (root, HARNESS.parents[1]), forbidden)
    audit_guard.install()
    os.environ[audit_guard.ENV] = audit_guard.env_value()
    _suite = Suite(root, log, root / "bin")


def _isolation_problems():
    problems = []
    for name in ISOLATED:
        value = os.environ.get(name)
        if not value:
            problems.append(f"{name} is not set")
        elif not Path(value).resolve().is_relative_to(_suite.root):
            problems.append(f"{name} points at {value}, outside the suite's scratch directory")
    return problems


@pytest.hookimpl(tryfirst=True)
def pytest_sessionstart(session):
    problems = _isolation_problems()
    for name in BLOCKED:
        if shutil.which(name) != str(_suite.bin / name):
            problems.append(f"the first {name} on PATH is not the suite's blocker")
    if problems:
        pytest.exit(
            "the suite refuses to start, and ran no test, because the real company home, config or "
            "~/.claude could be in reach: " + "; ".join(problems),
            returncode=REFUSED_START,
        )


def _new_violations():
    lines = _suite.log.read_text().splitlines() if _suite.log.exists() else []
    new = lines[_suite.reported :]
    _suite.reported = len(lines)
    return new


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    problems = _isolation_problems()
    if problems:
        pytest.fail("the suite's guard: " + "; ".join(problems), pytrace=False)
    try:
        return (yield)
    finally:
        new = _new_violations()
        if new:
            pytest.fail("the suite's guard caught this, in this test or just before it: " + "; ".join(new), pytrace=False)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session):
    new = _new_violations()
    if new:
        pytest.exit("the suite's guard caught something outside a test: " + "; ".join(new), returncode=1)


@pytest.hookimpl(trylast=True)
def pytest_unconfigure(config):
    if _suite is not None:
        shutil.rmtree(_suite.root, ignore_errors=True)
