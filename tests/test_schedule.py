"""The schedule: its jobs are listed in code, its timers install off, and only Daniel's command turns them on.

Each test runs the installed command with a stub `systemctl`; the suite's blocker fails any test that reaches a real one.
"""

import os
import shlex
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from ledger_history import ledger_at, section
from session_checks import events
from usage_records import (
    ALPHA,
    record_reading,
    start_session,
    transcript_line,
    week_reading,
)

from company import paths, schedule
from company.ledger import Ledger


def turned_on(systemctl):
    """Every call that could start a timer, by any verb a test could miss."""
    return [call for call in systemctl.calls() if any(verb in call.split() for verb in ("enable", "start", "restart", "reenable", "--now")) and "disable" not in call.split()]


def timers():
    return sorted(path.name for path in paths.systemd_user().glob("*.timer"))


JOB_NAMES = [job.name for job in schedule.JOBS]


# Installed off


def test_nothing_is_enabled_after_install(company, systemctl):
    done = company("schedule", "install")

    assert done.returncode == 0, done.stdout + done.stderr
    assert turned_on(systemctl) == []
    assert systemctl.calls() == ["--user daemon-reload"]
    assert timers() == sorted(f"company-{name}.timer" for name in JOB_NAMES)
    assert events("schedule-enabled") == []
    assert "off" in done.stdout


def test_installing_twice_leaves_it_off(company, systemctl):
    company("schedule", "install")
    company("schedule", "install")
    assert turned_on(systemctl) == []


def test_each_timer_fires_its_job_through_the_ledgers_check(company, systemctl, company_home):
    company("schedule", "install")
    directory = paths.systemd_user()

    for job in schedule.JOBS:
        service = (directory / f"company-{job.name}.service").read_text()
        assert f"schedule run {job.name}".replace(" ", '" "') in service
        assert f'Environment="COMPANY_HOME={company_home}"' in service
        timer = (directory / f"company-{job.name}.timer").read_text()
        assert f"OnCalendar={job.calendar}" in timer
        assert "WantedBy=timers.target" in timer


def test_a_units_command_really_runs_and_refuses_with_the_schedule_off(company, systemctl):
    company("schedule", "install")
    service = (paths.systemd_user() / "company-kill-self-test.service").read_text()
    line = next(line for line in service.splitlines() if line.startswith("ExecStart="))

    done = subprocess.run(shlex.split(line.removeprefix("ExecStart=")), capture_output=True, text=True, timeout=60, check=False)

    assert done.returncode == 1
    assert "the schedule is off" in done.stderr
    assert "did not run" in done.stderr


def test_with_no_systemctl_it_says_so(company, monkeypatch, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))

    done = company("schedule", "install")

    assert done.returncode == 1
    assert "no systemctl" in done.stderr


# The job list


def test_the_self_test_the_charge_the_paper_tick_and_the_check_are_jobs(company, systemctl):
    assert ("kill", "--self-test") in [job.command for job in schedule.JOBS]
    assert ("treasurer", "charge") in [job.command for job in schedule.JOBS]
    assert ("paper", "tick") in [job.command for job in schedule.JOBS]
    assert ("treasurer", "check") in [job.command for job in schedule.JOBS]
    done = company("schedule", "list")
    assert done.returncode == 0, done.stderr
    assert "The schedule is off." in done.stdout
    assert "kill-self-test: `company kill --self-test`" in done.stdout
    assert "treasurer-charge: `company treasurer charge`" in done.stdout
    assert "paper-tick: `company paper tick`" in done.stdout
    assert "treasurer-check: `company treasurer check`" in done.stdout


@pytest.mark.parametrize("name", JOB_NAMES)
def test_each_job_stays_off_with_the_schedule(company, name):
    before = events()

    done = company("schedule", "run", name)

    assert done.returncode == 1
    assert "the schedule is off" in done.stderr
    assert events() == before


def test_a_job_is_refused_on_a_broken_ledger(company, company_home, board):
    with (company_home / "ledger.jsonl").open("a") as file:
        file.write("not an event\n")
    assert company("schedule", "run", "kill-self-test").returncode == 1


def test_the_self_test_job_runs_with_the_schedule_on(company, board, systemctl):
    assert company("schedule", "enable", "--message", "1234").returncode == 0
    before = events()

    done = company("schedule", "run", "kill-self-test")

    assert done.returncode == 0, done.stdout + done.stderr
    assert "passed" in done.stdout
    assert events() == before
    assert "--user disable --now" not in " ".join(systemctl.calls())


