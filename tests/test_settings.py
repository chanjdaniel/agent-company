"""Daniel's settings: `company settings init` and `set`, and `load()`, which refuses a file changed any other way."""

import json
import stat
import threading

import pytest
from usage_records import SETTINGS_INIT as INIT

from company import settings as settings_module
from company.ledger import Ledger


@pytest.fixture
def settings_file(tmp_path):
    return tmp_path / "company-config" / "settings.json"


@pytest.fixture
def started(company):
    result = company(*INIT)
    assert result.returncode == 0, result.stderr


def kinds(kind):
    return [event for event in Ledger().read() if event["kind"] == kind]


# company settings init


def test_init_writes_what_daniel_gave_and_what_the_design_sets(company, settings_file):
    result = company(*INIT)

    assert result.returncode == 0, result.stderr
    written = json.loads(settings_file.read_text())
    assert written["company_share"] == 0.25
    assert written["team_floor"] == 60
    assert written["monthly_price"] == 130
    assert written["plan_name"] == "a-plan"
    assert written["reading_max_age_minutes"] == 120
    assert written["session_max_minutes"] == 60
    assert written["session_max_weight"] == 20
    # The numbers the design records, each Daniel's to change.
    assert written["cell_model"] == "claude-opus-5-5"
    assert written["auditor_model"] == "claude-sonnet-5-5"
    assert written["backtest_max_seconds"] == 60
    assert written["daily_minutes"] == 15
    assert written["minutes_table"] == {"templated-approval": 0.5, "message-review": 2, "message-send": 0.5, "new-public-artifact": 5}
    assert written["complaint_threshold"] == {"count": 2, "days": 30, "outside_action_fraction": 0.02}
    assert written["portfolio"] == {
        "exploration_floor": 0.1,
        "holdout_share": 0.1,
        "new_bet_token_share": 0.1,
        "new_bet_minutes": 15,
        "new_bet_dollars": 0,
        "new_bet_weeks": 4,
        "closure_kills": 2,
        "margin_lookback_weeks": 4,
    }
    assert written["usage_day_dirs"] == []
    assert written["outside_accounts"] == []
    assert "weekly_send_cap" not in written


