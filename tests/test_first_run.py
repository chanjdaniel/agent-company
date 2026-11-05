"""`docs/first-run.md`: every command it names, run in its order, on the stub, by the code `uv tool install` puts in place.

The walk starts from a home with nothing in it and sets only `HOME`, so that each command finds what the one before left where the runbook says.
`company paper check` is the one command not in a child, since the broker's fake is chosen in this process; no test reaches the broker.
"""

import json
import os
import re
import shutil
import subprocess
from datetime import timedelta
from pathlib import Path

from session_checks import events
from test_paper import FakeBroker
from usage_records import TEAM, transcript_line

from company import cli, paper, paths, times

REPO = Path(__file__).resolve().parents[1]
BLOCK = re.compile(r"^```(sh|json)\n(.*?)\n```$", re.MULTILINE | re.DOTALL)


def runbook() -> str:
    return (REPO / "docs/first-run.md").read_text()


def blocks() -> list[tuple[str, list[str]]]:
    """Each command in order, with the quoted fragments its next line says to expect."""
    text = runbook()
    found = []
    for block in BLOCK.finditer(text):
        # The JSON is the status line's setting, whose command is what Claude Code would run.
        command = block[2] if block[1] == "sh" else json.loads(block[2])["statusLine"]["command"]
        after = text[block.end() :].lstrip("\n").split("\n", 1)[0]
        assert after.startswith("You should see"), f"{command} says nothing of what to see"
        found.append((command, re.findall(r"`([^`]+)`", after)))
    return found


def test_each_block_is_one_command_and_says_what_to_see():
    assert blocks()
    for command, _ in blocks():
        assert "\n" not in command, command


def test_the_steps_come_in_order():
    headings = re.findall(r"^## (S\d):", runbook(), re.MULTILINE)
    assert headings == ["S3", "S4", "S5", "S6", "S7"]


def test_every_line_is_one_sentence():
    in_fence = False
    for line in runbook().splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
        if in_fence or not line:
            continue
        prose = re.sub(r"`[^`]*`|\[[^\]]*\]\([^)]*\)", "x", line)
        assert not re.search(r"[.!?][*\"]* +[A-Z]", prose), line
    assert chr(0x2014) not in runbook()


def test_it_names_the_three_dependencies_to_check_in_s5():
    s5 = runbook().split("## S5:", 1)[1].split("\n## ", 1)[0]
    assert "extra usage is off" in s5
    assert "`claude -p` on plan limits" in s5
    assert "--" + "bare` becoming the default" in s5
    assert "The terms" in s5


def test_it_names_the_cost_the_design_gives_a_session():
    text = runbook()
    assert "$2.12" in text
    assert "$7.69" in text
    assert "$2.12" in (REPO / "docs/design.md").read_text()


def test_it_says_how_to_stop_everything_and_what_is_daniels_alone():
    text = runbook()
    assert "## Stop everything" in text
    assert "## Which commands are yours alone" in text
    alone = text.split("## Which commands are yours alone", 1)[1].split("\n## ", 1)[0]
    for command in ("company session probe", "company session probe --kill-test", "company go real-sessions", "company kill", "company resume", "company paper check"):
        assert f"`{command}`" in alone


def test_it_says_sign_in_is_unproven_and_what_a_failed_one_looks_like():
    text = runbook()
    assert "Sign-in under `--restricted` is unproven until this probe." in text
    assert "A failed sign-in looks like this" in text
    # Word for word what the command prints on one.
    assert "The check proved nothing: the session exited" in text


def test_it_names_the_paper_keys_outside_accounts_entry_as_the_settings_write_it():
    from company import settings

    assert json.dumps(settings.PAPER_ACCOUNTS[0]) in runbook()


def test_the_commands_it_says_are_daniels_exist(company):
    alone = runbook().split("## Which commands are yours alone", 1)[1].split("\n## ", 1)[0]
    for command in re.findall(r"`(company [^`<]+?)`", alone):
        assert company(*command.split()[1:], "--help").returncode == 0, command


def cell_steps():
    return [
        {"do": "reply", "request": "cell-1", "output": 1, "text": "The cell's words."},
        {"do": "tool", "name": "record_promise", "arguments": {"promise": "One honest report", "due_date": (times.now() + timedelta(days=2)).date().isoformat()}},
    ]


def auditor_steps(session):
    arguments = {"rubric": "false-statement", "summary": "s", "evidence": "e", "audited_session": session}
    return [{"do": "reply", "request": "audit-1", "output": 1, "text": "Read."}, {"do": "tool", "name": "record_finding", "arguments": arguments}]