def test_an_unknown_job_is_a_mistake_in_the_command(company):
    assert company("schedule", "run", "no-such-job").returncode == 2


# Turning it on


def test_enable_needs_the_message(company, systemctl):
    done = company("schedule", "enable")
    assert done.returncode == 2
    assert "--message" in done.stderr
    assert systemctl.calls() == []


def test_enable_logs_its_word_and_turns_on_every_timer(company, board, systemctl):
    done = company("schedule", "enable", "--message", "1234")

    assert done.returncode == 0, done.stdout + done.stderr
    word = events("schedule-enabled")
    assert len(word) == 1
    assert word[0]["writer"] == "board"
    assert word[0]["message"] == "1234"
    assert word[0]["jobs"] == JOB_NAMES
    assert systemctl.calls()[-1] == "--user enable --now " + " ".join(f"company-{name}.timer" for name in JOB_NAMES)
    assert "The schedule is on." in company("schedule", "list").stdout


@pytest.mark.parametrize("message", ["", "not-a-discord-id"])
def test_a_word_that_cannot_be_true_turns_nothing_on(company, board, systemctl, message):
    done = company("schedule", "enable", "--message", message)

    assert done.returncode == 1
    assert turned_on(systemctl) == []
    assert events("schedule-enabled") == []


def test_a_failed_enable_turns_it_off_again_and_logs_that(company, board, systemctl):
    systemctl.fail("enable")

    done = company("schedule", "enable", "--message", "1234")

    assert done.returncode == 1
    assert "enable failed" in done.stderr
    assert "the ledger says the schedule is off" in done.stderr.lower()
    assert events("schedule-disabled")[-1]["reason"] == "enable-failed"
    assert "The schedule is off." in company("schedule", "list").stdout
    assert systemctl.calls()[-1].startswith("--user disable --now")


def test_a_failed_enable_turns_the_timers_off_even_if_the_ledger_cannot_say_so(company, company_home, board, systemctl):
    systemctl.fail("enable")
    systemctl.after("enable", f"echo 'not a head' > '{company_home}/ledger.head'")

    assert company("schedule", "enable", "--message", "1234").returncode == 1

    assert systemctl.calls()[-1].startswith("--user disable --now")


def test_a_pull_landing_during_an_enable_leaves_the_timers_off(company, company_home, board, systemctl):
    systemctl.after("enable", f"echo '{{}}' > '{company_home}/kill.state'")

    done = company("schedule", "enable", "--message", "1234")

    assert done.returncode == 1
    assert "pulled" in done.stderr
    assert systemctl.calls()[-1].startswith("--user disable --now")
    assert "The schedule is off." in company("schedule", "list").stdout


def test_enable_is_refused_on_a_broken_ledger(company, company_home, board, systemctl):
    with (company_home / "ledger.jsonl").open("a") as file:
        file.write("not an event\n")

    assert company("schedule", "enable", "--message", "1234").returncode == 1
    assert turned_on(systemctl) == []


def test_a_second_enable_is_refused(company, board, systemctl):
    company("schedule", "enable", "--message", "1234")
    calls = len(systemctl.calls())

    done = company("schedule", "enable", "--message", "1234")

    assert done.returncode == 1
    assert "already on" in done.stderr
    assert "Nothing was turned on" in done.stderr
    assert len(systemctl.calls()) == calls
    assert len(events("schedule-enabled")) == 1


def test_nothing_but_enable_turns_a_timer_on(repo):
    # The one place in the package that names the verb, so no default or other path can.
    found = [path.name for path in (repo / "src/company").rglob("*.py") if '"enable", "--now"' in path.read_text()]
    assert found == ["schedule.py"]
    assert (repo / "src/company/schedule.py").read_text().count('"enable", "--now"') == 1


def test_disable_turns_every_timer_off_and_logs_it(company, board, systemctl):
    company("schedule", "enable", "--message", "1234")

    done = company("schedule", "disable", "--reason", "for now")

    assert done.returncode == 0, done.stdout + done.stderr
    assert systemctl.calls()[-1].startswith("--user disable --now")
    disabled = events("schedule-disabled")[-1]
    assert disabled["writer"] == "board"
    assert disabled["reason"] == "for now"
    assert company("schedule", "run", "kill-self-test").returncode == 1


