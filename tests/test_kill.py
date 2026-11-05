"""`company kill` and `company resume`: everything stops at once, and nothing starts until Daniel says so.

Each test runs the installed command on the real clock, with the stub session and a stub `systemctl`.
"""

import contextlib
import fcntl
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from company import killswitch, launcher, paths, settings
from company.ledger import Ledger

COMPANY = Path(sys.executable).parent / "company"


def events(kind=None):
    found = Ledger().read()
    return found if kind is None else [event for event in found if event["kind"] == kind]


def wait_for(condition, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.02)
    raise AssertionError("it did not happen in time")


def pid_is_running(pid):
    try:
        text = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return False
    return text.rsplit(")", 1)[1].split()[0] != "Z"


def progress(stub, key):
    return next(line[key] for line in stub.progress() if key in line)


def hung_session(stub, *first_steps, role="probe"):
    """A session running in the background, hanging once it has started a child; the launcher's process."""
    stub.play(*first_steps, {"do": "children", "count": 2}, {"do": "hang"})
    launch = subprocess.Popen([COMPANY, "session", "start", role], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    wait_for(lambda: any("hanging" in line for line in stub.progress()))
    return launch


@pytest.fixture
def running(stub, board, systemctl):
    """One session running, and the processes it holds."""
    launch = hung_session(stub)
    yield launch
    if launch.poll() is None:
        launch.kill()
        launch.communicate()


def step(target):
    found = [event for event in events("kill-step") if event["target"] == target]
    assert len(found) == 1, found
    return found[0]


# The stop


def test_the_kill_switch_stops_a_running_session_and_its_children_mid_way(company, stub, running):
    done = company("kill", "--reason", "it looks wrong")

    assert done.returncode == 0, done.stdout + done.stderr
    pids = [progress(stub, "hanging"), *progress(stub, "children")]
    assert not any(pid_is_running(pid) for pid in pids)
    running.communicate(timeout=30)
    assert running.returncode == 1
    started = events("session-started")[-1]
    stopped = events("session-stopped")
    assert [event["session"] for event in stopped] == [started["session"]]
    assert stopped[0]["reason"] == "kill-switch"
    assert [event["session"] for event in events("session-ended")] == [started["session"]]


def test_the_ledger_says_who_pulled_it_and_each_steps_result(company, running):
    company("kill", "--reason", "it looks wrong")

    pulled = events("kill-pulled")
    assert len(pulled) == 1
    assert pulled[0]["by"] == "daniel"
    assert pulled[0]["reason"] == "it looks wrong"
    assert pulled[0]["writer"] == "killswitch"
    assert pulled[0]["ts"]
    assert "loop" not in pulled[0]
    session = events("session-started")[-1]["session"]
    assert step(session)["step"] == "stop-session"
    assert step(session)["result"] == "stopped"
    assert Ledger().verify().ok


def test_a_session_that_ignores_the_signal_is_killed(company, stub, board, systemctl):
    launch = hung_session(stub, {"do": "ignore-term"})

    assert company("kill").returncode == 0

    assert not pid_is_running(progress(stub, "hanging"))
    launch.communicate(timeout=30)


def test_a_frozen_launcher_does_not_keep_the_session_or_itself_alive(company, stub, board, systemctl):
    launch = hung_session(stub)
    launch.send_signal(signal.SIGSTOP)

    done = company("kill")

    assert done.returncode == 0, done.stdout + done.stderr
    assert not any(pid_is_running(pid) for pid in [progress(stub, "hanging"), *progress(stub, "children")])
    launch.communicate(timeout=30)
    assert launch.returncode == -signal.SIGKILL
    assert events("session-stopped")[-1]["reason"] == "launcher-gone"


def test_with_nothing_running_it_still_holds_every_launch(company, board):
    done = company("kill")

    assert done.returncode == 0, done.stdout + done.stderr
    assert company("governor", "check", "probe").returncode == 1
    assert events("kill-step") == [event for event in events("kill-step") if event["step"] == "schedule"]


def test_a_finished_session_is_not_counted_as_stopped(company, stub, board):
    stub.play()
    assert company("session", "start", "probe").returncode == 0

    assert company("kill").returncode == 0

    assert [event for event in events("kill-step") if event["step"] == "stop-session"] == []


def test_an_unrelated_process_group_recorded_long_ago_is_left_alone(company, stub, board):
    stub.play()
    assert company("session", "start", "probe").returncode == 0
    other = subprocess.Popen(["/bin/sleep", "600"], start_new_session=True)
    try:
        run = events("session-started")[-1]["run"]
        state = json.loads((paths.runs() / run / "session.json").read_text())
        (paths.runs() / run / "session.json").write_text(json.dumps({**state, "group": other.pid, "group_started": 1}))

        assert company("kill").returncode == 0

        assert other.poll() is None
    finally:
        other.kill()
        other.wait()


def test_a_launch_that_holds_its_lock_does_not_delay_the_rest_and_is_reported(company, board, systemctl, monkeypatch):
    assert company("schedule", "enable", "--message", "1234").returncode == 0
    set_accounts(company, "paper")
    key_of("paper").write_text("k")
    monkeypatch.setattr(killswitch, "_LAUNCH_WAIT_SECONDS", 0.2)
    fd = os.open(paths.home() / "launch.lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        pulled = killswitch.pull("daniel", "a launch is deciding")
    finally:
        os.close(fd)

    assert not pulled.clean
    assert step("launch-lock")["result"] == "failed"
    assert step("timers")["result"] == "turned-off"
    assert step("paper")["result"] == "moved-aside"


def wrap_stub(stub, tmp_path, monkeypatch, when):
    """A `claude` that pulls the kill file into place at `when`, as a pull landing at that moment would."""
    wrapper = tmp_path / "wrapped-claude"
    held = shlex.quote(str(paths.home() / "kill.state"))
    wrapper.write_text(f"#!/bin/sh\ncase \"$*\" in {when}) echo '{{}}' > {held};; esac\nexec {shlex.quote(str(stub.binary))} \"$@\"\n")
    wrapper.chmod(0o700)
    monkeypatch.setenv(launcher.BINARY_VARIABLE, str(wrapper))


def test_a_pull_during_a_launchs_preparing_refuses_it_before_it_starts(company, stub, board, tmp_path, monkeypatch):
    wrap_stub(stub, tmp_path, monkeypatch, "*--help*")

    done = company("session", "start", "probe")

    assert done.returncode == 1
    assert "kill check" in done.stdout
    assert stub.session_calls() == []
    refused = events("launch-refused")[-1]
    assert refused["writer"] == "launcher"
    assert refused["check"] == "kill"
    assert events("session-started") == []


def test_a_session_stops_itself_on_a_pull_it_sees_with_no_kill_command_running(company, stub, board, tmp_path, monkeypatch):
    wrap_stub(stub, tmp_path, monkeypatch, "*--session-id*")
    stub.play({"do": "children", "count": 1}, {"do": "hang"})

    done = company("session", "start", "probe")

    assert done.returncode == 1
    assert events("session-stopped")[-1]["reason"] == "kill-switch"
    # It may stop before the stub gets as far as its child, which is the point; any it did start has gone too.
    started = [pid for line in stub.progress() for pid in line.get("children", [])]
    assert not any(pid_is_running(pid) for pid in started)


def test_a_sessions_rules_keep_it_from_the_kill_file(company, stub, board):
    stub.play()
    assert company("session", "start", "probe").returncode == 0

    rule = "//" + str(paths.home() / "*.state").lstrip("/")
    deny = stub.settings()["permissions"]["deny"]
    assert f"Read({rule})" in deny
    assert f"Edit({rule})" in deny


# The hold


def test_every_launch_is_refused_until_the_resume_command_runs(company, stub, board):
    stub.play()
    assert company("session", "start", "probe").returncode == 0
    assert company("kill").returncode == 0
    used = len(stub.session_calls())

    for args in (("session", "start", "probe"), ("governor", "check", "probe"), ("session", "start", "auditor")):
        refused = company(*args)
        assert refused.returncode == 1, refused.stdout
        assert "kill check" in refused.stdout
        assert "company resume" in refused.stdout
    assert len(stub.session_calls()) == used
    logged = events("launch-refused")
    assert [event["check"] for event in logged] == ["kill", "kill", "kill"]
    assert logged[0]["reason"].startswith("killed: ")

    done = company("resume", "--message", "5678")

    assert done.returncode == 0, done.stdout + done.stderr
    resumed = events("resumed")
    assert len(resumed) == 1
    assert resumed[0]["kill_seq"] == events("kill-pulled")[-1]["seq"]
    assert resumed[0]["writer"] == "board"
    assert resumed[0]["message"] == "5678"
    assert company("session", "start", "probe").returncode == 0
    assert len(stub.session_calls()) == used + 1


def test_the_kill_is_checked_after_the_ledger_and_before_the_settings(company):
    # With no settings at all, the refusal is still the kill's.
    company("kill")
    done = company("governor", "check", "probe")
    assert "kill check" in done.stdout


def test_a_ledger_event_alone_holds_every_launch_even_with_the_file_gone(company, board):
    company("kill")
    (paths.home() / "kill.state").unlink()

    assert "kill check" in company("governor", "check", "probe").stdout

    assert company("resume").returncode == 0
    assert company("governor", "check", "probe").returncode == 0


def test_the_file_alone_holds_every_launch_when_the_ledger_could_not_take_the_pull(company, board):
    (paths.home() / "kill.state").write_text(json.dumps({"by": "daniel", "reason": "r", "at": "2026-11-05T00:00:00Z", "steps": []}))

    assert "kill check" in company("governor", "check", "probe").stdout

    assert company("resume").returncode == 0
    assert events("kill-pulled")[-1]["by"] == "daniel"
    assert events("resumed")[-1]["kill_seq"] == events("kill-pulled")[-1]["seq"]
    assert company("governor", "check", "probe").returncode == 0


def test_a_file_that_is_no_record_still_holds_every_launch_and_resumes(company, board):
    (paths.home() / "kill.state").write_text("not json")

    assert "kill check" in company("governor", "check", "probe").stdout

    assert company("resume").returncode == 0
    assert company("governor", "check", "probe").returncode == 0


def test_two_pulls_need_one_resume_that_closes_both(company, board):
    company("kill")
    company("kill")

    assert company("resume").returncode == 0

    assert sorted(event["kill_seq"] for event in events("resumed")) == [event["seq"] for event in events("kill-pulled")]
    assert company("governor", "check", "probe").returncode == 0


def test_a_later_pull_after_a_resume_holds_again(company, board):
    company("kill")
    company("resume")
    company("kill")

    assert "kill check" in company("governor", "check", "probe").stdout


def test_resume_with_nothing_pulled_is_refused_and_writes_nothing(company, board):
    before = len(events())

    done = company("resume")

    assert done.returncode == 1
    assert "not pulled" in done.stderr
    assert len(events()) == before


def test_resume_is_refused_on_a_broken_ledger_and_the_hold_stays(company, company_home, board):
    company("kill")
    with (company_home / "ledger.jsonl").open("a") as file:
        file.write("not an event\n")

    done = company("resume")

    assert done.returncode == 1
    assert (company_home / "kill.state").exists()


def test_resume_is_refused_on_an_edited_past_line_that_still_reads_as_an_event(company, company_home, board):
    # A break in the middle stops no append, so only the resume's own check of the whole chain can refuse this.
    company("kill")
    ledger = company_home / "ledger.jsonl"
    ledger.write_text(ledger.read_text().replace('"a-plan"', '"b-plan"').replace('"sessions":10', '"sessions":99'))

    done = company("resume")

    assert done.returncode == 1
    assert "broken" in done.stderr
    assert '"kind":"resumed"' not in ledger.read_text()
    assert (company_home / "kill.state").exists()


def test_a_session_cannot_pull_or_resume_it(company, board, monkeypatch):
    company("kill")
    monkeypatch.setenv("COMPANY_SESSION", "aaaaaaaa-0000-4000-8000-000000000000")
    before = events("resumed")

    for args in (("resume",), ("kill",), ("schedule", "enable", "--message", "1")):
        done = company(*args)
        assert done.returncode == 1, args
        assert "Nothing" in done.stderr

    monkeypatch.delenv("COMPANY_SESSION")
    assert events("resumed") == before
    assert len(events("kill-pulled")) == 1
    assert [event["attempted_kind"] for event in events("append-refused")] == ["resumed", "kill-pulled", "schedule-enabled"]


# The schedule, from the kill switch


def test_the_kill_switch_turns_the_schedule_off_and_says_so(company, board, systemctl):
    assert company("schedule", "enable", "--message", "1234").returncode == 0
    timers = sorted(path.name for path in paths.systemd_user().glob("company-*.timer"))

    assert company("kill").returncode == 0

    assert f"--user disable --now {' '.join(timers)}" in systemctl.calls()
    disabled = events("schedule-disabled")
    assert len(disabled) == 1
    assert disabled[0]["writer"] == "killswitch"
    assert f"event {events('kill-pulled')[-1]['seq']}" in disabled[0]["reason"]
    assert step("timers")["result"] == "turned-off"


def test_a_schedule_that_cannot_be_turned_off_is_reported_and_stops_nothing_else(company, stub, board, systemctl, company_home):
    assert company("schedule", "enable", "--message", "1234").returncode == 0
    accounts = json.dumps([{"name": "paper", "rotation": "move-key", "key_file": "paper.key"}])
    assert company("settings", "set", "outside_accounts", accounts).returncode == 0
    settings.key_path({"key_file": "paper.key"}).write_text("fixture")
    launch = hung_session(stub)
    systemctl.fail("disable")

    done = company("kill")

    assert done.returncode == 1
    assert "schedule timers: failed" in done.stdout
    assert step("timers")["result"] == "failed"
    assert "disable failed" in step("timers")["detail"]
    assert step("paper")["result"] == "moved-aside"
    assert not pid_is_running(progress(stub, "hanging"))
    # The ledger's word still says off, which is what a timer left on reads before it runs anything.
    assert len(events("schedule-disabled")) == 1
    launch.communicate(timeout=30)


def test_after_a_resume_the_schedule_stays_off_until_enabled_again(company, board, systemctl):
    assert company("schedule", "enable", "--message", "1234").returncode == 0
    company("kill")
    before = len([call for call in systemctl.calls() if " enable " in f" {call} "])

    refused = company("schedule", "enable", "--message", "1234")
    assert refused.returncode == 1
    assert "company resume" in refused.stderr
    assert len([call for call in systemctl.calls() if " enable " in f" {call} "]) == before

    done = company("resume")
    assert "schedule stays off" in done.stdout
    assert len([call for call in systemctl.calls() if " enable " in f" {call} "]) == before
    assert company("schedule", "run", "kill-self-test").returncode == 1

    assert company("schedule", "enable", "--message", "1234").returncode == 0


# The outside accounts


def set_accounts(company, *names, **key_files):
    accounts = [{"name": name, "rotation": "move-key", "key_file": key_files.get(name, f"{name}.key")} for name in names]
    done = company("settings", "set", "outside_accounts", json.dumps(accounts))
    assert done.returncode == 0, done.stderr


def key_of(name):
    return paths.config() / f"{name}.key"


def test_each_account_listed_is_rotated_and_the_ledger_says_each_result(company, board):
    set_accounts(company, "paper", "other")
    key_of("paper").write_text("the-fixture-key")
    key_of("other").write_text("the-other-fixture-key")

    done = company("kill")

    assert done.returncode == 0, done.stdout + done.stderr
    assert not key_of("paper").exists()
    assert not key_of("other").exists()
    assert [path.read_text() for path in paths.config().glob("paper.key.revoked-*")] == ["the-fixture-key"]
    for name in ("paper", "other"):
        assert step(name)["step"] == "rotation"
        assert step(name)["result"] == "moved-aside"
        assert "regenerate" in step(name)["detail"]
    assert "paper" in done.stdout
    assert "regenerate" in done.stdout


def test_a_rotation_that_fails_does_not_stop_the_others_and_is_reported(company, board):
    set_accounts(company, "first", "broken", "last", broken="not-a-directory/key")
    (paths.config() / "not-a-directory").write_text("a file")
    key_of("first").write_text("k")
    key_of("last").write_text("k")

    done = company("kill")

    assert done.returncode == 1
    assert "rotation broken: failed" in done.stdout
    assert step("broken")["result"] == "failed"
    assert step("broken")["detail"]
    assert step("first")["result"] == "moved-aside"
    assert step("last")["result"] == "moved-aside"
    assert "company resume" in done.stdout


def test_a_key_already_gone_is_said_and_is_no_failure(company, board):
    set_accounts(company, "paper")

    done = company("kill")

    assert done.returncode == 0, done.stdout + done.stderr
    assert step("paper")["result"] == "no-key"


def test_no_key_text_reaches_the_ledger_or_the_output(company, company_home, board):
    set_accounts(company, "paper")
    key_of("paper").write_text("the-fixture-key")

    done = company("kill")

    assert "the-fixture-key" not in done.stdout + done.stderr
    assert "the-fixture-key" not in (company_home / "ledger.jsonl").read_text()
    assert "the-fixture-key" not in (company_home / "kill.state").read_text()


@pytest.mark.parametrize(
    "account",
    [
        "a-string",
        {"name": "x"},
        {"name": "", "rotation": "move-key", "key_file": "k"},
        {"name": "x", "rotation": "run-this", "key_file": "k"},
        {"name": "x", "rotation": "move-key", "key_file": "/etc/passwd"},
        {"name": "x", "rotation": "move-key", "key_file": "../outside"},
        {"name": "x", "rotation": "move-key", "key_file": "k", "more": 1},
    ],
)
def test_settings_refuse_an_account_with_no_rotation_step_it_can_run(company, board, account):
    done = company("settings", "set", "outside_accounts", json.dumps([account]))
    assert done.returncode == 1
    assert "outside_accounts" in done.stderr


def test_a_tampered_settings_file_does_not_stop_the_rotation_and_is_reported(company, board):
    set_accounts(company, "paper")
    key_of("paper").write_text("k")
    path = paths.config() / "settings.json"
    path.write_text(path.read_text().replace('"plan_name"', '"plan_name" ').replace("a-plan", "b-plan"))

    done = company("kill")

    assert done.returncode == 1
    assert not key_of("paper").exists()
    assert step("paper")["result"] == "moved-aside"
    assert step("settings")["result"] == "failed"
    assert "not checked" in step("settings")["detail"]


def test_a_tampered_list_cannot_reach_a_file_outside_the_config_directory(company, board, tmp_path):
    outside = tmp_path / "outside-file"
    outside.write_text("mine")
    path = paths.config() / "settings.json"
    held = json.loads(path.read_text())
    path.write_text(json.dumps({**held, "outside_accounts": [{"name": "evil", "rotation": "move-key", "key_file": str(outside)}, {"name": "worse", "rotation": "move-key", "key_file": "../../outside-file"}]}))

    company("kill")

    assert outside.read_text() == "mine"
    assert step("evil")["result"] == "failed"
    assert step("worse")["result"] == "failed"


# A broken ledger: review finding 35


def break_ledger(company_home):
    with (company_home / "ledger.jsonl").open("ab") as file:
        file.write(b"not an event\n")


def test_it_stops_sessions_on_a_broken_ledger(company, company_home, stub, board):
    set_accounts(company, "paper")
    key_of("paper").write_text("k")
    launch = hung_session(stub)
    break_ledger(company_home)

    done = company("kill", "--reason", "with a broken ledger")

    assert done.returncode == 1
    assert not any(pid_is_running(pid) for pid in [progress(stub, "hanging"), *progress(stub, "children")])
    launch.communicate(timeout=30)
    assert launch.poll() is not None
    assert not key_of("paper").exists()
    assert "could not take" in done.stderr
    assert "stop-session" in done.stdout
    record = json.loads((company_home / "kill.state").read_text())
    assert record["by"] == "daniel"
    assert record["reason"] == "with a broken ledger"
    assert {entry["step"] for entry in record["steps"]} >= {"stop-session", "schedule", "rotation"}


def test_a_ledger_cut_at_its_end_takes_no_write_and_the_launch_stays_refused(company, company_home, board):
    (company_home / "ledger.head").write_text("not a head")

    done = company("kill")

    assert done.returncode == 1
    assert (company_home / "kill.state").exists()
    assert company("governor", "check", "probe").returncode == 1


def test_the_resume_writes_what_the_ledger_could_not_take_at_the_pull(company, company_home, board, tmp_path):
    set_accounts(company, "paper")
    key_of("paper").write_text("k")
    ledger, head = company_home / "ledger.jsonl", company_home / "ledger.head"
    kept = ledger.read_bytes(), head.read_bytes()
    head.write_text("not a head")
    assert company("kill", "--reason", "cut").returncode == 1
    ledger.write_bytes(kept[0])
    head.write_bytes(kept[1])

    done = company("resume")

    assert done.returncode == 0, done.stdout + done.stderr
    pulled = events("kill-pulled")
    assert len(pulled) == 1
    assert pulled[0]["by"] == "daniel"
    assert "cut" in pulled[0]["reason"]
    assert "logged at the resume" in pulled[0]["reason"]
    assert step("paper")["result"] == "moved-aside"
    assert events("resumed")[-1]["kill_seq"] == pulled[0]["seq"]
    assert not (company_home / "kill.state").exists()


# A loop's red line


def test_a_loops_red_line_pulls_it_by_code_and_the_ledger_names_the_loop(company, stub, board):
    launch = hung_session(stub)

    pulled = killswitch.pull("treasurer", "a red line was crossed", loop="honesty")

    assert pulled.clean
    event = events("kill-pulled")[-1]
    assert event["seq"] == pulled.seq
    assert event["by"] == "treasurer"
    assert event["loop"] == "honesty"
    assert not pid_is_running(progress(stub, "hanging"))
    assert "kill check" in company("governor", "check", "probe").stdout
    launch.communicate(timeout=30)


def test_the_launcher_that_finished_a_session_can_pull_it_at_once(stub, board):
    # As the probe will: a forbidden action succeeded, and the process that ran the session pulls the switch.
    stub.play()
    code = (
        "from company import killswitch, launcher\n"
        "launcher.start('probe')\n"
        "pulled = killswitch.pull('probe-check', 'a forbidden action succeeded', loop='first-run')\n"
        "raise SystemExit(0 if pulled.clean else 1)\n"
    )
    began = time.monotonic()

    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False)

    assert done.returncode == 0, done.stdout + done.stderr
    assert time.monotonic() - began < 5, "it waited for itself"
    assert events("kill-pulled")[-1]["loop"] == "first-run"


# The self-test


def tree(root):
    return {str(path.relative_to(root)): path.read_bytes() if path.is_file() else None for path in sorted(root.rglob("*"))}


def test_the_self_test_passes_on_its_own_stubs(company):
    done = company("kill", "--self-test")

    assert done.returncode == 0, done.stdout + done.stderr
    assert "FAILED" not in done.stdout
    for said in ("session", "schedule", "account", "refused", "resume"):
        assert said in done.stdout


def test_the_self_test_never_touches_the_home_it_was_started_from(company, company_home, stub, board, systemctl, tmp_path):
    assert company("schedule", "enable", "--message", "1234").returncode == 0
    set_accounts(company, "paper")
    key_of("paper").write_text("k")
    launch = hung_session(stub)
    calls = systemctl.calls()
    roots = [company_home, paths.config(), paths.systemd_user(), paths.claude_directory()]
    before = [tree(root) for root in roots]
    kept = [pid for pid in [progress(stub, "hanging"), *progress(stub, "children")]]
    try:
        done = company("kill", "--self-test")

        assert done.returncode == 0, done.stdout + done.stderr
        assert [tree(root) for root in roots] == before
        assert systemctl.calls() == calls
        assert all(pid_is_running(pid) for pid in kept)
        assert launch.poll() is None
    finally:
        launch.kill()
        launch.communicate()
        for pid in kept:
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGKILL)


def test_the_self_test_leaves_nothing_of_its_own_behind(company, monkeypatch, tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setenv("TMPDIR", str(scratch))

    assert company("kill", "--self-test").returncode == 0

    assert list(scratch.iterdir()) == []


def test_a_self_test_that_finds_a_broken_stop_fails(tmp_path, monkeypatch):
    # Every `company` it starts has a stop that does nothing: it must say so, and still end what it started.
    wrapper = tmp_path / "pythonpath" / "sitecustomize.py"
    wrapper.parent.mkdir()
    wrapper.write_text(
        f"import sys\nsys.path.insert(0, {os.environ['PYTHONPATH']!r})\n"
        "import audit_guard\naudit_guard.install_from_env()\n"
        "from company import kill_state, launcher\n"
        "launcher.running_sessions = lambda: []\n"
        "kill_state.present = lambda: False\n"
    )
    monkeypatch.setenv("PYTHONPATH", str(wrapper.parent))
    monkeypatch.setattr(killswitch, "_TEST_WAIT_SECONDS", 1)

    checks = killswitch.self_test()

    assert [check.name for check in checks if not check.passed][:2] == ["the session and its child stopped, with nothing left running", "its launcher ended and logged the stop"]
