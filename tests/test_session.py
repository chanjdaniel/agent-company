"""`company session start`: one whole session path on the stub `claude`, through the real company tools.

Each test runs the installed command on the real clock, and reads the ledger and what the stub saw.
Weights: a reply of 5,000,000 output tokens on Opus weighs 100, as `usage_records` says, so 50,000 weighs 1.
"""

import ast
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from session_checks import (
    events,
    patch_every_company,
    pid_is_running,
    run_file_fails,
    wait_for,
)
from test_suite_guard import run_child_suite
from usage_records import (
    SETTINGS_INIT,
    TEAM,
    record_reading,
    start_session,
    transcript_line,
    week_reading,
)

from company import banned, goals, launcher, paths
from company.ledger import Ledger

CONFIG_NAMES = (".claude", ".mcp.json", "CLAUDE.md", "CLAUDE.local.md")
# Assembled, since the scan rightly finds these words in any file of ours.
KEY_HELPER = "apiKey" + "Helper"
BARE = "--" + "bare"


def stamp(when):
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def kinds():
    return [event["kind"] for event in events()]


@pytest.fixture
def session(company, stub, board):
    """`company session start`."""

    def run(role="probe", *more):
        return company("session", "start", role, *more)

    return run


def only(kind):
    found = events(kind)
    assert len(found) == 1, found
    return found[0]


def workspace(name="ws"):
    path = paths.workspaces() / name
    path.mkdir(parents=True)
    return path


# The whole path


def test_a_session_starts_writes_its_note_through_the_tools_and_ends(session, stub):
    stub.play({"do": "tool", "name": "note", "arguments": {"text": "hello"}}, {"do": "reply", "request": "r1", "output": 50_000})

    done = session("probe", "--prompt", "say hello")

    assert done.returncode == 0, done.stdout + done.stderr
    assert kinds()[-3:] == ["session-started", "session-note", "session-ended"]
    started, note, ended = events("session-started")[-1], only("session-note"), only("session-ended")
    assert note["writer"] == "probe"
    assert note["text"] == "hello"
    assert note["session"] == started["session"] == ended["session"] == stub.argument("--session-id")
    assert started["writer"] == ended["writer"] == "launcher"
    assert started["session"] in done.stdout
    assert Ledger().verify().ok


def test_a_session_uses_one_launch_of_the_go_word(session, company, stub):
    assert session().returncode == 0
    assert events("session-started")[-1]["gate"] == f"go:{only('go-given')['seq']}"
    assert "9 real launches left" in company("governor", "check", "probe").stdout


def test_the_session_is_given_its_goal_and_task_on_stdin_with_every_flag_before_it(session, stub):
    session("probe", "--prompt", "THE TASK")

    call = stub.session_calls()[-1]
    assert "The probe's goal" in call["stdin"]
    assert "THE TASK" in call["stdin"]
    assert "THE TASK" not in " ".join(call["argv"])


def test_the_session_runs_in_a_fresh_workspace_and_its_own_process_group(session, stub):
    stub.play({"do": "children", "count": 1})
    session()

    cwd = stub.session_calls()[-1]["cwd"]
    assert Path(cwd).parent == paths.workspaces().resolve()
    started = events("session-started")[-1]
    state = json.loads((paths.runs() / started["run"] / "session.json").read_text())
    assert state["group"] != os.getpgid(0)


def test_the_session_is_started_with_the_flags_the_design_names(session, stub):
    session()

    argv = stub.session_calls()[-1]["argv"]
    assert argv[0] == "-p"
    assert stub.argument("--output-format") == "stream-json"
    assert "--verbose" in argv
    assert stub.argument("--permission-mode") == "dontAsk"
    assert stub.argument("--model") == launcher.PROBE_MODEL
    assert stub.argument("--tools") == "Read,Edit,Write,Glob,Grep,Bash"
    assert stub.argument("--allowedTools") == "Read,Edit,Write,Glob,Grep,Bash,mcp__company__note"
    assert stub.settings()
    assert stub.mcp_config()


def test_each_role_gets_its_own_tools_and_never_the_agent_tool(session, stub):
    for role, more in (("cell", ("--bet", "alpha")), ("strategy", ()), ("auditor", ()), ("retro", ())):
        assert session(role, *more).returncode == 0
        for flag in ("--tools", "--allowedTools"):
            assert "Agent" not in stub.argument(flag)
            assert "Task" not in stub.argument(flag)
    assert stub.argument("--tools") == "Read,Glob,Grep"


@pytest.mark.parametrize(("role", "more", "setting"), [("cell", ("--bet", "alpha"), "claude-opus-5-5"), ("auditor", (), "claude-sonnet-5-5")])
def test_a_role_runs_on_its_model_from_the_settings(session, stub, role, more, setting):
    assert session(role, *more).returncode == 0
    assert stub.argument("--model") == setting
    assert events("session-started")[-1]["model"] == setting


# A refused launch


def test_a_launch_the_governor_refuses_starts_nothing_and_says_why(company, stub):
    done = company("session", "start", "probe")

    assert done.returncode == 1
    assert "Refused at the settings check" in done.stdout
    assert stub.calls() == []
    assert "session-started" not in kinds()
    assert only("launch-refused")["writer"] == "governor"


def test_a_launch_past_the_go_word_starts_nothing(company, stub):
    assert company(*SETTINGS_INIT).returncode == 0
    assert company("go", "real-sessions", "--message", "1", "--sessions", "1").returncode == 0
    week_reading()
    assert company("session", "start", "probe").returncode == 0
    calls = len(stub.calls())

    done = company("session", "start", "probe")

    assert done.returncode == 1
    assert "go-used-up" in done.stdout
    assert len(stub.calls()) == calls