def test_disable_turns_the_timers_off_even_on_a_broken_ledger(company, company_home, board, systemctl):
    company("schedule", "enable", "--message", "1234")
    with (company_home / "ledger.jsonl").open("a") as file:
        file.write("not an event\n")

    done = company("schedule", "disable")

    assert done.returncode == 1
    assert "the timers are off" in done.stderr
    assert systemctl.calls()[-1].startswith("--user disable --now")


# A scheduled session


@pytest.fixture
def session_on_schedule(company, stub):
    def run(*more):
        return company("session", "start", "probe", "--scheduled", *more)

    return run


def settings_and_reading(company):
    from usage_records import SETTINGS_INIT

    assert company(*SETTINGS_INIT).returncode == 0
    return week_reading()


def test_a_scheduled_session_is_refused_with_the_schedule_disabled(company, session_on_schedule, stub):
    settings_and_reading(company)

    done = session_on_schedule()

    assert done.returncode == 1
    assert "schedule-off" in done.stdout
    assert schedule.ENABLE in done.stdout
    refused = events("launch-refused")[-1]
    assert refused["check"] == "go"
    assert refused["reason"].startswith("schedule-off: ")
    assert stub.session_calls() == []


def test_a_scheduled_session_needs_no_word_with_the_schedule_enabled(company, session_on_schedule, stub, systemctl):
    settings_and_reading(company)
    assert company("schedule", "enable", "--message", "1234").returncode == 0
    assert events("go-given") == []
    stub.play()

    done = session_on_schedule()

    assert done.returncode == 0, done.stdout + done.stderr
    assert events("session-started")[-1]["gate"] == "schedule"
    assert len(stub.session_calls()) == 1


def test_a_session_by_hand_still_needs_a_word_with_the_schedule_enabled(company, stub, systemctl):
    settings_and_reading(company)
    assert company("schedule", "enable", "--message", "1234").returncode == 0

    done = company("session", "start", "probe")

    assert done.returncode == 1
    assert "no-go" in done.stdout


def test_a_scheduled_session_uses_up_no_word(company, session_on_schedule, stub, systemctl, board):
    assert company("schedule", "enable", "--message", "1234").returncode == 0
    stub.play()

    assert session_on_schedule().returncode == 0

    assert "10 real launches left" in company("governor", "check", "probe").stdout


def test_a_scheduled_session_is_refused_after_the_kill_switch(company, session_on_schedule, stub, systemctl):
    settings_and_reading(company)
    company("schedule", "enable", "--message", "1234")
    company("kill")
    company("resume")

    done = session_on_schedule()

    assert done.returncode == 1
    assert "schedule-off" in done.stdout


def test_the_governor_answers_for_a_scheduled_session(company, systemctl):
    settings_and_reading(company)
    assert company("governor", "check", "probe", "--scheduled").returncode == 1
    company("schedule", "enable", "--message", "1234")

    done = company("governor", "check", "probe", "--scheduled")

    assert done.returncode == 0, done.stdout
    assert "on the schedule" in done.stdout


# When the charge runs: review finding 33


def stamp(when):
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def end(session):
    Ledger().append("session-ended", {"session": session, "exit": 0, "transcript_path": "p", "transcript_hash": "h", "weight": 1.0}, "launcher")


def company_used_in_week(transcripts, session=ALPHA):
    earlier = datetime.now(UTC) - timedelta(minutes=5)
    transcripts.session(session, transcript_line(session, "r1", earlier.strftime("%Y-%m-%dT%H:%M:%S.000Z"), output=50_000))


@pytest.fixture
def on_schedule(company, systemctl, transcripts):
    assert company("schedule", "enable", "--message", "1234").returncode == 0


@pytest.fixture
def charge_job(company, board, on_schedule, transcripts):
    def run():
        done = company("schedule", "run", "treasurer-charge")
        assert done.returncode == 0, done.stdout + done.stderr
        return done

    return run


def test_the_charge_is_not_on_a_plain_daily_timer(repo):
    job = schedule.job("treasurer-charge")
    assert job.due is not None
    assert job.calendar != "daily"


def test_with_nothing_to_charge_the_job_writes_nothing(charge_job):
    before = events()

    done = charge_job()

    assert "not due" in done.stdout
    assert events() == before


def test_the_charge_runs_at_a_sessions_end(charge_job, board, transcripts):
    company_used_in_week(transcripts)
    start_session(ALPHA, "probe", board)
    assert "not due" in charge_job().stdout
    assert events("resource-charged") == []

    end(ALPHA)
    done = charge_job()

    assert "Charged" in done.stdout
    assert [event["line"] for event in events("resource-charged")] == ["overhead"]
    # That window's last session is now counted, so the next firing has nothing to do.
    before = events()
    assert "not due" in charge_job().stdout
    assert events() == before


