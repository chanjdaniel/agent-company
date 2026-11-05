"""`company preflight`: each of Daniel's steps from S3 to S7, passed or open with what closes it, on the installed command."""

import json
import os
import re
from datetime import timedelta

import pytest
from session_checks import events, patch_every_company
from usage_records import (
    SETTINGS_INIT,
    TEAM,
    record_reading,
    transcript_line,
    week_reading,
)

from company import banned, paths, settings, times


def stamp_now():
    return times.now().strftime("%Y-%m-%dT%H:%M:%S.000Z")


def write_key(text="PKDECOY\nsecret-decoy\n", mode=0o600):
    path = paths.paper_key()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)
    return path


def section(text, step):
    """One step's lines of the report."""
    found = re.search(rf"^{step} (?:passed|OPEN):.*(?:\n  .*)*", text, re.MULTILINE)
    assert found, text
    return found[0]


@pytest.fixture
def ready(company, stub, board):
    """Every step closed: settings and a go and a reading from `board`, a key file, and Daniel's check of the account."""
    write_key()
    done = company("account", "checked")
    assert done.returncode == 0, done.stderr


@pytest.fixture
def preflight(company):
    return lambda: company("preflight")


def is_open(done, step, *words):
    assert done.returncode == 1, done.stdout
    found = section(done.stdout, step)
    assert found.startswith(f"{step} OPEN"), found
    assert "To close it:" in found, found
    for word in words:
        assert word in found, found
    assert f"Preflight is open: {step}." in done.stdout, done.stdout


def test_with_every_step_done_it_passes(ready, preflight):
    done = preflight()
    assert done.returncode == 0, done.stdout
    for step in ("S3", "S4", "S5", "S6", "S7"):
        assert section(done.stdout, step).startswith(f"{step} passed")
    assert done.stdout.splitlines()[-1] == "Preflight passes: every step from S3 to S7 is done."


def test_on_a_new_home_it_lists_each_step_open_with_its_command(stub, preflight):
    done = preflight()
    assert done.returncode == 1
    assert "install -m 600 /dev/null" in section(done.stdout, "S3")
    assert "company settings init" in section(done.stdout, "S4")
    assert "company account checked" in section(done.stdout, "S5")
    assert "company settings init" in section(done.stdout, "S6")
    assert "company go real-sessions --message <Discord id> --sessions <n>" in section(done.stdout, "S7")
    assert "Preflight is open: S3, S4, S5, S6, S7." in done.stdout


def test_it_writes_nothing(ready, preflight):
    before = events()
    assert preflight().returncode == 0
    assert events() == before


def test_a_missing_key_leaves_s3_open(ready, preflight):
    paths.paper_key().unlink()
    is_open(preflight(), "S3", "there is no paper key", "install -m 600 /dev/null")


def test_a_key_others_can_reach_leaves_s3_open_and_names_chmod(ready, preflight):
    write_key(mode=0o640)
    is_open(preflight(), "S3", "chmod 600")


def test_an_empty_key_leaves_s3_open(ready, preflight):
    write_key(text="")
    is_open(preflight(), "S3", "is empty", "your editor")


def test_a_link_for_a_key_leaves_s3_open(ready, preflight, tmp_path):
    real = tmp_path / "elsewhere"
    real.write_text("PKDECOY\nsecret-decoy\n")
    real.chmod(0o600)
    paths.paper_key().unlink()
    paths.paper_key().symlink_to(real)
    is_open(preflight(), "S3", "is not a file", "plain file")


def test_a_key_of_someone_elses_leaves_s3_open_and_chmod_is_not_the_fix(ready, preflight, tmp_path, monkeypatch):
    patch_every_company(tmp_path, monkeypatch, "import os", "_real = os.getuid()", "os.getuid = lambda: _real + 1")
    done = preflight()
    assert "belongs to someone else" in done.stdout
    assert "plain file of your own" in section(done.stdout, "S3")
    assert "chmod" not in section(done.stdout, "S3")


def test_a_directory_for_a_key_leaves_s3_open(ready, preflight):
    paths.paper_key().unlink()
    paths.paper_key().mkdir()
    is_open(preflight(), "S3", "is not a file")


