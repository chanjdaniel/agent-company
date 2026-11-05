"""`company kill` and `company resume`: everything stops at once, and nothing starts until Daniel says so.

Each test runs the installed command on the real clock, with the stub session and a stub `systemctl`.
A loop's red line is code, so those tests call `killswitch.pull` as a loop will, and so do the few that need a shorter wait.
"""

import contextlib
import fcntl
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
from pathlib import Path

import audit_guard
import pytest
from session_checks import events, pid_is_running, wait_for
from usage_records import TEAM, start_session

from company import cli, kill_state, killswitch, launcher, paths, settings
from company.ledger import Ledger

COMPANY = Path(sys.executable).parent / "company"


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


def remove_the_kill_records():
    shutil.rmtree(paths.home() / "kill.state")


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
    assert pulled[0]["pulled_at"] <= pulled[0]["ts"]
    assert "loop" not in pulled[0]
    assert Ledger().verify().ok


def test_a_session_that_ignores_the_signal_is_killed(company, stub, board, systemctl):
    launch = hung_session(stub, {"do": "ignore-term"})

    assert company("kill").returncode == 0

    assert not pid_is_running(progress(stub, "hanging"))
    launch.communicate(timeout=30)


def test_a_frozen_launcher_does_not_keep_the_session_or_itself_alive(company, stub, board, systemctl):
    # A launcher that is awake may see the hold and stop its session first, leaving the pull no step for it; this one cannot.
    launch = hung_session(stub)
    launch.send_signal(signal.SIGSTOP)

    done = company("kill")

    assert done.returncode == 0, done.stdout + done.stderr
    assert not any(pid_is_running(pid) for pid in [progress(stub, "hanging"), *progress(stub, "children")])
    launch.communicate(timeout=30)
    assert launch.returncode == -signal.SIGKILL
    assert events("session-stopped")[-1]["reason"] == "launcher-gone"
    session = events("session-started")[-1]["session"]
    assert step(session)["step"] == "stop-session"
    assert step(session)["result"] == "stopped"


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
    """A `claude` that puts `kill.state` in place at `when`, as a pull landing at that moment would."""
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

    deny = stub.settings()["permissions"]["deny"]
    for name in ("*.state", "kill.state/**", "*.lock"):
        rule = "//" + str(paths.home() / name).lstrip("/")
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
    remove_the_kill_records()

    assert "kill check" in company("governor", "check", "probe").stdout

    assert company("resume").returncode == 0
    assert company("governor", "check", "probe").returncode == 0


def test_the_file_alone_holds_every_launch_when_the_ledger_could_not_take_the_pull(company, board):
    kill_state.write({"id": "a-pull", "by": "daniel", "reason": "r", "pulled_at": "2026-11-05T00:00:00Z", "steps": []})

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

    for args in (("resume",), ("kill",), ("schedule", "enable", "--message", "1"), ("schedule", "disable"), ("schedule", "install")):
        done = company(*args)
        assert done.returncode == 1, args
        assert "Nothing" in done.stderr

    monkeypatch.delenv("COMPANY_SESSION")
    assert events("resumed") == before
    assert len(events("kill-pulled")) == 1
    assert [event["attempted_kind"] for event in events("append-refused")] == ["resumed", "kill-pulled", "schedule-enabled", "schedule-disabled", "schedule-install"]


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
    assert "the-fixture-key" not in json.dumps(kill_state.read())


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
    # So that the stop is the pull's, and this launcher does not see the hold and do it first.
    launch.send_signal(signal.SIGSTOP)
    break_ledger(company_home)

    done = company("kill", "--reason", "with a broken ledger")

    assert done.returncode == 1
    assert not any(pid_is_running(pid) for pid in [progress(stub, "hanging"), *progress(stub, "children")])
    launch.communicate(timeout=30)
    assert launch.poll() is not None
    assert not key_of("paper").exists()
    assert "could not take" in done.stderr
    assert "stop-session" in done.stdout
    record = kill_state.read()[-1]
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
    assert pulled[0]["reason"] == "cut"
    assert pulled[0]["pulled_at"] <= pulled[0]["ts"]
    assert step("paper")["result"] == "moved-aside"
    assert events("resumed")[-1]["kill_seq"] == pulled[0]["seq"]
    assert not (company_home / "kill.state").exists()