class Walk:
    """Stands where Daniel does: what each placeholder is by then, and what each session does when it starts."""

    def __init__(self, stub):
        self.stub = stub
        self.preflights = 0

    def _last(self, role, field):
        return next(event[field] for event in reversed(events("session-started")) if event["role"] == role)

    def filled(self, command):
        now = times.now()
        values = {
            "<monthly price>": "130",
            "<plan>": "a-plan",
            "<percent>": "40",
            "<reset time>": times.stamp(now + timedelta(hours=4 if "five_hour" in command else 72)),
            "<Discord id>": "1234",
            "<n>": "6",
            "<why>": "the walk's last step",
        }
        for name, value in values.items():
            command = command.replace(name, value)
        if "<run>" in command:
            command = command.replace("<run>", self._last("probe", "run"))
        if "<cell run>" in command:
            command = command.replace("<cell run>", self._last("cell", "run"))
        if "<promise>" in command:
            command = command.replace("<promise>", str(events("promise-recorded")[-1]["seq"]))
        if "<finding>" in command:
            command = command.replace("<finding>", str(events("finding")[-1]["seq"]))
        assert "<" not in command, command
        return command

    def before(self, command):
        """What happens between commands: Daniel's editor, and the script of the session about to start."""
        if command.startswith("company settings init"):
            paths.paper_key().write_text("PKDECOY\nsecret-decoy\n")
        if command == "company session probe":
            self.stub.play({"do": "reply", "request": "probe-1", "output": 1, "text": "words"}, {"do": "probe-actions"})
        if command == "company session probe --kill-test":
            self.stub.play({"do": "tool", "name": "note", "arguments": {"text": "PROBE waiting"}}, {"do": "wait-as-told"}, {"do": "hang"})
        if command.startswith("company session start cell"):
            self.stub.play(*cell_steps())
        if command.startswith("company audit"):
            self.stub.play(*auditor_steps(self._last("cell", "session")))

    def stdin(self, command):
        """What Claude Code gives a status line, in the documented fields."""
        if command != "company reading statusline":
            return ""
        return json.dumps({"rate_limits": {"seven_day": {"used_percentage": 40, "resets_at": int((times.now() + timedelta(hours=72)).timestamp())}}})

    def exit_expected(self, command):
        if command == "company preflight":
            self.preflights += 1
            return 1 if self.preflights == 1 else 0
        return 0


def test_each_command_runs_in_order_on_the_stub(stub, systemctl, tmp_path, monkeypatch, capsys, transcripts):
    installed = tmp_path / "tool-bin"
    home = tmp_path / "daniels-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("COMPANY_HOME")
    monkeypatch.delenv("COMPANY_CONFIG")
    # Where the walk's commands would otherwise have a reading with no weight behind it, once a session has replied.
    transcripts.session(TEAM, transcript_line(TEAM, "team-1", (times.now() - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S.000Z"), output=50_000_000))
    environment = {
        **os.environ,
        "PATH": f"{installed}{os.pathsep}{os.environ['PATH']}",
        "UV_OFFLINE": "1",
        "UV_TOOL_DIR": str(tmp_path / "tools"),
        "UV_TOOL_BIN_DIR": str(installed),
    }
    walk = Walk(stub)
    ran = []
    for written, see in blocks():
        walk.before(written)
        command = walk.filled(written)
        ran.append(written)
        if written == "company paper check":
            monkeypatch.setattr(paper, "transport", FakeBroker)
            capsys.readouterr()
            code = cli.main(["paper", "check"])
            captured = capsys.readouterr()
            output = captured.out + captured.err
        else:
            cwd = REPO if written.startswith("uv tool") else tmp_path
            done = subprocess.run(["/bin/bash", "-c", command], env=environment, cwd=cwd, input=walk.stdin(written), capture_output=True, text=True, timeout=180, check=False)
            code, output = done.returncode, done.stdout + done.stderr
        assert code == walk.exit_expected(written), f"{command}\n{output}"
        for fragment in see:
            assert fragment in output, f"{command} did not show {fragment}:\n{output}"
    # The walk reached the end, on the code it installed, whose data files the sessions and the ledger read.
    assert ran[-1] == "company resume"
    assert shutil.which("company", path=str(installed))
    assert (tmp_path / "tools/agent-company").is_dir()
    assert paths.home() == home / ".local/state/agent-company"
    assert {event["role"] for event in events("session-started")} == {"probe", "cell", "auditor"}