def test_a_list_that_would_not_rotate_the_key_leaves_s3_open(ready, preflight, company):
    assert company("settings", "set", "outside_accounts", "[]").returncode == 0
    is_open(preflight(), "S3", "outside_accounts", json.dumps(settings.PAPER_ACCOUNTS))


def test_it_never_opens_the_key(ready, preflight, tmp_path, monkeypatch):
    """Not by its contents in the output: by the interpreter's own record of what the command opened."""
    log = tmp_path / "opened"
    patch_every_company(
        tmp_path,
        monkeypatch,
        "import sys",
        f"def _note(event, args):\n    if event == 'open' and str(args[0]).endswith('paper.key'):\n        open({str(log)!r}, 'a').write(str(args[0]) + chr(10))",
        "sys.addaudithook(_note)",
    )
    done = preflight()
    assert done.returncode == 0, done.stdout + done.stderr
    assert "secret-decoy" not in done.stdout + done.stderr
    assert not log.exists()


def test_a_key_of_nothing_but_garbage_passes_since_it_is_never_read(ready, preflight):
    write_key(text="not a key at all")
    assert preflight().returncode == 0


def test_settings_changed_by_hand_leave_s4_open_and_are_not_logged(ready, preflight):
    path = paths.config() / "settings.json"
    path.write_text(path.read_text().replace("0.25", "0.9"))
    before = events()
    done = preflight()
    assert done.returncode == 1
    found = section(done.stdout, "S4")
    assert "S4 OPEN" in found
    assert "tampered" in found
    assert "company settings init" in found
    assert events() == before


def test_a_claude_that_lacks_a_flag_leaves_s4_open(ready, preflight, stub):
    stub.play(help_lacks=["--restricted"])
    is_open(preflight(), "S4", "no-load-form", "--restricted")


def test_no_claude_at_all_leaves_s4_open(ready, preflight, monkeypatch, tmp_path):
    monkeypatch.setenv("COMPANY_CLAUDE_BIN", str(tmp_path / "no-such-file"))
    is_open(preflight(), "S4", "no-load-form", "Claude Code")


@pytest.mark.parametrize("tool", ["bwrap", "socat"])
def test_a_missing_sandbox_tool_leaves_s4_open(ready, preflight, tool, tmp_path, monkeypatch):
    other = "socat" if tool == "bwrap" else "bwrap"
    shelf = tmp_path / "bin"
    shelf.mkdir()
    (shelf / other).write_text("#!/bin/sh\n")
    (shelf / other).chmod(0o755)
    patch_every_company(tmp_path, monkeypatch, "import company.launcher", f"company.launcher.CHILD_PATH = {str(shelf)!r}")
    is_open(preflight(), "S4", f"`{tool}` is not on a session's path", "package manager")


def test_the_sandbox_tools_are_looked_for_on_a_sessions_own_path(ready, preflight, tmp_path, monkeypatch):
    """A tool on this shell's path alone is one a session would not find, and this shell has both."""
    empty = tmp_path / "empty"
    empty.mkdir()
    patch_every_company(tmp_path, monkeypatch, "import company.launcher", f"company.launcher.CHILD_PATH = {str(empty)!r}")
    done = preflight()
    assert "`bwrap` is not on a session's path" in done.stdout
    assert "`socat` is not on a session's path" in done.stdout


@pytest.mark.parametrize("name", [banned.VARIABLES[0], banned.VARIABLES[-1], "ANTHROPIC_" + "SOMETHING_NEW", "APCA_" + "ANYTHING"])
def test_a_banned_variable_leaves_s4_open_and_names_it_and_not_its_value(ready, preflight, monkeypatch, name):
    """The list is `banned.py`'s: a name no list here holds, under its prefix, is caught the same."""
    monkeypatch.setenv(name, "a-decoy-value")
    done = preflight()
    is_open(done, "S4", f"`{name}`", f"unset {name}")
    assert "a-decoy-value" not in done.stdout


def test_no_check_of_the_account_leaves_s5_open(stub, company, board, preflight):
    write_key()
    is_open(preflight(), "S5", "extra usage", "Dependencies to re-check", "company account checked")