def test_a_resume_writes_no_step_a_second_time(company, board):
    set_accounts(company, "paper")
    key_of("paper").write_text("k")
    company("kill")

    assert company("resume").returncode == 0

    assert len(events("kill-pulled")) == 1
    assert step("paper")["result"] == "moved-aside"
    assert step("timers")["result"] == "turned-off"


def test_with_no_settings_file_there_is_nothing_to_rotate_and_no_failure(company):
    done = company("kill")

    assert done.returncode == 0, done.stdout + done.stderr
    assert [event["step"] for event in events("kill-step")] == ["schedule"]


def test_a_settings_file_that_cannot_be_read_is_reported_and_stops_nothing_else(company, stub, board):
    launch = hung_session(stub)
    (paths.config() / "settings.json").write_text("not json")

    done = company("kill")

    assert done.returncode == 1
    assert "cannot be read" in done.stdout
    assert not pid_is_running(progress(stub, "hanging"))
    assert step("timers")["result"] == "turned-off"
    launch.communicate(timeout=30)


def test_a_ledger_that_stops_part_way_through_a_pull_gets_the_rest_at_the_resume(company, board, systemctl, monkeypatch):
    # It took `kill-pulled` and no more, so the schedule's word in the ledger still said on.
    assert company("schedule", "enable", "--message", "1234").returncode == 0
    set_accounts(company, "paper")
    key_of("paper").write_text("k")
    real = Ledger.append

    def full_after_the_first(self, kind, fields, writer, refusal_context=None):
        if kind == "kill-step":
            raise OSError("no space left")
        return real(self, kind, fields, writer, refusal_context)

    monkeypatch.setattr(Ledger, "append", full_after_the_first)
    pulled = killswitch.pull("daniel", "part way")
    monkeypatch.setattr(Ledger, "append", real)
    assert "could not take" in pulled.unlogged
    assert events("kill-step") == []

    done = company("resume")

    assert done.returncode == 0, done.stdout + done.stderr
    assert len(events("kill-pulled")) == 1
    assert step("paper")["result"] == "moved-aside"
    assert step("timers")["result"] == "turned-off"
    assert "The schedule is off." in company("schedule", "list").stdout
    assert "schedule-off" in company("session", "start", "probe", "--scheduled").stdout


def test_a_second_pull_on_a_broken_ledger_keeps_the_first_ones_record(company, company_home, board):
    ledger, head = company_home / "ledger.jsonl", company_home / "ledger.head"
    kept = ledger.read_bytes(), head.read_bytes()
    head.write_text("not a head")
    company("kill", "--reason", "first")
    company("kill", "--reason", "second")
    ledger.write_bytes(kept[0])
    head.write_bytes(kept[1])

    assert company("resume").returncode == 0

    assert [event["reason"] for event in events("kill-pulled")] == ["first", "second"]
    assert sorted(event["kill_seq"] for event in events("resumed")) == [event["seq"] for event in events("kill-pulled")]


def test_a_resume_with_the_file_gone_still_leaves_the_schedule_off(company, company_home, board, systemctl, monkeypatch):
    assert company("schedule", "enable", "--message", "1234").returncode == 0
    real = Ledger.append

    def no_steps(self, kind, fields, writer, refusal_context=None):
        if kind == "kill-step":
            raise OSError("no space left")
        return real(self, kind, fields, writer, refusal_context)

    monkeypatch.setattr(Ledger, "append", no_steps)
    killswitch.pull("daniel", "part way")
    monkeypatch.setattr(Ledger, "append", real)
    remove_the_kill_records()

    assert company("resume").returncode == 0

    assert "The schedule is off." in company("schedule", "list").stdout