def test_only_the_owner_can_touch_the_file(company, settings_file, started):
    assert stat.S_IMODE(settings_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(settings_file.parent.stat().st_mode) == 0o700


def test_init_logs_the_keys_and_the_digest_and_no_value_as_board(company, settings_file, started):
    event = kinds("settings-changed")[-1]

    assert event["writer"] == "board"
    assert event["digest"] == settings_module.digest_of(settings_file.read_bytes())
    assert "company_share" in event["keys"]
    assert "a-plan" not in json.dumps(event)
    assert "message" not in event


def test_init_holds_the_message_it_is_given(company):
    assert company(*INIT, "--message", "1234").returncode == 0

    assert kinds("settings-changed")[-1]["message"] == "1234"


@pytest.mark.parametrize("flag", ["--company-share", "--team-floor", "--monthly-price", "--plan-name"])
def test_init_compiles_in_no_value_daniel_must_give(company, settings_file, flag):
    args = list(INIT)
    at = args.index(flag)
    del args[at : at + 2]

    result = company(*args)

    assert result.returncode == 2
    assert flag in result.stderr
    assert not settings_file.exists()
    assert Ledger().read() == []


@pytest.mark.parametrize(
    ("flag", "value", "named"),
    [
        ("--company-share", "25", "company_share"),
        ("--company-share", "0", "company_share"),
        ("--team-floor", "150", "team_floor"),
        ("--team-floor", "-1", "team_floor"),
        ("--team-floor", "sixty", "team_floor"),
        ("--monthly-price", "0", "monthly_price"),
        ("--monthly-price", "1e999", "monthly_price"),
        ("--plan-name", "7", "plan_name"),
        ("--cell-model", "", "cell_model"),
        ("--reading-max-age-minutes", "NaN", "reading_max_age_minutes"),
    ],
)
def test_init_refuses_a_value_that_cannot_be_right_and_writes_nothing(company, settings_file, flag, value, named):
    result = company(*INIT, flag, value)

    assert result.returncode == 1
    assert named in result.stderr
    assert "Nothing was changed" in result.stderr
    assert not settings_file.exists()
    assert kinds("settings-changed") == []


def test_a_second_init_is_refused_since_set_changes_a_good_file(company, settings_file, started):
    before = settings_file.read_bytes()

    result = company(*INIT, "--team-floor", "10")

    assert result.returncode == 1
    assert "company settings set" in result.stderr
    assert settings_file.read_bytes() == before
    assert len(kinds("settings-changed")) == 1


def test_a_bad_message_leaves_the_file_as_it_was(company, settings_file, started):
    before = settings_file.read_bytes()

    result = company("settings", "set", "team_floor", "50", "--message", "not-digits")

    assert result.returncode == 1
    assert settings_file.read_bytes() == before
    assert len(kinds("settings-changed")) == 1
    assert kinds("append-refused")[-1]["reason"] == "bad-field:message"
    assert list(settings_file.parent.glob("*.new")) == []


def test_a_broken_ledger_changes_no_settings(company, company_home, settings_file, started):
    before = settings_file.read_bytes()
    ledger = company_home / "ledger.jsonl"
    ledger.write_bytes(ledger.read_bytes()[:-5])

    for args in (("settings", "set", "team_floor", "50"), INIT):
        result = company(*args)

        assert result.returncode == 1
        assert "LEDGER BROKEN" in result.stdout
        assert settings_file.read_bytes() == before


# company settings set


@pytest.mark.parametrize(
    ("key", "text", "value"),
    [
        ("company_share", "0.3", 0.3),
        ("team_floor", "0", 0),
        ("team_floor", "100", 100),
        ("plan_name", "another plan", "another plan"),
        ("weekly_send_cap", "0", 0),
        ("usage_day_dirs", '["/some/usage"]', ["/some/usage"]),
        ("minutes_table", '{"message-review": 3}', {"message-review": 3}),
    ],
)
def test_set_changes_one_key_and_logs_it_as_board_with_the_new_digest(company, settings_file, started, key, text, value):
    result = company("settings", "set", key, text)

    assert result.returncode == 0, result.stderr
    assert key in result.stdout
    assert json.loads(settings_file.read_text())[key] == value
    event = kinds("settings-changed")[-1]
    assert event["writer"] == "board"
    assert event["keys"] == [key]
    assert event["digest"] == settings_module.digest_of(settings_file.read_bytes())


@pytest.mark.parametrize(
    ("key", "text"),
    [
        ("company_share", "25"),
        ("company_share", "0"),
        ("team_floor", "100.5"),
        ("team_floor", "-0.1"),
        ("team_floor", "true"),
        ("monthly_price", "1e999"),
        ("weekly_send_cap", "1.5"),
        ("weekly_send_cap", "-1"),
        ("minutes_table", '{"message-review": -3}'),
        ("portfolio", '{"holdout_share": 0.1}'),
        ("complaint_threshold", "2"),
        ("usage_day_dirs", "a-string"),
        ("outside_accounts", "a-string"),
        ("no_such_setting", "1"),
    ],
)
def test_set_refuses_what_cannot_be_right_and_changes_nothing(company, settings_file, started, key, text):
    before = settings_file.read_bytes()

    result = company("settings", "set", key, text)

    assert result.returncode == 1
    assert key in result.stderr
    assert "Nothing was changed" in result.stderr
    assert settings_file.read_bytes() == before
    assert len(kinds("settings-changed")) == 1


def test_set_with_no_settings_says_to_init(company, settings_file):
    result = company("settings", "set", "team_floor", "50")

    assert result.returncode == 1
    assert "company settings init" in result.stderr
    assert not settings_file.exists()


def test_set_on_a_changed_file_is_refused_since_it_would_bless_the_change(company, settings_file, started):
    edited = settings_file.read_text().replace('"team_floor": 60', '"team_floor": 99')
    settings_file.write_text(edited)

    result = company("settings", "set", "plan_name", "another")

    assert result.returncode == 1
    assert "company settings init" in result.stderr
    assert settings_file.read_text() == edited
    assert len(kinds("settings-changed")) == 1
    assert len(kinds("settings-tamper")) == 1


# load()


def test_load_returns_the_file_as_the_commands_wrote_it(company, started):
    assert settings_module.load()["team_floor"] == 60


def test_load_with_no_settings_and_no_digest_refuses_and_logs_nothing():
    with pytest.raises(settings_module.SettingsRefused) as refused:
        settings_module.load()

    assert refused.value.fix == "company settings init"
    assert Ledger().read() == []


def test_an_edit_outside_the_commands_is_refused_and_logged(company, settings_file, started):
    recorded = kinds("settings-changed")[-1]["digest"]
    settings_file.write_text(settings_file.read_text().replace('"company_share": 0.25', '"company_share": 1'))

    with pytest.raises(settings_module.SettingsTampered) as refused:
        settings_module.load()

    assert refused.value.fix == "company settings init"
    event = kinds("settings-tamper")[-1]
    assert event["writer"] == "governor"
    assert event["expected_digest"] == recorded
    assert event["found_digest"] == settings_module.digest_of(settings_file.read_bytes())


def test_a_file_removed_outside_the_commands_is_tamper(company, settings_file, started):
    recorded = kinds("settings-changed")[-1]["digest"]
    settings_file.unlink()

    with pytest.raises(settings_module.SettingsTampered):
        settings_module.load()

    event = kinds("settings-tamper")[-1]
    assert event["expected_digest"] == recorded
    assert event["found_digest"] == "none"


def test_a_file_no_command_ever_wrote_is_tamper(settings_file):
    settings_file.parent.mkdir()
    settings_file.write_text('{"company_share": 1, "team_floor": 100}')

    with pytest.raises(settings_module.SettingsTampered):
        settings_module.load()

    event = kinds("settings-tamper")[-1]
    assert event["expected_digest"] == "none"
    assert event["found_digest"] == settings_module.digest_of(settings_file.read_bytes())


def test_a_reader_that_promises_to_write_nothing_is_refused_with_nothing_logged(company, settings_file, started):
    settings_file.write_text("{}")

    with pytest.raises(settings_module.SettingsTampered):
        settings_module.load(log_tamper=False)

    assert kinds("settings-tamper") == []


def test_tamper_still_refuses_when_the_ledger_cannot_take_the_event(company, company_home, settings_file, started):
    settings_file.write_text("{}")
    (company_home / "ledger.head").write_text("not a head record")
    before = (company_home / "ledger.jsonl").read_bytes()

    with pytest.raises(settings_module.SettingsTampered):
        settings_module.load()

    assert (company_home / "ledger.jsonl").read_bytes() == before


def test_a_config_that_cannot_be_read_refuses(company, settings_file, started):
    settings_file.unlink()
    settings_file.mkdir()

    with pytest.raises(settings_module.SettingsRefused) as refused:
        settings_module.load()

    assert "cannot be read" in str(refused.value)


def test_init_recovers_from_tamper_with_a_whole_new_file(company, settings_file, started):
    settings_file.write_text('{"company_share": 1}')

    result = company(*INIT, "--team-floor", "50")

    assert result.returncode == 0, result.stderr
    assert len(kinds("settings-tamper")) == 1
    assert settings_module.load()["team_floor"] == 50
    assert settings_module.load()["company_share"] == 0.25


def test_a_load_during_a_set_never_reads_as_tamper(company, started):
    # The digest goes in the ledger just before the file moves into place, so without a lock a load can fall between.
    done = threading.Event()
    wrong = []

    def load_until_done():
        while not done.is_set():
            try:
                settings_module.load()
            except settings_module.SettingsRefused as refused:
                wrong.append(str(refused))

    reader = threading.Thread(target=load_until_done)
    reader.start()
    for number in range(40):
        settings_module.set_value("daily_minutes", str(number + 1))
    done.set()
    reader.join()

    assert wrong == []
    assert kinds("settings-tamper") == []


def test_every_setting_the_file_may_hold_has_its_check():
    assert set(settings_module.KEYS) == {
        "company_share", "team_floor", "monthly_price", "plan_name", "cell_model", "auditor_model",
        "reading_max_age_minutes", "session_max_minutes", "session_max_weight", "backtest_max_seconds", "daily_minutes", "weekly_send_cap",
        "minutes_table", "complaint_threshold", "portfolio", "outside_accounts", "usage_day_dirs",
    }  # fmt: skip


def test_no_value_reaches_the_ledger(company, started):
    assert all("0.25" not in json.dumps(event) for event in Ledger().read())