def test_a_session_on_an_open_schedule_is_charged_as_it_ends_with_no_timer_firing(company, stub, board, on_schedule, transcripts):
    # A timer's next firing could fall after the window's reset, so the launcher does not leave this to the timer.
    # Weight up to the reading, or a reply that falls in a later second than the reading leaves the share unreadable.
    company_used_in_week(transcripts)
    stub.play({"do": "reply", "request": "r1", "output": 50_000})

    done = company("session", "start", "probe")

    assert done.returncode == 0, done.stdout + done.stderr
    started, charged = events("session-started")[-1], events("resource-charged")
    assert [event["line"] for event in charged] == ["overhead"]
    assert charged[-1]["seq"] > started["seq"]
    assert charged[-1]["seq"] > events("session-ended")[-1]["seq"]


def test_a_session_with_the_schedule_off_is_not_charged_as_it_ends(company, stub, board):
    stub.play({"do": "reply", "request": "r1", "output": 50_000})

    assert company("session", "start", "probe").returncode == 0

    assert events("resource-charged") == []


def test_the_charge_runs_for_a_session_stopped_as_well(charge_job, board, transcripts):
    company_used_in_week(transcripts)
    start_session(ALPHA, "probe", board)
    Ledger().append("session-stopped", {"session": ALPHA, "reason": "launcher-gone"}, "launcher")

    assert "Charged" in charge_job().stdout