def test_a_frozen_lock_on_the_ledger_stops_no_action_and_the_pull_still_reports(company, board, systemctl, stub):
    # Something holds the ledger's lock and never lets go, so a pull that waited for it would never move the key.
    assert company("schedule", "enable", "--message", "1234").returncode == 0
    set_accounts(company, "paper")
    key_of("paper").write_text("k")
    launch = hung_session(stub)
    code = (
        "from company import killswitch\n"
        "killswitch._LEDGER_WAIT_SECONDS = 1\n"
        "pulled = killswitch.pull('daniel', 'a frozen lock')\n"
        "print(pulled.unlogged)\n"
    )
    lock = os.open(paths.home() / "ledger.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        # The launcher's end is the one write that can get ahead of this: it waits on the lock, and is killed in time.
        fcntl.flock(lock, fcntl.LOCK_EX)
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False)
        assert done.returncode == 0, done.stdout + done.stderr
        assert "did not answer" in done.stdout
        assert not key_of("paper").exists()
        assert not pid_is_running(progress(stub, "hanging"))
        assert any(call.startswith("--user disable --now") for call in systemctl.calls())
    finally:
        os.close(lock)
    launch.communicate(timeout=30)
    assert (paths.home() / "kill.state").exists()
    record = kill_state.read()[-1]
    assert record["reason"] == "a frozen lock"


def test_one_unreadable_session_record_spares_no_other_session(company, company_home, stub, board):
    launch = hung_session(stub)
    # The launcher died, so only the kill command can stop what it left.
    launch.kill()
    launch.communicate()
    for name, text in (("a-list", "[]"), ("not-json", "{"), ("no-session", '{"group": 1}')):
        (paths.runs() / name).mkdir()
        (paths.runs() / name / "session.json").write_text(text)

    done = company("kill")

    assert done.returncode == 0, done.stdout + done.stderr
    assert not any(pid_is_running(pid) for pid in [progress(stub, "hanging"), *progress(stub, "children")])


def test_the_next_launch_is_not_stopped_by_an_unreadable_session_record(company, stub, board):
    stub.play()
    (paths.runs() / "a-list").mkdir(parents=True)
    (paths.runs() / "a-list" / "session.json").write_text("[]")
    start_session(TEAM, "probe", board)
    Ledger().append("session-stopped", {"session": TEAM, "reason": "x"}, "launcher")

    assert company("session", "start", "probe").returncode == 0


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
        "assert pulled.clean, pulled\n"
        "assert not [step for step in pulled.steps if step.step == killswitch.STOP_SESSION], pulled\n"
    )

    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False)

    assert done.returncode == 0, done.stdout + done.stderr
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


# The cost of a pull: review finding 41


def test_a_pulls_first_act_and_its_sweeps_do_not_grow_with_the_runs_the_company_has_had(monkeypatch):
    for number in range(500):
        run = paths.runs() / f"old-{number}"
        run.mkdir(parents=True)
        # Numbers above any pid this machine can give, as a long-gone session's are; each as a real record holds them.
        record = {"session": f"old-{number}", "launcher": 5_000_000 + number, "launcher_started": 1, "group": 5_000_000 + number, "group_started": 1}
        (run / "session.json").write_text(json.dumps(record))
    read, sweep = launcher._process_stat, launcher.running_sessions
    held_at_each_read, held_at_each_sweep = [], []

    def counted_read(pid):
        # A pull's own number goes in its first file: one read, of itself, whatever the machine holds.
        if pid != os.getpid():
            held_at_each_read.append(kill_state.present())
        return read(pid)

    def counted_sweep():
        held_at_each_sweep.append(kill_state.present())
        return sweep()

    monkeypatch.setattr(launcher, "_process_stat", counted_read)
    monkeypatch.setattr(launcher, "running_sessions", counted_sweep)

    killswitch.pull("daniel", "after many runs")

    assert all(held_at_each_sweep), "a sweep came before the hold"
    assert all(held_at_each_read), "a look at the processes came before the hold"
    processes = sum(entry.name.isdigit() for entry in Path("/proc").iterdir())
    assert len(held_at_each_read) < 10 * processes, "each run's record cost a look at every process"