def test_a_check_stands_for_the_go_after_it(stub, company, usage_ready):
    assert company("account", "checked").returncode == 0
    assert company("go", "real-sessions", "--message", "1", "--sessions", "1").returncode == 0
    assert section(company("preflight").stdout, "S5").startswith("S5 passed")


def test_a_second_go_with_no_check_since_the_first_leaves_s5_open(stub, company, usage_ready):
    assert company("account", "checked").returncode == 0
    assert company("go", "real-sessions", "--message", "1", "--sessions", "1").returncode == 0
    assert company("go", "real-sessions", "--message", "2", "--sessions", "1").returncode == 0
    assert section(company("preflight").stdout, "S5").startswith("S5 OPEN")
    assert company("account", "checked").returncode == 0
    assert section(company("preflight").stdout, "S5").startswith("S5 passed")


def test_a_word_used_up_needs_a_new_check_before_the_next_go(stub, company, usage_ready):
    assert company("account", "checked").returncode == 0
    assert company("go", "real-sessions", "--message", "1", "--sessions", "1").returncode == 0
    stub.play()
    assert company("session", "start", "probe").returncode == 0
    done = company("preflight")
    assert section(done.stdout, "S5").startswith("S5 OPEN")
    assert section(done.stdout, "S7").startswith("S7 OPEN")


@pytest.fixture
def usage_ready(company):
    """Daniel's settings and a reading, with no go and no check yet."""
    assert company(*SETTINGS_INIT).returncode == 0
    week_reading()
    write_key()


def test_a_word_of_the_account_is_refused_inside_a_session(company, usage_ready):
    done = company("account", "checked", env={**os.environ, "COMPANY_SESSION": "not-a-session"})
    assert done.returncode == 1
    assert not events("account-checked")


def test_no_reading_leaves_s6_open_and_names_its_command(stub, company, preflight):
    assert company(*SETTINGS_INIT).returncode == 0
    write_key()
    assert company("account", "checked").returncode == 0
    assert company("go", "real-sessions", "--message", "1", "--sessions", "1").returncode == 0
    is_open(preflight(), "S6", "no-reading", "company reading record")


def test_a_stale_reading_leaves_s6_open(ready, preflight):
    now = times.now()
    record_reading("seven_day", 40, times.stamp(now + timedelta(hours=72)), times.stamp(now - timedelta(hours=3)))
    is_open(preflight(), "S6", "stale", "company reading record")


def test_an_account_past_the_floor_leaves_s6_open(ready, preflight):
    week_reading(used_percent=70)
    is_open(preflight(), "S6", "above-floor")


def test_a_company_past_its_share_leaves_s6_open(ready, preflight, company, transcripts):
    done = company("session", "start", "probe")
    assert done.returncode == 0, done.stdout
    session = events("session-started")[-1]["session"]
    transcripts.session(session, transcript_line(session, "r1", stamp_now(), output=5_000_000), project="-a-company-session")
    week_reading(used_percent=40)
    is_open(preflight(), "S6", "share-used")


def test_a_team_only_week_is_no_problem_for_the_share(ready, preflight, transcripts):
    transcripts.session(TEAM, transcript_line(TEAM, "t1", stamp_now(), output=5_000_000))
    week_reading(used_percent=40)
    assert preflight().returncode == 0


def test_no_go_leaves_s7_open_and_names_its_command(stub, company, usage_ready, preflight):
    assert company("account", "checked").returncode == 0
    is_open(preflight(), "S7", "no go-given word", "company go real-sessions")


def test_the_kill_switch_pulled_leaves_s7_open_and_names_the_resume(ready, preflight, company, systemctl):
    assert company("kill", "--reason", "a test").returncode == 0
    write_key()
    done = preflight()
    assert done.returncode == 1
    found = section(done.stdout, "S7")
    assert "S7 OPEN" in found
    assert "company resume" in found


def test_a_broken_ledger_says_so_and_lists_nothing(ready, preflight):
    path = paths.home() / "ledger.jsonl"
    lines = path.read_text().splitlines()
    path.write_text("\n".join(["{}", *lines[1:]]) + "\n")
    done = preflight()
    assert done.returncode == 1
    assert "LEDGER BROKEN" in done.stdout
    assert "Preflight" not in done.stdout