def test_two_launches_at_once_cannot_both_spend_a_words_last_launch(company, stub, tmp_path):
    assert company(*SETTINGS_INIT).returncode == 0
    assert company("go", "real-sessions", "--message", "1", "--sessions", "1").returncode == 0
    week_reading()
    stub.play({"do": "hang", "seconds": 1})
    script = Path(sys.executable).parent / "company"

    both = [subprocess.Popen([script, "session", "start", "probe"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
    codes = sorted(process.wait(timeout=60) for process in both)
    for process in both:
        process.stdout.close()
        process.stderr.close()

    assert codes == [0, 1]
    assert len(events("session-started")) == 1


# The environment


def test_the_child_holds_only_allow_listed_variables(company, stub, board, monkeypatch):
    for name in banned.VARIABLES:
        monkeypatch.setenv(name, "x")
    monkeypatch.setenv("SOME_UNKNOWN_VARIABLE", "x")
    monkeypatch.setenv("COMPANY_SECRET_THING", "x")

    done = company("session", "start", "probe")
    assert done.returncode == 0, done.stdout + done.stderr

    seen = stub.environment()
    allowed = {*launcher.ALLOWED_ENVIRONMENT, "PATH", launcher.SESSION_VARIABLE, "CLAUDE_CODE_DISABLE_CLAUDE_MDS", "CLAUDE_CODE_DISABLE_AUTO_MEMORY"}
    assert set(seen) <= allowed | {"_", "PWD", "OLDPWD", "SHLVL"}
    for name in banned.VARIABLES:
        assert name not in seen
    assert "SOME_UNKNOWN_VARIABLE" not in seen
    assert "COMPANY_SECRET_THING" not in seen
    assert "COMPANY_HOME" not in seen
    assert "COMPANY_CONFIG" not in seen
    assert launcher.BINARY_VARIABLE not in seen


def test_the_allow_list_strips_the_suites_guard_and_fixes_the_path(session, stub):
    session()

    seen = stub.environment()
    assert "PYTHONPATH" not in seen
    assert "COMPANY_TEST_GUARD" not in seen
    assert seen["PATH"] == launcher.CHILD_PATH


def test_no_allow_listed_variable_is_a_banned_one():
    assert [name for name in launcher.ALLOWED_ENVIRONMENT if banned.is_banned(name)] == []


def test_every_banned_variable_is_banned_at_run_time_and_so_are_others_of_their_kind():
    assert all(banned.is_banned(name) for name in banned.VARIABLES)
    assert banned.is_banned("ANTHROPIC_PROFILE")
    assert not banned.is_banned("HOME")


def test_a_banned_variable_that_joined_the_allow_list_would_still_be_stripped(monkeypatch):
    name = banned.VARIABLES[0]
    monkeypatch.setenv(name, "x")
    monkeypatch.setattr(launcher, "ALLOWED_ENVIRONMENT", (*launcher.ALLOWED_ENVIRONMENT, name))

    assert name not in launcher.child_environment()


def test_the_module_of_banned_variables_is_one_of_the_scans_own_files():
    from scan_rules import SCAN_FILES

    assert "src/company/banned.py" in SCAN_FILES


# The guard reaches the stub and the company tools


GUARDED_SESSION = """
import os, subprocess, sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import stub_session

COMPANY = Path(sys.executable).parent / "company"


def company(*args):
    done = subprocess.run([COMPANY, *args], capture_output=True, text=True, timeout=60)
    print(done.stdout, done.stderr)
    return done


def test_it(tmp_path):
    stub = stub_session.Stub(tmp_path / "stub")
    stub.play(STEP)
    os.environ["COMPANY_CLAUDE_BIN"] = str(stub.binary)
    company("settings", "init", "--company-share", "0.25", "--team-floor", "60", "--monthly-price", "130",
            "--plan-name", "p", "--reading-max-age-minutes", "120", "--session-max-minutes", "60",
            "--session-max-weight", "20")
    company("go", "real-sessions", "--message", "1", "--sessions", "1")
    resets = (datetime.now(UTC) + timedelta(hours=72)).strftime("%Y-%m-%dT%H:%M:%SZ")
    company("reading", "record", "--window", "seven_day", "--used-percent", "40", "--resets-at", resets)
    assert company("session", "start", "probe").returncode == 0
"""


def guarded(tmp_path, step):
    return run_child_suite(tmp_path, GUARDED_SESSION.replace("STEP", repr(step)))


def test_a_network_attempt_from_the_stub_fails_the_test(tmp_path):
    done = guarded(tmp_path, {"do": "network"})
    assert done.returncode == 1, done.stdout + done.stderr
    assert "the suite's guard caught this, in this test or just before it: network" in done.stdout


def test_a_claude_started_inside_the_stub_hits_the_blocker(tmp_path):
    done = guarded(tmp_path, {"do": "run", "command": ["claude", "-p", "again"]})
    assert done.returncode == 1, done.stdout + done.stderr
    assert "model: a test ran claude" in done.stdout


def test_a_quiet_stub_session_passes_under_the_guard(tmp_path):
    done = guarded(tmp_path, {"do": "tool", "name": "note", "arguments": {"text": "fine"}})
    assert done.returncode == 0, done.stdout + done.stderr


def test_a_launch_with_no_stub_chosen_hits_the_blocker_and_starts_nothing(tmp_path):
    source = GUARDED_SESSION.replace("STEP", "{}").replace('os.environ["COMPANY_CLAUDE_BIN"] = str(stub.binary)', "pass").replace(
        'assert company("session", "start", "probe").returncode == 0', 'assert company("session", "start", "probe").returncode == 1'
    )
    done = run_child_suite(tmp_path, source)
    assert done.returncode == 1, done.stdout + done.stderr
    assert "model: a test ran claude --help" in done.stdout


def test_the_launcher_finds_the_blocker_first_on_its_path(monkeypatch):
    monkeypatch.delenv(launcher.BINARY_VARIABLE, raising=False)
    assert launcher.binary() == shutil.which("claude")
    assert "company-suite-" in launcher.binary()


# The generated settings


def test_the_settings_fail_closed_on_the_sandbox(session, stub):
    session()

    sandbox = stub.settings()["sandbox"]
    assert sandbox["enabled"] is True
    assert sandbox["failIfUnavailable"] is True
    assert sandbox["allowUnsandboxedCommands"] is False


def test_the_settings_allow_no_network_host(session, stub):
    session()

    network = stub.settings()["sandbox"]["network"]
    assert network["allowedDomains"] == []
    assert network["strictAllowlist"] is True


def test_the_sandbox_denies_reading_outside_the_workspace_and_allows_it(session, stub):
    session()

    filesystem = stub.settings()["sandbox"]["filesystem"]
    workspace_path = stub.session_calls()[-1]["cwd"]
    assert filesystem["allowRead"] == [workspace_path]
    assert "~/" in filesystem["denyRead"]
    for root in (paths.home(), paths.config(), paths.claude_directory()):
        assert str(root) in filesystem["denyRead"]


def test_the_sandbox_gives_no_write_beyond_its_working_directory(session, stub):
    session()

    filesystem = stub.settings()["sandbox"]["filesystem"]
    assert "allowWrite" not in filesystem
    for root in (paths.config(), paths.claude_directory()):
        assert str(root) in filesystem["denyWrite"]


def test_the_permission_rules_refuse_the_file_tools_outside_the_workspace(session, stub):
    session()

    permissions = stub.settings()["permissions"]
    assert permissions["blockReadsOutsideWorkingDirectories"] is True
    assert permissions["blockWritesOutsideWorkingDirectories"] is True


@pytest.mark.parametrize("tool", ["Read", "Edit"])
def test_the_permission_rules_name_what_matters_most(session, stub, tool):
    session()

    deny = stub.settings()["permissions"]["deny"]
    for root in (paths.config(), paths.claude_directory(), paths.runs()):
        assert f"{tool}(//{str(root).lstrip('/')}/**)" in deny
    assert f"{tool}(//{str(paths.home() / 'ledger*').lstrip('/')})" in deny


def test_no_permission_rule_is_of_a_form_that_never_matches(session, stub):
    # The permission docs say a path rule for this tool is accepted and never matched: `Edit` rules cover it.
    session()

    assert not [rule for rule in stub.settings()["permissions"]["deny"] if rule.startswith("Write(")]


def test_the_settings_hold_no_key_helper_hook_or_status_line(session, stub):
    session()

    def keys(value):
        if isinstance(value, dict):
            for key, inner in value.items():
                yield key
                yield from keys(inner)
        elif isinstance(value, list):
            for inner in value:
                yield from keys(inner)

    found = set(keys(stub.settings()))
    assert KEY_HELPER not in found
    assert "hooks" not in found
    assert "statusLine" not in found
    assert stub.settings()["disableAllHooks"] is True


@pytest.mark.parametrize("role", ["probe", "auditor"])
def test_the_launch_never_passes_bare_mode(session, stub, role):
    session(role)

    for call in stub.calls():
        assert BARE not in call["argv"]
    assert "CLAUDE_CODE_SIMPLE" not in stub.environment()


@pytest.mark.parametrize("name", CONFIG_NAMES)
def test_the_settings_deny_writing_each_configuration_path_at_any_depth(session, stub, name):
    session()

    settings = stub.settings()
    workspace_path = stub.session_calls()[-1]["cwd"]
    assert f"Edit(//{workspace_path.lstrip('/')}/**/{name})" in settings["permissions"]["deny"]
    # On Linux a sandbox write rule takes no wildcard but a trailing one, so it can name only the top of the workspace.
    assert f"{workspace_path}/{name}" in settings["sandbox"]["filesystem"]["denyWrite"]


def test_no_sandbox_write_rule_holds_a_wildcard_that_does_nothing_on_linux(session, stub):
    session()

    for path in stub.settings()["sandbox"]["filesystem"]["denyWrite"]:
        assert not set(path.removesuffix("/**")) & set("*?"), path


def test_what_a_session_wrote_deep_in_its_workspace_refuses_the_next_session_there(session, stub):
    # The sandbox cannot deny the shell this at depth on Linux, so this refusal is what keeps it from a later session.
    root = workspace()
    write = f"import pathlib; p = pathlib.Path({str(root / 'deep/er')!r}); p.mkdir(parents=True); (p / 'CLAUDE.md').write_text('x')"
    stub.play({"do": "run", "command": [sys.executable, "-c", write]})
    assert session("probe", "--workspace", str(root)).returncode == 0
    stub.play()

    done = session("probe", "--workspace", str(root))

    assert done.returncode == 1
    assert only("launch-refused")["check"] == "workspace"
    assert "deep/er/CLAUDE.md" in done.stdout


def test_the_settings_deny_writing_inside_a_claude_directory(session, stub):
    session()

    workspace_path = stub.session_calls()[-1]["cwd"].lstrip("/")
    assert f"Edit(//{workspace_path}/**/.claude/**)" in stub.settings()["permissions"]["deny"]


# What a session loads


def test_the_launch_passes_the_form_that_loads_nothing(session, stub):
    session()

    argv = stub.session_calls()[-1]["argv"]
    for flag in ("--restricted", "--strict-mcp-config", "--disable-slash-commands", "--tools"):
        assert flag in argv
    seen = stub.environment()
    assert seen["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"
    assert seen["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
    settings = stub.settings()
    assert settings["enabledPlugins"] == {}
    assert settings["autoMemoryEnabled"] is False
    assert settings["syncClaudeAiSkills"] is False
    assert settings["syncClaudeAiPlugins"] is False
    assert settings["disableClaudeAiConnectors"] is True


def test_the_launch_never_names_a_setting_source(session, stub):
    # The docs advise `--setting-sources user`, which would load what the design keeps out.
    session()

    assert "--setting-sources" not in stub.session_calls()[-1]["argv"]


@pytest.mark.parametrize("flag", launcher.FORM_FLAGS)
def test_a_claude_with_no_such_flag_starts_nothing_and_falls_back_to_nothing(session, stub, flag):
    stub.play(help_lacks=[flag])

    done = session()

    assert done.returncode == 1
    assert "load-form" in done.stdout
    assert flag in done.stdout
    assert stub.session_calls() == []
    event = only("launch-refused")
    assert event["writer"] == "launcher"
    assert event["check"] == "load-form"
    assert event["reason"].startswith("no-load-form")
    assert "session-started" not in kinds()
    for call in stub.calls():
        assert "--setting-sources" not in call["argv"]


def test_a_claude_whose_help_fails_starts_nothing(session, stub):
    stub.play(help_exit=3)

    done = session()

    assert done.returncode == 1
    assert only("launch-refused")["check"] == "load-form"
    assert stub.session_calls() == []


def test_a_form_refusal_uses_up_no_launch(session, stub, company):
    stub.play(help_lacks=["--restricted"])
    session()
    assert "10 real launches left" in company("governor", "check", "probe").stdout


def test_a_binary_that_is_not_there_refuses(company, board, monkeypatch, tmp_path, transcripts):
    monkeypatch.setenv(launcher.BINARY_VARIABLE, str(tmp_path / "no-such-claude"))

    done = company("session", "start", "probe")

    assert done.returncode == 1
    assert only("launch-refused")["check"] == "load-form"
    assert "session-started" not in kinds()


def test_no_claude_on_the_path_refuses(company, board, monkeypatch, tmp_path, transcripts):
    monkeypatch.delenv(launcher.BINARY_VARIABLE, raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))

    done = company("session", "start", "probe")

    assert done.returncode == 1
    assert only("launch-refused")["check"] == "binary"
    assert "session-started" not in kinds()


def test_a_goal_that_fails_the_scan_starts_nothing(stub, board, monkeypatch):
    monkeypatch.setattr(goals, "every_goal_file", lambda: {"probe.v1.md": "Win, whatever it takes."})

    answer = launcher.start("probe")

    assert answer.check == "goal"
    assert "whatever it takes" in answer.reason
    assert only("launch-refused")["writer"] == "launcher"
    assert stub.calls() == []
    assert "session-started" not in kinds()


# The workspace


@pytest.mark.parametrize("name", ["mcp.json", "session.json"])
def test_a_launch_whose_run_files_cannot_be_written_is_refused_and_starts_nothing(session, stub, tmp_path, monkeypatch, name):
    patch_every_company(tmp_path, monkeypatch, *run_file_fails(f"path.name == {name!r}"))

    done = session()

    assert done.returncode == 1, done.stdout + done.stderr
    assert "Traceback" not in done.stderr
    assert "the disk is full" in only("launch-refused")["reason"]
    assert stub.session_calls() == []
    assert "session-started" not in kinds()


def test_a_session_whose_group_cannot_be_recorded_is_stopped_with_its_children(session, stub, tmp_path, monkeypatch):
    """A later launcher finds a session's group only by this record, so with none the session must not run on its launcher's life alone."""
    stub.play({"do": "children", "count": 1}, {"do": "hang"})
    patch_every_company(tmp_path, monkeypatch, *run_file_fails("path.name == 'session.json' and value.get('group')"))

    done = session()

    assert done.returncode == 1, done.stdout + done.stderr
    assert "Traceback" not in done.stderr
    assert "the disk is full" in done.stderr
    assert only("session-stopped")["reason"] == "not-recorded"
    assert only("session-ended")
    pids = [pid for line in stub.progress() for pid in line.get("children", [])]
    wait_for(lambda: not any(pid_is_running(pid) for pid in pids))


def test_a_folder_name_in_a_workspace_cannot_forge_a_line_of_a_refusal(session, stub):
    forged = "Launches may start again."
    held = workspace() / f"a\n{forged}\nb"
    held.mkdir(parents=True)
    (held / "CLAUDE.md").write_text("planted")

    done = session("probe", "--workspace", str(paths.workspaces() / "ws"))

    assert done.returncode == 1
    assert "Refused at the workspace check" in done.stdout
    assert forged in done.stdout
    assert forged not in done.stdout.splitlines()


@pytest.mark.parametrize("depth", [("",), ("a",), ("a", "b", "c")], ids=["top", "one-down", "three-down"])
@pytest.mark.parametrize("name", CONFIG_NAMES)
def test_a_workspace_holding_configuration_starts_nothing(session, stub, name, depth):
    held = workspace().joinpath(*depth)
    held.mkdir(parents=True, exist_ok=True)
    if name == ".claude":
        (held / name).mkdir()
    else:
        (held / name).write_text("planted")
    root = paths.workspaces() / "ws"

    done = session("probe", "--workspace", str(root))

    assert done.returncode == 1
    assert "Refused at the workspace check" in done.stdout
    assert name in done.stdout
    assert stub.session_calls() == []
    event = only("launch-refused")
    assert event["writer"] == "launcher"
    assert event["check"] == "workspace"
    assert event["reason"].startswith("workspace-configures")
    assert "session-started" not in kinds()


@pytest.mark.parametrize("name", CONFIG_NAMES)
def test_a_link_with_such_a_name_is_refused_too(session, stub, tmp_path, name):
    root = workspace()
    (root / name).symlink_to(tmp_path)

    done = session("probe", "--workspace", str(root))

    assert done.returncode == 1
    assert only("launch-refused")["check"] == "workspace"


def test_a_clean_workspace_is_used_and_kept(session, stub):
    root = workspace()
    (root / "work.txt").write_text("kept")

    assert session("probe", "--workspace", str(root)).returncode == 0

    assert stub.session_calls()[-1]["cwd"] == str(root.resolve())
    assert (root / "work.txt").read_text() == "kept"


@pytest.mark.parametrize("where", ["outside", "the-root", "missing"])
def test_a_workspace_elsewhere_is_refused(session, stub, tmp_path, where):
    paths.workspaces().mkdir(parents=True)
    chosen = {"outside": tmp_path, "the-root": paths.workspaces(), "missing": paths.workspaces() / "none"}[where]

    done = session("probe", "--workspace", str(chosen))

    assert done.returncode == 1
    assert only("launch-refused")["reason"].startswith("not-a-workspace")
    assert stub.session_calls() == []


# The company tools


def test_a_session_naming_another_writer_still_writes_as_its_own(session, stub):
    stub.play({"do": "tool", "name": "note", "arguments": {"text": "mine", "writer": "treasurer", "session": TEAM, "kind": "revenue"}})

    assert session("cell", "--bet", "alpha").returncode == 0

    note = only("session-note")
    assert note["writer"] == "cell:alpha"
    assert note["session"] == stub.argument("--session-id")
    assert "revenue" not in kinds()


def test_each_server_is_started_with_what_the_launcher_fixed(session, stub):
    assert session("cell", "--bet", "alpha").returncode == 0

    server = stub.mcp_config()["mcpServers"]["company"]
    arguments = server["args"]
    assert arguments[arguments.index("--role") + 1] == "cell"
    assert arguments[arguments.index("--bet") + 1] == "alpha"
    assert arguments[arguments.index("--session") + 1] == stub.argument("--session-id")
    assert server["env"] == {"COMPANY_HOME": str(paths.home()), "COMPANY_SESSION": stub.argument("--session-id")}


def test_a_tool_outside_the_role_is_refused_and_logged_with_its_session_and_tool(session, stub):
    stub.play({"do": "tool", "name": "note", "arguments": {"text": "not mine"}})

    assert session("strategy").returncode == 0

    assert "session-note" not in kinds()
    event = only("append-refused")
    assert event["attempted_kind"] == "session-note"
    assert event["attempted_writer"] == "strategy"
    assert event["reason"] == "tool-not-in-role"
    assert event["tool"] == "note"
    assert event["session"] == stub.argument("--session-id")
    assert event["writer"] == "treasurer"
    assert stub.tool_results()[-1]["result"]["isError"] is True
    assert f"event {event['seq']}" in stub.tool_results()[-1]["result"]["content"][0]["text"]


def test_a_tool_that_does_not_exist_is_refused_and_logged(session, stub):
    stub.play({"do": "tool", "name": "pay-me", "arguments": {}})

    assert session().returncode == 0

    event = only("append-refused")
    assert event["reason"] == "unknown-tool"
    assert event["tool"] == "pay-me"
    assert event["session"] == stub.argument("--session-id")


def test_a_tool_name_that_is_no_name_is_not_logged_as_it_stands(session, stub):
    stub.play({"do": "tool", "name": "A secret value!", "arguments": {}})

    assert session().returncode == 0

    assert only("append-refused")["tool"] == "<not-a-name>"


@pytest.mark.parametrize("arguments", [{}, {"text": ""}, {"text": 5}])
def test_a_note_with_no_text_is_refused_and_logged(session, stub, arguments):
    stub.play({"do": "tool", "name": "note", "arguments": arguments})

    assert session().returncode == 0

    assert "session-note" not in kinds()
    assert only("append-refused")["reason"] == "bad-arguments"


def test_a_role_lists_only_its_own_tools(session, stub):
    stub.play({"do": "list-tools"})
    assert session("probe").returncode == 0
    assert [tool["name"] for tool in stub.tool_lists()[-1]["result"]["tools"]] == ["note"]

    assert session("strategy").returncode == 0
    assert stub.tool_lists()[-1]["result"]["tools"] == []


def test_a_file_planted_in_the_workspace_cannot_run_as_the_company_tools(session, stub, tmp_path):
    # The server starts in the workspace, outside the sandbox, so a module there must not shadow the package's.
    root = workspace()
    marker = tmp_path / "planted-ran"
    planted = f"open({str(marker)!r}, 'w').close()\n"
    (root / "company").mkdir()
    (root / "company" / "__init__.py").write_text(planted)
    (root / "company" / "tools.py").write_text(planted)
    (root / "json.py").write_text(planted)
    stub.play({"do": "tool", "name": "note", "arguments": {"text": "real"}})

    assert session("probe", "--workspace", str(root)).returncode == 0

    assert not marker.exists()
    assert only("session-note")["text"] == "real"


def test_the_command_refuses_an_agent_that_tries_it_inside_a_session(session, stub, company_home):
    # A real session's shell cannot write the company home at all, which the probe proves; this is the second layer.
    command = [str(Path(sys.executable).parent / "company"), "ledger", "append", "revenue", "--writer", "treasurer", "--fields",
               json.dumps({"amount": "1.00", "currency": "USD", "source": "s", "record": "r"})]  # fmt: skip
    stub.play({"do": "run", "command": command, "env": {"COMPANY_HOME": str(company_home)}})

    assert session().returncode == 0

    assert stub.runs()[-1]["exit"] == 1
    assert "only through its company tools" in stub.runs()[-1]["stderr"]
    assert "revenue" not in kinds()
    event = only("append-refused")
    assert event["reason"] == "inside-a-session"
    assert event["attempted_kind"] == "revenue"
    assert event["attempted_writer"] == "treasurer"
    assert event["writer"] == "treasurer"
    assert event["tool"] == "ledger-append"
    assert event["session"] == stub.argument("--session-id")


def test_the_company_command_is_not_on_a_sessions_path(session, stub):
    # The stub's wrapper puts only the blocker's directory back, so this reads what the launcher gave.
    session()

    assert str(Path(sys.executable).parent) not in stub.environment()["PATH"]


def test_the_settings_deny_the_shell_the_company_and_claude_commands(session, stub):
    session()

    deny = stub.settings()["permissions"]["deny"]
    assert "Bash(company *)" in deny
    assert "Bash(claude *)" in deny


# The limits


def test_a_session_past_its_time_is_stopped_with_its_children(session, stub, company):
    assert company("settings", "set", "session_max_minutes", "0.02").returncode == 0
    stub.play({"do": "children", "count": 2}, {"do": "hang"})

    done = session()

    assert done.returncode == 1
    assert "max-minutes" in done.stdout
    stopped = only("session-stopped")
    assert stopped["reason"] == "max-minutes"
    assert stopped["session"] == stub.argument("--session-id")
    assert 0.015 < stopped["elapsed_minutes"] < 0.2
    assert "session-ended" in kinds()
    pids = next(line["children"] for line in stub.progress() if "children" in line)
    wait_for(lambda: not any(pid_is_running(pid) for pid in pids))


@pytest.mark.parametrize("where", ["output", "transcript"])
def test_a_session_past_its_weight_is_stopped_mid_way(session, stub, company, where):
    assert company("settings", "set", "session_max_weight", "2").returncode == 0
    stub.play({"do": "reply", "request": "r1", "output": 50_000, "where": where}, {"do": "reply", "request": "r2", "output": 150_000, "where": where}, {"do": "hang"}, {"do": "print", "text": "never-reached"})

    done = session()

    assert done.returncode == 1
    stopped = only("session-stopped")
    assert stopped["reason"] == "max-weight"
    assert stopped["weight"] == pytest.approx(4.0)
    assert only("session-ended")["weight"] == pytest.approx(4.0)
    assert any("hanging" in line for line in stub.progress())


def test_a_session_under_its_limits_is_not_stopped(session, stub):
    stub.play({"do": "reply", "request": "r1", "output": 50_000})

    assert session().returncode == 0
    assert "session-stopped" not in kinds()


def test_a_session_that_ignores_the_stop_signal_is_killed(session, stub, company):
    assert company("settings", "set", "session_max_minutes", "0.01").returncode == 0
    stub.play({"do": "ignore-term"}, {"do": "hang"})

    done = session()

    assert done.returncode == 1
    assert only("session-stopped")["reason"] == "max-minutes"
    assert only("session-ended")["exit"] == -signal.SIGKILL
    pid = next(line["hanging"] for line in stub.progress() if "hanging" in line)
    wait_for(lambda: not pid_is_running(pid))


def test_a_child_left_behind_by_a_finished_session_is_stopped(session, stub):
    stub.play({"do": "children", "count": 1})

    assert session().returncode == 0

    pid = next(line["children"] for line in stub.progress() if "children" in line)[0]
    wait_for(lambda: not pid_is_running(pid))


def test_a_signal_to_the_launcher_stops_the_session_and_logs_it(company, stub, board):
    stub.play({"do": "children", "count": 1}, {"do": "hang"})
    script = Path(sys.executable).parent / "company"
    launch = subprocess.Popen([script, "session", "start", "probe"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    wait_for(lambda: any("hanging" in line for line in stub.progress()))

    launch.send_signal(signal.SIGINT)
    launch.communicate(timeout=30)

    assert launch.returncode == 1
    assert only("session-stopped")["reason"] == "launcher-signalled"
    assert "session-ended" in kinds()
    pid = next(line["children"] for line in stub.progress() if "children" in line)[0]
    wait_for(lambda: not pid_is_running(pid))


# The end of a session


def test_the_end_holds_the_exit_the_transcripts_hash_and_the_weight(session, stub):
    stub.play({"do": "reply", "request": "r1", "output": 50_000}, {"do": "reply", "request": "r2", "output": 100_000})

    assert session().returncode == 0

    ended = only("session-ended")
    assert ended["exit"] == 0
    assert ended["weight"] == pytest.approx(3.0)
    copy = Path(ended["transcript_path"])
    assert copy.is_relative_to(paths.home())
    assert ended["transcript_hash"] == hashlib.sha256(copy.read_bytes()).hexdigest()
    assert '"requestId": "r2"' in copy.read_text()


def test_the_copy_of_the_transcript_outlives_claude_codes_own(session, stub, transcripts):
    stub.play({"do": "reply", "request": "r1", "output": 50_000})
    assert session().returncode == 0
    ended = only("session-ended")

    for original in transcripts.projects.glob(f"*/{ended['session']}.jsonl"):
        original.unlink()

    assert Path(ended["transcript_path"]).exists()


def test_a_session_that_wrote_no_transcript_says_so(session, stub):
    assert session().returncode == 0

    ended = only("session-ended")
    assert ended["transcript_path"] == "none"
    assert ended["transcript_hash"] == "none"
    assert ended["weight"] == 0


def test_a_failing_session_has_its_exit_on_record(session, stub):
    stub.play({"do": "exit", "code": 7})

    done = session()

    assert done.returncode == 1
    assert only("session-ended")["exit"] == 7
    assert "exit 7" in done.stdout


def test_the_raw_output_and_what_was_passed_are_kept_in_the_run(session, stub):
    stub.play({"do": "print", "text": "a raw line"})

    assert session().returncode == 0

    run = paths.runs() / only("session-started")["run"]
    assert "a raw line" in (run / "output.jsonl").read_text()
    assert "The probe's goal" in (run / "prompt.txt").read_text()
    assert stub.argument("--settings") == str(run / "settings.json")
    assert stub.argument("--mcp-config") == str(run / "mcp.json")


def test_the_share_counts_this_session_as_the_companys(session, stub, company, transcripts):
    # The company's reply weighs 3 against the team's 1, so its fraction is 3/4 of the account's 40%: 30%.
    now = datetime.now(UTC) - timedelta(minutes=5)
    transcripts.session(TEAM, transcript_line(TEAM, "team-1", now.strftime("%Y-%m-%dT%H:%M:%S.000Z"), output=50_000))
    stub.play({"do": "reply", "request": "r1", "output": 150_000})
    assert session().returncode == 0
    week_reading()

    done = company("treasurer", "share")

    assert "company used 30.00%" in done.stdout, done.stdout


# A launcher that died


def test_a_session_whose_launcher_died_is_closed_before_the_next_starts(company, stub, board, transcripts):
    # The team's reply weighs 9 against this session's 1, so the company has used 4% of the week, under its share.
    earlier = datetime.now(UTC) - timedelta(minutes=5)
    transcripts.session(TEAM, transcript_line(TEAM, "team-1", earlier.strftime("%Y-%m-%dT%H:%M:%S.000Z"), output=450_000))
    stub.play({"do": "reply", "request": "r1", "output": 50_000}, {"do": "children", "count": 1}, {"do": "hang"})
    script = Path(sys.executable).parent / "company"
    launch = subprocess.Popen([script, "session", "start", "probe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wait_for(lambda: any("hanging" in line for line in stub.progress()))
    first = events("session-started")[-1]

    launch.kill()
    launch.wait()
    assert events("session-stopped") == []
    stub.play()

    assert company("session", "start", "probe").returncode == 0

    stopped = only("session-stopped")
    assert stopped["session"] == first["session"]
    assert stopped["reason"] == "launcher-gone"
    assert stopped["weight"] == pytest.approx(1.0)
    assert stopped["elapsed_minutes"] >= 0
    assert (paths.runs() / first["run"] / "transcript.jsonl").exists()
    second = events("session-started")[-1]
    assert second["session"] != first["session"]
    assert stopped["seq"] < second["seq"]
    # What it left running does not run on, since nothing watches its limits now.
    pids = [next(line["hanging"] for line in stub.progress() if "hanging" in line), next(line["children"] for line in stub.progress() if "children" in line)[0]]
    wait_for(lambda: not any(pid_is_running(pid) for pid in pids))


def test_a_process_group_whose_number_was_reused_is_left_alone(company, stub, board):
    # Its launcher is gone, and the number it recorded now belongs to something else, which it must not kill.
    other = subprocess.Popen(["/bin/sleep", "600"], start_new_session=True)
    try:
        start_session(TEAM, "probe", board)
        run_dir = paths.runs() / "run-1"
        run_dir.mkdir(parents=True)
        state = {"session": TEAM, "launcher": -1, "launcher_started": None, "group": other.pid, "group_started": 1}
        (run_dir / "session.json").write_text(json.dumps(state))

        assert company("session", "start", "probe").returncode == 0

        assert events("session-stopped")[0]["session"] == TEAM
        assert other.poll() is None
    finally:
        other.kill()
        other.wait()


def test_a_refused_launch_still_closes_a_session_that_has_gone(company, stub, board):
    start_session(TEAM, "probe", board)
    assert company("go", "real-sessions", "--message", "9", "--sessions", "1").returncode == 0
    assert company("settings", "set", "team_floor", "1").returncode == 0

    done = company("session", "start", "probe")

    assert done.returncode == 1
    assert only("session-stopped")["session"] == TEAM
    assert stub.calls() == []


def test_a_session_still_being_watched_is_left_alone(company, stub, board):
    stub.play({"do": "hang"})
    script = Path(sys.executable).parent / "company"
    launch = subprocess.Popen([script, "session", "start", "probe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wait_for(lambda: any("hanging" in line for line in stub.progress()))
    stub.play()

    assert company("session", "start", "probe").returncode == 0

    assert "session-stopped" not in kinds()
    assert launch.poll() is None
    launch.send_signal(signal.SIGTERM)
    launch.wait(timeout=30)
    assert only("session-stopped")["reason"] == "launcher-signalled"


def test_a_broken_ledger_refuses_and_closes_nothing(company, stub, board):
    start_session(TEAM, "probe", board)
    ledger = paths.home() / "ledger.jsonl"
    lines = ledger.read_text().splitlines(keepends=True)
    lines[1] = lines[1].replace('"sessions":10', '"sessions":99')
    ledger.write_text("".join(lines))

    done = company("session", "start", "probe")

    assert done.returncode == 1
    assert "Refused at the ledger check" in done.stdout
    assert stub.calls() == []
    assert "session-stopped" not in ledger.read_text()


def test_a_dead_launchers_windows_count_after_the_next_charge_and_closed_ones_stay_named(company, stub, board, transcripts):
    # The reading resets in 72 hours, so the open window opened 4 days ago, and the one before it 11 days ago.
    # The session started 6 days ago, in that closed window, and its launcher died.
    from ledger_history import ledger_at

    # Every time here comes from one `resets`, since the windows step from the newest reading's, to the second.
    now = datetime.now(UTC).replace(microsecond=0)
    resets = now + timedelta(hours=72)
    open_window = resets - timedelta(days=7)
    closed_window = open_window - timedelta(days=7)
    start_session(TEAM, "probe", board, ledger=ledger_at(stamp(now - timedelta(days=6))))
    stub.play({"do": "reply", "request": "r1", "output": 50_000})

    assert company("session", "start", "probe").returncode == 0
    assert only("session-stopped")["session"] == TEAM
    record_reading("seven_day", 40, stamp(resets), stamp(datetime.now(UTC)))
    done = company("treasurer", "charge")
    assert done.returncode == 0, done.stdout + done.stderr

    # Once the open window has closed, the charge counts it, and nothing charges the one before.
    after_reset = stamp(resets + timedelta(hours=1))
    page = company("digest", "--now", after_reset).stdout
    assert f"the window opening {stamp(closed_window)} holds a session" in page
    assert f"the window opening {stamp(open_window)} holds a session" not in page

    # Four windows on, the closed one has left the trailing month.
    later = stamp(resets + timedelta(days=7 * 4, hours=1))
    page = company("digest", "--now", later).stdout
    assert f"the window opening {stamp(closed_window)} holds a session" not in page


# The launcher is the only code that starts `claude`


SPAWNING = {
    "subprocess": {"run", "Popen", "call", "check_call", "check_output", "getoutput", "getstatusoutput"},
    "os": {"system", "popen", "posix_spawn", "posix_spawnp", "execv", "execve", "execvp", "execvpe", "execl", "execle", "execlp", "execlpe",
           "spawnv", "spawnve", "spawnvp", "spawnvpe", "spawnl", "spawnle", "spawnlp", "spawnlpe"},
    "asyncio": {"create_subprocess_exec", "create_subprocess_shell"},
    "pty": {"spawn"},
}  # fmt: skip
# Each of these starts a process of its own for a reason: `schedule.py` runs `systemctl`, `killswitch.py` its self-test, and `quant.py` the `bwrap` a strategy runs in.
SPAWNING_MODULES = frozenset({"launcher.py", "killswitch.py", "schedule.py", "quant.py"})
CLAUDE_MODULES = frozenset({"launcher.py"})


def starts_processes(source):
    """Whether this module's code can start a process at all."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import) and any(alias.name.split(".")[0] in ("subprocess", "pty", "multiprocessing") for alias in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in ("subprocess", "pty", "multiprocessing"):
            return True
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.attr in SPAWNING.get(node.value.id, ()):
            return True
    return False


def names_claude(source):
    """Whether this module's code names the `claude` binary, by its own name or the variable that chooses it."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and (node.value == "claude" or node.value.startswith("claude ") or node.value == launcher.BINARY_VARIABLE):
            return True
    return False


def scan_for_spawners(root):
    found = []
    for path in Path(root).rglob("*.py"):
        source = path.read_text()
        if (path.name not in SPAWNING_MODULES and starts_processes(source)) or (path.name not in CLAUDE_MODULES and names_claude(source)):
            found.append(path.name)
    return sorted(found)


def test_the_launcher_is_the_only_code_that_names_claude_and_only_these_start_a_process(repo):
    assert scan_for_spawners(repo / "src/company") == []


def test_a_module_that_may_start_a_process_still_may_not_name_claude(tmp_path):
    (tmp_path / "schedule.py").write_text("import subprocess\nsubprocess.run(['claude', '-p'])\n")
    assert scan_for_spawners(tmp_path) == ["schedule.py"]


@pytest.mark.parametrize(
    "planted",
    [
        "import subprocess\nsubprocess.run(['claude', '-p'])\n",
        "from subprocess import Popen\nPopen(['x'])\n",
        "import os\nos.execvp('claude', ['claude'])\n",
        "import os\nos.system('claude -p hello')\n",
        "import os\nos.posix_spawn('/bin/x', ['x'], {})\n",
        "import asyncio\nasyncio.create_subprocess_exec('x')\n",
        "import pty\npty.spawn('x')\n",
        "import shutil\nshutil.which('claude')\n",
    ],
)
def test_the_scan_for_other_code_that_starts_claude_catches_each_form(tmp_path, planted):
    (tmp_path / "planted.py").write_text(planted)
    assert scan_for_spawners(tmp_path) == ["planted.py"]