# Pulls that overlap: review finding 42


def a_second_pull_during_the_first(systemctl):
    hook = systemctl.directory / "after-disable"
    systemctl.after("disable", f"rm -f {shlex.quote(str(hook))}\n{shlex.quote(str(COMPANY))} kill --reason second > /dev/null 2>&1")


def assert_each_pull_once_with_its_steps():
    pulled = events("kill-pulled")
    assert sorted(event["reason"] for event in pulled) == ["first", "second"]
    for event in pulled:
        steps = [found for found in events("kill-step") if found.get("pull") == event.get("pull")]
        assert [found["target"] for found in steps] == ["timers"], event["reason"]


def test_two_pulls_that_overlap_on_a_whole_ledger_are_each_written_once(company, board, systemctl):
    assert company("schedule", "enable", "--message", "1234").returncode == 0
    a_second_pull_during_the_first(systemctl)

    company("kill", "--reason", "first")
    assert company("resume").returncode == 0

    assert_each_pull_once_with_its_steps()


def test_two_pulls_that_overlap_on_a_cut_ledger_are_each_written_once_at_the_resume(company, company_home, board, systemctl):
    assert company("schedule", "enable", "--message", "1234").returncode == 0
    a_second_pull_during_the_first(systemctl)
    ledger, head = company_home / "ledger.jsonl", company_home / "ledger.head"
    kept = ledger.read_bytes(), head.read_bytes()
    head.write_text("not a head")

    company("kill", "--reason", "first")
    ledger.write_bytes(kept[0])
    head.write_bytes(kept[1])
    assert company("resume").returncode == 0

    assert_each_pull_once_with_its_steps()