def test_the_charge_runs_shortly_before_the_newest_readings_reset(charge_job, board, transcripts):
    company_used_in_week(transcripts)
    start_session(ALPHA, "probe", board)
    end(ALPHA)
    charge_job()
    newest = events("resource-charged")[-1]["seq"]
    earlier = datetime.now(UTC) - timedelta(minutes=4)
    # More use by the same session, with its end already charged, so only the reset can make a charge due.
    transcripts.session(ALPHA, transcript_line(ALPHA, "r1", (earlier - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z"), output=50_000), transcript_line(ALPHA, "r2", earlier.strftime("%Y-%m-%dT%H:%M:%S.000Z"), output=50_000))
    assert "not due" in charge_job().stdout

    now = datetime.now(UTC)
    record_reading("seven_day", 40, stamp(now + timedelta(minutes=10)), stamp(now))
    done = charge_job()

    assert "Charged" in done.stdout
    assert events("resource-charged")[-1]["seq"] > newest


def test_the_charge_is_not_due_after_the_reset(charge_job, board, transcripts):
    now = datetime.now(UTC)
    start_session(ALPHA, "probe", board)
    end(ALPHA)
    record_reading("seven_day", 40, stamp(now - timedelta(minutes=1)), stamp(now - timedelta(minutes=2)))

    assert "not due" in charge_job().stdout


def test_a_session_from_before_the_window_does_not_keep_the_charge_due(company, board, on_schedule, transcripts):
    start_session(ALPHA, "probe", board)
    end(ALPHA)
    # The next window's reading: the session ended now on the real clock, so its window must close before that.
    now = datetime.now(UTC)
    record_reading("seven_day", 40, stamp(now + timedelta(days=8)), stamp(now))

    done = company("schedule", "run", "treasurer-charge")

    assert "not due" in done.stdout


# A job that fails


def broken_stop(tmp_path, monkeypatch):
    """Every `company` from here on has a stop that does nothing, so that the kill switch's real self-test fails, and soon."""
    wrapper = tmp_path / "pythonpath" / "sitecustomize.py"
    wrapper.parent.mkdir()
    wrapper.write_text(
        f"import sys\nsys.path.insert(0, {os.environ['PYTHONPATH']!r})\n"
        "import audit_guard\naudit_guard.install_from_env()\n"
        "from company import kill_state, killswitch, launcher\n"
        "launcher.running_sessions = lambda: []\n"
        "kill_state.present = lambda: False\n"
        "killswitch._TEST_WAIT_SECONDS = 1\n"
    )
    monkeypatch.setenv("PYTHONPATH", str(wrapper.parent))


def digest_incidents(company):
    done = company("digest")
    assert done.returncode == 0, done.stderr
    return section(done.stdout, "Incidents")


def test_a_failed_self_test_on_the_schedule_is_in_the_real_ledger_and_the_digest(company, board, systemctl, tmp_path, monkeypatch):
    assert company("schedule", "enable", "--message", "1234").returncode == 0
    broken_stop(tmp_path, monkeypatch)

    done = company("schedule", "run", "kill-self-test")

    assert done.returncode == 1, done.stdout + done.stderr
    assert "FAILED" in done.stdout
    failed = events("job-failed")
    assert [(found["writer"], found["job"], found["exit"]) for found in failed] == [("scheduler", "kill-self-test", 1)]
    incidents = digest_incidents(company).splitlines()
    assert len(incidents) == 1
    assert "kill-self-test" in incidents[0]
    assert "1 time " in incidents[0]
    assert "journalctl --user -u company-kill-self-test" in incidents[0]


@pytest.fixture
def schedule_on(company, board, systemctl):
    assert company("schedule", "enable", "--message", "1234").returncode == 0


def test_a_job_that_refuses_is_a_job_that_failed(company, schedule_on):
    # A lock that cannot be opened stops the tick, which the command reports and refuses.
    (paths.home() / "paper.lock").mkdir()

    done = company("schedule", "run", "paper-tick")

    assert done.returncode == 1
    assert [found["job"] for found in events("job-failed")] == ["paper-tick"]


def test_a_job_that_raises_is_a_job_that_failed(company, schedule_on, tmp_path, monkeypatch):
    wrapper = tmp_path / "pythonpath" / "sitecustomize.py"
    wrapper.parent.mkdir()
    wrapper.write_text(
        f"import sys\nsys.path.insert(0, {os.environ['PYTHONPATH']!r})\n"
        "import audit_guard\naudit_guard.install_from_env()\n"
        "from company import killswitch\n"
        "def fail():\n    raise RuntimeError('a stand-in failure')\n"
        "killswitch.self_test = fail\n"
    )
    monkeypatch.setenv("PYTHONPATH", str(wrapper.parent))

    done = company("schedule", "run", "kill-self-test")

    assert done.returncode == 1
    assert "a stand-in failure" in done.stderr
    assert [(found["job"], found["exit"]) for found in events("job-failed")] == [("kill-self-test", 1)]


def test_a_job_that_passes_or_is_refused_records_no_failure(company, board, systemctl):
    assert company("schedule", "run", "kill-self-test").returncode == 1
    assert events("job-failed") == []
    assert company("schedule", "enable", "--message", "1234").returncode == 0
    assert company("schedule", "run", "kill-self-test").returncode == 0
    assert events("job-failed") == []
    assert company("kill").returncode == 0
    assert company("schedule", "run", "kill-self-test").returncode == 1
    assert events("job-failed") == []


def test_the_failures_of_one_job_read_as_one_line_and_only_for_the_week(company, schedule_on):
    now = datetime.now(UTC)
    for days in (9, 2, 1):
        ledger_at(stamp(now - timedelta(days=days))).append("job-failed", {"job": "paper-tick", "exit": days}, "scheduler")
    ledger_at(stamp(now - timedelta(days=1))).append("job-failed", {"job": "treasurer-charge", "exit": 1}, "scheduler")

    incidents = digest_incidents(company).splitlines()

    assert len(incidents) == 2
    assert "paper-tick" in incidents[0]
    assert "2 times " in incidents[0]
    assert "exit 1" in incidents[0]
    assert "treasurer-charge" in incidents[1]


def test_a_failure_the_ledger_cannot_take_says_so_and_the_job_still_fails(company, schedule_on, tmp_path, monkeypatch):
    wrapper = tmp_path / "pythonpath" / "sitecustomize.py"
    wrapper.parent.mkdir()
    wrapper.write_text(
        f"import sys\nsys.path.insert(0, {os.environ['PYTHONPATH']!r})\n"
        "import audit_guard\naudit_guard.install_from_env()\n"
        "from company import killswitch, ledger\n"
        "def cut():\n    (ledger.paths.home() / 'ledger.head').unlink()\n    return [killswitch.Check('a stand-in check', False, 'it failed')]\n"
        "killswitch.self_test = cut\n"
    )
    monkeypatch.setenv("PYTHONPATH", str(wrapper.parent))
    before = len(events())

    done = company("schedule", "run", "kill-self-test")

    assert done.returncode == 1
    assert "could not record it" in done.stderr
    assert len((paths.home() / "ledger.jsonl").read_text().splitlines()) == before
