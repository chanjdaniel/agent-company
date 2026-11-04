"""The pytest plugin that keeps the suite away from the network, any model and Daniel's real state.

At start-up it moves HOME, the company home, the config directory, Claude Code's directory and the
temporary directory into one scratch directory, and puts a `claude` first on PATH that fails the test.
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
ISOLATED = ("HOME", "COMPANY_HOME", "COMPANY_CONFIG", "CLAUDE_CONFIG_DIR")
REFUSED_START = 3

# A session must not be able to pick another provider, or a real binary, from the shell that ran pytest.
DROPPED_ENV_PREFIXES = ("ANTHROPIC_", "CLAUDE_CODE_USE_")
DROPPED_ENV = ("COMPANY_CLAUDE_BIN",)


@dataclass
class Suite:
    root: Path
    log: Path
    blocker: Path
    reported: int = 0


_suite: Suite | None = None


def _real_paths():
    """Daniel's real state, by the password file and by the shell's variables, before either moves."""
    homes = {pwd.getpwuid(os.getuid()).pw_dir, os.environ.get("HOME") or ""} - {""}
    paths = {os.environ[name] for name in ISOLATED[1:] if os.environ.get(name)}
    for home in homes:
        paths |= {f"{home}/.claude", f"{home}/.local/state/agent-company", f"{home}/.config/agent-company"}
    return sorted(os.path.abspath(path) for path in paths)


def _write_blocker(path, log):
    path.write_text(
        "#!/bin/sh\n"
        f"printf 'model: a test ran claude %s\\n' \"$*\" >> '{log}'\n"
        "echo \"the suite's guard refused it: no test may run claude without choosing the stub\" >&2\n"
        "exit 97\n"
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    global _suite
    forbidden = _real_paths()
    root = Path(tempfile.mkdtemp(prefix="company-suite-")).resolve()
    for name in ("bin", "tmp", "home", "company-home", "company-config", "claude-config"):
        (root / name).mkdir()
    log = root / "guard.log"
    blocker = root / "bin/claude"
    _write_blocker(blocker, log)

    for name in list(os.environ):
        if name.startswith(DROPPED_ENV_PREFIXES) or name in DROPPED_ENV:
            del os.environ[name]
    os.environ.update(
        HOME=str(root / "home"),
        COMPANY_HOME=str(root / "company-home"),
        COMPANY_CONFIG=str(root / "company-config"),
        CLAUDE_CONFIG_DIR=str(root / "claude-config"),
        TMPDIR=str(root / "tmp"),
        PATH=f"{root / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
        PYTHONPATH=str(HARNESS),
    )
    tempfile.tempdir = None

    # The checkout is always in reach, even when it sits under a forbidden path, as a job's scratch clone may.
    audit_guard.configure(log, (root, HARNESS.parents[1]), forbidden)
    audit_guard.install()
    os.environ[audit_guard.ENV] = audit_guard.env_value()
    _suite = Suite(root, log, blocker)


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
    if shutil.which("claude") != str(_suite.blocker):
        problems.append("the first claude on PATH is not the suite's blocker")
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