def test_a_pull_that_lands_during_a_resume_keeps_its_hold(company, board, monkeypatch):
    company("kill", "--reason", "first")
    real = Ledger.append

    def a_pull_lands(self, kind, fields, writer, refusal_context=None):
        written = real(self, kind, fields, writer, refusal_context)
        if kind == "resumed":
            monkeypatch.setattr(Ledger, "append", real)
            # The hold is its first act; its write-up then waits its turn behind this resume.
            second.append(subprocess.Popen([COMPANY, "kill", "--reason", "second"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            wait_for(lambda: len(kill_state.read()) == 2)
        return written

    second = []
    monkeypatch.setattr(Ledger, "append", a_pull_lands)

    with pytest.raises(killswitch.ResumeRefused, match="another pull"):
        killswitch.resume()
    monkeypatch.setattr(Ledger, "append", real)
    assert second[0].wait(timeout=60) == 0

    assert "kill check" in company("governor", "check", "probe").stdout
    assert company("resume").returncode == 0
    assert company("governor", "check", "probe").returncode == 0
    assert sorted(event["reason"] for event in events("kill-pulled")) == ["first", "second"]


def test_resumes_at_the_same_moment_write_each_event_once(company, company_home, board):
    set_accounts(company, "paper")
    ledger, head = company_home / "ledger.jsonl", company_home / "ledger.head"
    kept = ledger.read_bytes(), head.read_bytes()
    head.write_text("not a head")
    company("kill", "--reason", "cut")
    ledger.write_bytes(kept[0])
    head.write_bytes(kept[1])

    resumes = [subprocess.Popen([COMPANY, "resume"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for _ in range(6)]
    for resume in resumes:
        resume.wait(timeout=60)

    assert len(events("kill-pulled")) == 1
    assert len(events("resumed")) == 1
    assert len([event for event in events("kill-step") if event["target"] == "paper"]) == 1
    assert Ledger().verify().ok
    assert company("governor", "check", "probe").returncode == 0


def test_one_pulls_record_is_not_written_over_by_anothers(company, company_home, board, systemctl):
    assert company("schedule", "enable", "--message", "1234").returncode == 0
    a_second_pull_during_the_first(systemctl)
    (company_home / "ledger.head").write_text("not a head")

    company("kill", "--reason", "first")

    assert sorted(record["reason"] for record in kill_state.read()) == ["first", "second"]
    assert all(record["steps"] for record in kill_state.read())


# A refused resume: review finding 43


def test_a_refused_resume_leaves_the_next_one_nothing_to_write_twice(company, company_home, board):
    set_accounts(company, "paper")
    key_of("paper").write_text("k")
    ledger, head = company_home / "ledger.jsonl", company_home / "ledger.head"
    kept = ledger.read_bytes(), head.read_bytes()
    head.write_text("not a head")
    company("kill", "--reason", "cut")
    ledger.write_bytes(kept[0])
    head.write_bytes(kept[1])

    refused = company("resume", "--message", "not-an-id")

    assert refused.returncode == 1
    assert "kill check" in company("governor", "check", "probe").stdout

    assert company("resume", "--message", "1234").returncode == 0

    assert len(events("kill-pulled")) == 1
    targets = [event["target"] for event in events("kill-step")]
    assert sorted(targets) == sorted(set(targets))
    assert "paper" in targets


# A session that has ended: review finding 44


def test_a_live_process_that_has_finished_its_sessions_is_not_running_one(company, stub, board, systemctl):
    stub.play()
    code = "import time\nfrom company import launcher\nlauncher.start('probe')\nlauncher.start('probe')\nprint('ready', flush=True)\ntime.sleep(600)\n"
    process = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == "ready"

        done = company("kill")

        assert done.returncode == 0, done.stdout + done.stderr
        assert [event for event in events("kill-step") if event["step"] == "stop-session"] == []
        assert process.poll() is None
    finally:
        process.kill()
        process.communicate()


def test_a_long_lived_process_whose_session_a_pull_stops_is_not_killed(company, stub, board, systemctl, tmp_path):
    stub.play({"do": "children", "count": 1}, {"do": "hang"})
    code = "import time\nfrom company import launcher\nlauncher.start('probe')\nprint('ended', flush=True)\ntime.sleep(600)\n"
    process = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    try:
        wait_for(lambda: any("hanging" in line for line in stub.progress()))

        done = company("kill")

        assert done.returncode == 0, done.stdout + done.stderr
        assert process.stdout.readline().strip() == "ended"
        assert process.poll() is None
        assert events("session-stopped")[-1]["reason"] == "kill-switch"
        # The launcher may see the hold first, and then the pull has no step for this session.
        session = events("session-started")[-1]["session"]
        assert all(event["result"] == "stopped" for event in events("kill-step") if event["target"] == session)
    finally:
        process.kill()
        process.communicate()


def test_a_long_lived_process_whose_session_could_not_start_is_not_running_one(company, stub, board, systemctl, tmp_path, monkeypatch):
    wrapper = tmp_path / "goes-after-its-help"
    wrapper.write_text(f"#!/bin/sh\nrm -f {shlex.quote(str(wrapper))}\nexec {shlex.quote(str(stub.binary))} \"$@\"\n")
    wrapper.chmod(0o700)
    monkeypatch.setenv(launcher.BINARY_VARIABLE, str(wrapper))
    code = "import time\nfrom company import launcher\nprint(launcher.start('probe').check, flush=True)\ntime.sleep(600)\n"
    process = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == "binary"

        done = company("kill")

        assert done.returncode == 0, done.stdout + done.stderr
        assert [event for event in events("kill-step") if event["step"] == "stop-session"] == []
        assert process.poll() is None
    finally:
        process.kill()
        process.communicate()


# A pull from a company tool: review finding 45


def test_a_pull_in_a_tools_environment_is_refused_and_says_so(company, stub, board, systemctl, tmp_path):
    # A real server has the session's allow-list and its own `env`, so it cannot see the config or reach the timers.
    # Pulling all the same reported timers that are on as `turned-off`, `0 installed`, and left the key in place.
    assert company("schedule", "enable", "--message", "1234").returncode == 0
    set_accounts(company, "paper")
    key_of("paper").write_text("k")
    code = "from company import killswitch\nkillswitch.pull('a-tool', 'crossed a line', loop='honesty')\n"
    session = "11111111-2222-4333-8444-555555555555"
    environment = {
        **launcher.child_environment(session),
        **launcher._mcp_config("probe", None, session)["mcpServers"]["company"]["env"],
        "PATH": f"{systemctl.directory}{os.pathsep}{launcher.CHILD_PATH}",
        "PYTHONPATH": os.environ["PYTHONPATH"],
        audit_guard.ENV: os.environ[audit_guard.ENV],
    }
    pairs = [f"{name}={value}" for name, value in environment.items()]
    stub.play({"do": "run", "command": ["/usr/bin/env", "-i", *pairs, sys.executable, "-c", code]})
    disabled_before = [call for call in systemctl.calls() if " disable " in call]

    assert company("session", "start", "probe").returncode == 0

    assert stub.runs()[-1]["exit"] != 0
    assert "cannot pull the kill switch" in stub.runs()[-1]["stderr"]
    assert key_of("paper").exists()
    assert not kill_state.present()
    assert events("kill-pulled") == []
    assert [call for call in systemctl.calls() if " disable " in call] == disabled_before
    refused = events("append-refused")[-1]
    assert refused["attempted_kind"] == "kill-pulled"
    assert refused["reason"] == "inside-a-session"
    assert refused["session"] == session


def test_a_session_is_given_what_refuses_a_pull_from_its_tools(company, stub, board):
    stub.play()

    assert company("session", "start", "probe").returncode == 0

    server = stub.mcp_config()["mcpServers"]["company"]
    assert server["env"][launcher.SESSION_VARIABLE] == stub.argument("--session-id")


# What `key_file` may name: review finding 46

RESERVED_KEY_FILES = (".", "./", "settings.json", "settings.lock", "settings.json.new", "./settings.json", "sub/..")


@pytest.mark.parametrize("key_file", RESERVED_KEY_FILES)
def test_settings_refuse_a_key_file_that_names_the_directory_or_its_own_files(company, board, key_file):
    account = {"name": "x", "rotation": "move-key", "key_file": key_file}

    done = company("settings", "set", "outside_accounts", json.dumps([account]))

    assert done.returncode == 1, done.stdout
    assert "outside_accounts" in done.stderr


@pytest.mark.parametrize("key_file", RESERVED_KEY_FILES)
def test_a_tampered_list_cannot_move_the_config_directory_or_its_own_files(company, board, key_file):
    path = paths.config() / "settings.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), "outside_accounts": [{"name": "evil", "rotation": "move-key", "key_file": key_file}, {"name": "last", "rotation": "move-key", "key_file": "last.key"}]}))
    key_of("last").write_text("k")

    company("kill")

    assert step("evil")["result"] == "failed"
    assert step("last")["result"] == "moved-aside"
    assert path.exists()
    assert (paths.config() / "settings.lock").exists()


def test_a_key_file_that_is_a_directory_is_left_where_it_is(company, board):
    (paths.config() / "keys").mkdir()
    (paths.config() / "keys" / "paper").write_text("k")
    set_accounts(company, "paper", paper="keys")

    company("kill")

    assert step("paper")["result"] == "failed"
    assert (paths.config() / "keys" / "paper").read_text() == "k"


# A resume against a pull that is still going: review findings 52, 53 and 54


def test_a_resume_while_a_pull_is_still_running_is_refused_and_says_so(company, board, systemctl, tmp_path):
    assert company("schedule", "enable", "--message", "1234").returncode == 0
    said = tmp_path / "the-resume-said"
    hook = systemctl.directory / "after-disable"
    systemctl.after("disable", f"rm -f {shlex.quote(str(hook))}\n{shlex.quote(str(COMPANY))} resume > {shlex.quote(str(said))} 2>&1\necho \"exit $?\" >> {shlex.quote(str(said))}")

    assert company("kill", "--reason", "first").returncode == 0

    text = said.read_text()
    assert "exit 1" in text
    assert "still running" in text
    assert "launches may start" not in text
    assert events("resumed") == []
    assert "pulled by event" in company("governor", "check", "probe").stdout
    assert company("resume").returncode == 0
    assert company("governor", "check", "probe").returncode == 0
    assert [event["target"] for event in events("kill-step")] == ["timers"]


def test_a_pull_that_died_part_way_does_not_stop_the_resume(company, board, systemctl):
    assert company("schedule", "enable", "--message", "1234").returncode == 0
    systemctl.after("disable", "kill -9 $PPID")

    assert company("kill", "--reason", "cut short").returncode == -signal.SIGKILL
    assert "kill check" in company("governor", "check", "probe").stdout

    done = company("resume")

    assert done.returncode == 0, done.stderr
    assert company("governor", "check", "probe").returncode == 0
    assert [event["reason"] for event in events("kill-pulled")] == ["cut short"]


def test_a_later_process_with_a_pulls_number_does_not_stop_the_resume(company, board):
    # This process's own number, with a start time that is not its own: the pull died, and the number was reused.
    kill_state.write({"id": "1-reused", "by": "daniel", "reason": "reused", "steps": [], "process": {"pid": os.getpid(), "started": -1}})

    done = company("resume")

    assert done.returncode == 0, done.stderr
    assert [event["reason"] for event in events("kill-pulled")] == ["reused"]


def test_a_process_that_goes_on_after_its_pull_does_not_stop_the_resume(company, board):
    assert killswitch.pull("treasurer", "a red line was crossed", loop="honesty").clean

    done = company("resume")

    assert done.returncode == 0, done.stderr
    assert company("governor", "check", "probe").returncode == 0


LANDED = {"id": "99999999999999999999-landed", "by": "daniel", "reason": "second", "steps": []}


def a_pull_lands_once_the_resume_has_read(monkeypatch):
    real = kill_state.read

    def read_then_land():
        found = real()
        monkeypatch.setattr(kill_state, "read", real)
        kill_state.write(LANDED)
        return found

    monkeypatch.setattr(kill_state, "read", read_then_land)


def test_a_resume_cites_only_the_pulls_it_read(company, board, monkeypatch):
    company("kill", "--reason", "first")
    a_pull_lands_once_the_resume_has_read(monkeypatch)

    with pytest.raises(killswitch.ResumeRefused, match="another pull"):
        killswitch.resume()

    first = next(event for event in events("kill-pulled") if event["reason"] == "first")
    assert [event["kill_seq"] for event in events("resumed")] == [first["seq"]]
    assert [event["reason"] for event in events("kill-pulled")] == ["first"]
    assert kill_state.present()
    assert "kill check" in company("governor", "check", "probe").stdout
    assert company("resume").returncode == 0
    assert company("governor", "check", "probe").returncode == 0
    assert sorted(event["reason"] for event in events("kill-pulled")) == ["first", "second"]


def test_the_command_says_which_pulls_closed_when_another_lands_during_its_resume(company, board, monkeypatch, capsys):
    company("kill", "--reason", "first")
    a_pull_lands_once_the_resume_has_read(monkeypatch)

    code = cli.main(["resume", "--message", "1234"])

    said = capsys.readouterr()
    closed = events("resumed")[0]
    assert code == 1
    assert closed["message"] == "1234"
    assert "Nothing was resumed" not in said.err
    assert "launches may start" not in said.out
    assert f"event {closed['kill_seq']}" in said.err
    assert "another pull" in said.err
    assert "company resume" in said.err


# Records that say the wrong thing: review finding 55


def a_session_whose_record_has_a_list_for_a_group(board):
    start_session(TEAM, "probe", board)
    run = paths.runs() / "run-1"
    run.mkdir(parents=True)
    (run / "session.json").write_text(json.dumps({"session": TEAM, "group": [1], "group_started": 1}))


def test_a_group_that_is_no_number_does_not_stop_the_next_launch(company, stub, board):
    stub.play()
    a_session_whose_record_has_a_list_for_a_group(board)

    done = company("session", "start", "probe")

    assert done.returncode == 0, done.stdout + done.stderr
    assert "Traceback" not in done.stderr


def test_a_group_that_is_no_number_does_not_stop_a_pulls_write_up(company, board):
    a_session_whose_record_has_a_list_for_a_group(board)

    done = company("kill", "--reason", "first")

    assert done.returncode == 0, done.stdout + done.stderr
    assert "did not answer" not in done.stderr
    assert [event["reason"] for event in events("kill-pulled")] == ["first"]


def test_a_write_up_that_fails_says_so_and_does_not_blame_the_lock(board, monkeypatch):
    def fails():
        raise RuntimeError("the write-up broke")

    monkeypatch.setattr(launcher, "close_gone_sessions", fails)

    pulled = killswitch.pull("treasurer", "a red line was crossed")

    assert "did not answer" not in pulled.unlogged
    assert "the write-up broke" in pulled.unlogged
    assert kill_state.present()


@pytest.mark.parametrize("steps", ["x", 5, [1], {"a": 1}, [{"step": ["x"], "target": "t", "result": "r"}], [{"target": "t"}]])
def test_a_pulls_file_with_steps_that_are_not_steps_says_so_at_the_resume(company, board, steps):
    kill_state.write({"id": "1-edited", "by": "daniel", "reason": "edited", "steps": steps})

    done = company("resume")

    assert "Traceback" not in done.stderr
    assert ".;" not in done.stderr
    assert (done.returncode == 0) == (not kill_state.present())
    assert (done.returncode == 0) == (len(events("resumed")) == 1)


# The retry that keeps a pull's first act: review finding 56


def test_a_pulls_record_is_kept_when_a_resume_takes_the_directory_away_mid_write(monkeypatch):
    real = Path.replace

    def taken_away_first(self, target):
        monkeypatch.setattr(Path, "replace", real)
        (paths.home() / "kill.state").rmdir()
        return real(self, target)

    monkeypatch.setattr(Path, "replace", taken_away_first)

    kill_state.write(LANDED)

    assert kill_state.present()
    assert kill_state.read() == [LANDED]


# A launcher that could not clear its record: review finding 58


def test_a_launcher_that_could_not_clear_its_record_does_not_stop_itself(stub, board):
    stub.play()
    code = (
        "from company import killswitch, launcher\n"
        "launcher._forget_processes = lambda launch: None\n"
        "launcher.start('probe')\n"
        "pulled = killswitch.pull('probe-check', 'a forbidden action succeeded', loop='first-run')\n"
        "assert not [step for step in pulled.steps if step.step == killswitch.STOP_SESSION], pulled\n"
    )

    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False)

    assert done.returncode == 0, done.stdout + done.stderr


# What a refused pull says: review finding 59


@pytest.mark.parametrize("value", ["aaaaaaaa-0000-4000-8000-000000000000", ""])
def test_a_pull_refused_by_a_stray_variable_says_the_switch_was_not_pulled_and_names_it(company, board, monkeypatch, value):
    monkeypatch.setenv("COMPANY_SESSION", value)

    done = company("kill")

    assert done.returncode == 1
    assert "kill switch was not pulled" in done.stderr
    assert "COMPANY_SESSION" in done.stderr
    assert "Every launch is refused" not in done.stdout
    monkeypatch.delenv("COMPANY_SESSION")
    assert not kill_state.present()
    assert events("kill-pulled") == []
