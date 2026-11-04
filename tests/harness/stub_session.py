"""The stub session a test chooses: a `claude` that plays a script, and that the suite's guard still covers.

The launcher's allow-list strips `PYTHONPATH` and `COMPANY_TEST_GUARD`, and its fixed `PATH` has no blocker on it.
So the seam is here, in the test's own executable and never in the company's code: the wrapper first notes the
environment it was given, which is what a real `claude` would get, then sets the guard and the blocker again, so that
the stub and the company tools it starts run guarded, and a `claude` they start hits the blocker.
"""

import json
import os
import shlex
import shutil
import stat
import sys
from pathlib import Path

import audit_guard

HARNESS = Path(__file__).resolve().parent


class Stub:
    """A stub `claude` in `directory`: `play` sets its script, and the rest read what it saw."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.binary = self.directory / "claude"
        self.play()
        blocker = shutil.which("claude")
        assert blocker is not None, "the suite's blocker is not on PATH"
        guarded = {
            "STUB_DIRECTORY": str(self.directory),
            "PYTHONPATH": str(HARNESS),
            audit_guard.ENV: os.environ[audit_guard.ENV],
        }
        settings = " ".join(f"{name}={shlex.quote(value)}" for name, value in guarded.items())
        self.binary.write_text(
            "#!/bin/sh\n"
            f"/usr/bin/env -0 > {shlex.quote(str(self.directory / 'environment'))}\n"
            f'PATH={shlex.quote(str(Path(blocker).parent))}:"$PATH" {settings} '
            f'exec {shlex.quote(sys.executable)} {shlex.quote(str(HARNESS / "stub_claude.py"))} "$@"\n'
        )
        self.binary.chmod(self.binary.stat().st_mode | stat.S_IXUSR)

    def play(self, *steps, help_lacks=(), help_exit=0):
        script = {"steps": list(steps), "help_lacks": list(help_lacks), "help_exit": help_exit}
        (self.directory / "script.json").write_text(json.dumps(script))

    def _lines(self, name):
        path = self.directory / name
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def environment(self):
        """The environment the launcher gave the last run, before the wrapper added the guard."""
        pairs = (self.directory / "environment").read_bytes().split(b"\0")
        return dict(pair.decode().split("=", 1) for pair in pairs if pair)

    def calls(self):
        return self._lines("calls.jsonl")

    def session_calls(self):
        """Every run that was a session, and not a look at `--help`."""
        return [call for call in self.calls() if "--help" not in call["argv"]]

    def tool_results(self):
        return self._lines("tool_results.jsonl")

    def tool_lists(self):
        return self._lines("tool_lists.jsonl")

    def runs(self):
        return self._lines("runs.jsonl")

    def progress(self):
        return self._lines("progress.jsonl")

    def argument(self, name):
        arguments = self.session_calls()[-1]["argv"]
        return arguments[arguments.index(name) + 1]

    def settings(self):
        return json.loads(Path(self.argument("--settings")).read_text())

    def mcp_config(self):
        return json.loads(Path(self.argument("--mcp-config")).read_text())
