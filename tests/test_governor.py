"""`company governor check`: admitted or refused from Daniel's settings, the reading and the ledger.

Each test runs the installed command against the real clock, so its readings and replies are set relative to now.
Weights: a reply of 5,000,000 output tokens on Opus weighs 100, as `usage_records` says.
"""

from datetime import UTC, datetime, timedelta

import pytest
from usage_records import (
    ALPHA,
    BETA,
    TEAM,
    record_reading,
    start_session,
    transcript_line,
)
from usage_records import SETTINGS_INIT as INIT

from company.ledger import Ledger

FIX_READING = "company reading record"


def stamp(when):
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def ago(minutes=0):
    return stamp(datetime.now(UTC) - timedelta(minutes=minutes))


def ahead(hours):
    return stamp(datetime.now(UTC) + timedelta(hours=hours))


def reply(session, request, minutes_ago, weight):
    when = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    return transcript_line(session, request, when.strftime("%Y-%m-%dT%H:%M:%S.000Z"), output=weight * 50_000)


def week_reading(used_percent=40, taken_minutes_ago=0):
    return record_reading("seven_day", used_percent, ahead(72), ago(taken_minutes_ago))


def five_hour_reading(used_percent=40, taken_minutes_ago=0):
    return record_reading("five_hour", used_percent, ahead(2), ago(taken_minutes_ago))


def events(kind):
    return [event for event in Ledger().read() if event["kind"] == kind]


def go(company, sessions=3, message="1234"):
    result = company("go", "real-sessions", "--message", message, "--sessions", str(sessions))
    assert result.returncode == 0, result.stderr
    return events("go-given")[-1]["seq"]


def launch(go_seq, session=TEAM):
    """What the launcher writes for a launch it was admitted to, which is what uses a word up."""
    fields = {
        "session": session,
        "role": "probe",
        "model": "m",
        "run": "r",
        "gate": f"go:{go_seq}",
        "account_used": 0,
        "company_used": 0,
        "reading_seq": events("usage-reading")[-1]["seq"],
    }
    Ledger().append("session-started", fields, "launcher")


@pytest.fixture
def check(company, transcripts):
    """`company governor check`, with this test's own transcripts."""

    def run(role="probe", bet=None):
        return company("governor", "check", role, *(("--bet", bet) if bet else ()))

    return run


@pytest.fixture
def board(company):
    """Daniel has set the share at 25% and the floor at 60%, and given a go for three launches."""
    result = company(*INIT)
    assert result.returncode == 0, result.stderr
    return go(company)


@pytest.fixture
def ready(board):
    """As `board`, with a reading of 40% just taken, and so nothing in the way."""
    return week_reading()


def assert_refused(result, check, reason):
    """The launch was refused, the command says why, and the ledger holds the same."""
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Admitted" not in result.stdout
    assert "Refused" in result.stdout
    assert reason in result.stdout
    event = events("launch-refused")[-1]
    assert event["writer"] == "governor"
    assert event["check"] == check
    assert event["reason"].startswith(reason)
    assert event["fix"] in result.stdout
    assert f"Event {event['seq']}" in result.stdout
    return event


# Admitted


def test_with_everything_in_order_a_launch_is_admitted_and_nothing_is_written(check, ready):
    before = Ledger().read()

    result = check()

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Admitted" in result.stdout
    assert "go:" in result.stdout
    assert "seven_day" in result.stdout
    assert "40.00%" in result.stdout
    assert Ledger().read() == before


def test_a_reading_with_no_five_hour_window_is_not_a_refusal(check, ready):
    assert events("usage-reading")[-1]["window"] == "seven_day"

    result = check()

    assert result.returncode == 0, result.stdout
    assert "five_hour: no reading" in result.stdout


# The share


def test_a_used_share_refuses_with_the_share_and_the_reading_it_came_from(check, board, transcripts):
    # The account reads 50%, under the floor. The company has 60 of the window's 100 of weight,
    # so its fraction is 0.6, and it has used 0.6 x 50 = 30%, at or past 25%.
    start_session(ALPHA, "cell", week_reading(50), bet="alpha")
    transcripts.session(ALPHA, reply(ALPHA, "a", 60, 60))
    transcripts.session(TEAM, reply(TEAM, "b", 60, 40))
    reading_seq = week_reading(50)

    result = check("cell", "alpha")

    event = assert_refused(result, "share", "share-used")
    assert event["role"] == "cell"
    assert event["bet"] == "alpha"
    assert event["account_used"] == pytest.approx(50)
    assert event["company_used"] == pytest.approx(30)
    assert event["reading_seq"] == reading_seq


def test_a_share_used_exactly_refuses(check, board, transcripts):
    # 50 of 100 of weight at 50% is 25%, which is not under 25%.
    start_session(ALPHA, "cell", week_reading(50), bet="alpha")
    transcripts.session(ALPHA, reply(ALPHA, "a", 60, 50))
    transcripts.session(TEAM, reply(TEAM, "b", 60, 50))
    week_reading(50)

    assert_refused(check("cell", "alpha"), "share", "share-used")


def test_a_share_with_room_admits(check, board, transcripts):
    # 49 of 100 of weight at 50% is 24.5%.
    start_session(ALPHA, "cell", week_reading(50), bet="alpha")
    transcripts.session(ALPHA, reply(ALPHA, "a", 60, 49))
    transcripts.session(TEAM, reply(TEAM, "b", 60, 51))
    week_reading(50)

    assert check("cell", "alpha").returncode == 0


def test_the_share_applies_to_the_five_hour_window_too(check, board, transcripts):
    # The week: 60 of the company's weight in 1,000, at 50%, is 3%, with room.
    # The five hours hold only the last hour's 100, of which 60 is the company's: at 50% that is 30%.
    start_session(ALPHA, "cell", week_reading(50), bet="alpha")
    transcripts.session(ALPHA, reply(ALPHA, "a", 60, 60))
    transcripts.session(TEAM, reply(TEAM, "b", 60, 40), reply(TEAM, "c", 60 * 24 * 2, 900))
    week_reading(50)
    reading_seq = five_hour_reading(50)

    event = assert_refused(check("cell", "alpha"), "share", "share-used")

    assert event["company_used"] == pytest.approx(30)
    assert event["reading_seq"] == reading_seq
    assert "five_hour" in event["reason"]


def test_a_new_share_reads_at_the_next_launch(company, check, board, transcripts):
    # 30 of 100 of weight at 40% is 12%: room under 25%, and none under 10%.
    start_session(ALPHA, "cell", week_reading(), bet="alpha")
    transcripts.session(ALPHA, reply(ALPHA, "a", 60, 30))
    transcripts.session(TEAM, reply(TEAM, "b", 60, 70))
    week_reading()
    assert check("cell", "alpha").returncode == 0

    assert company("settings", "set", "company_share", "0.1").returncode == 0

    assert_refused(check("cell", "alpha"), "share", "share-used")


# The floor


def test_the_account_above_the_floor_refuses_even_with_the_share_having_room(check, board, transcripts):
    # The account reads 70%, past the floor of 60%. The company has none of its weight, so its share has room.
    transcripts.session(TEAM, reply(TEAM, "b", 60, 100))
    reading_seq = week_reading(70)

    event = assert_refused(check(), "floor", "above-floor")

    assert event["account_used"] == pytest.approx(70)
    assert event["company_used"] == pytest.approx(0)
    assert event["reading_seq"] == reading_seq


def test_the_account_exactly_at_the_floor_refuses(check, board):
    week_reading(60)

    assert_refused(check(), "floor", "above-floor")


def test_the_use_since_the_reading_counts_towards_the_floor(check, board, transcripts):
    # Up to the reading: 100 of weight at 58%. Since: 5, which is 5 x 58 / 100 = 2.9 percent. So 60.9%.
    transcripts.session(TEAM, reply(TEAM, "a", 60, 100), reply(TEAM, "b", 10, 5))
    week_reading(58, taken_minutes_ago=30)

    event = assert_refused(check(), "floor", "above-floor")

    assert event["account_used"] == pytest.approx(60.9)


def test_the_floor_applies_to_the_five_hour_window_too(check, board):
    week_reading(40)
    reading_seq = five_hour_reading(70)

    event = assert_refused(check(), "floor", "above-floor")

    assert event["reading_seq"] == reading_seq
    assert "five_hour" in event["reason"]


def test_a_new_floor_reads_at_the_next_launch(company, check, board):
    week_reading(50)
    assert check().returncode == 0

    assert company("settings", "set", "team_floor", "45").returncode == 0

    assert_refused(check(), "floor", "above-floor")


# The reading


def no_reading(window, transcripts):
    pass


def stale(window, transcripts):
    record_reading(window, 40, ahead(1), ago(121))


def window_reset(window, transcripts):
    record_reading(window, 40, ago(60), ago(90))


def malformed(window, transcripts):
    record_reading(window, 150, ahead(1), ago())


def zero_percent(window, transcripts):
    transcripts.session(TEAM, reply(TEAM, "since", 10, 5))
    record_reading(window, 0, ahead(1), ago(30))


def no_weight(window, transcripts):
    transcripts.session(TEAM, reply(TEAM, "since", 10, 5))
    record_reading(window, 40, ahead(1), ago(30))


def read_error(window, transcripts):
    record_reading(window, 40, ahead(1), ago())
    (transcripts.projects / "-some-project" / "unreadable.jsonl").mkdir(parents=True)


@pytest.mark.parametrize(
    ("make", "reason"),
    [
        (no_reading, "no-reading"),
        (stale, "stale"),
        (window_reset, "window-reset"),
        (malformed, "malformed"),
        (zero_percent, "zero-percent"),
        (no_weight, "no-weight"),
        (read_error, "read-error"),
    ],
)
def test_a_week_that_cannot_be_read_refuses_with_its_reason_and_its_fix(check, board, transcripts, make, reason):
    make("seven_day", transcripts)

    event = assert_refused(check(), "reading", reason)

    assert event["fix"] == FIX_READING
    assert "account_used" not in event


@pytest.mark.parametrize(
    ("make", "reason"),
    [
        (stale, "stale"),
        (window_reset, "window-reset"),
        (malformed, "malformed"),
        (zero_percent, "zero-percent"),
        (no_weight, "no-weight"),
    ],
)
def test_a_five_hour_reading_that_cannot_be_read_refuses_too(check, board, transcripts, make, reason):
    make("five_hour", transcripts)
    week_reading()

    event = assert_refused(check(), "reading", reason)

    assert event["fix"] == FIX_READING
    assert event["reading_seq"] == events("usage-reading")[0]["seq"]
    assert "five_hour" in event["reason"]


# The settings


def test_with_no_settings_every_launch_is_refused(check):
    week_reading()

    event = assert_refused(check(), "settings", "missing")

    assert event["fix"] == "company settings init"


@pytest.mark.parametrize("key", ["company_share", "team_floor", "monthly_price", "reading_max_age_minutes"])
def test_a_setting_missing_from_the_file_refuses_and_is_named(check, settings, key):
    settings(**{"company_share": 0.25, "team_floor": 60, key: None})
    week_reading()

    event = assert_refused(check(), "settings", "unusable")

    assert key in event["reason"]
    assert event["fix"] == "company settings set"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("company_share", 25),
        ("company_share", 0),
        ("company_share", True),
        ("company_share", "0.25"),
        ("team_floor", 100.5),
        ("team_floor", -1),
        ("team_floor", True),
        ("team_floor", "60"),
    ],
)
def test_a_share_or_a_floor_that_cannot_be_right_refuses_and_is_named(check, settings, key, value):
    # Written past `company settings set`, which refuses these too, with its digest recorded.
    settings(**{"company_share": 0.25, "team_floor": 60, key: value})
    week_reading()

    event = assert_refused(check(), "settings", "unusable")

    assert key in event["reason"]


def test_a_cell_editing_the_file_refuses_the_next_launch_and_logs_tamper(check, ready, tmp_path):
    path = tmp_path / "company-config" / "settings.json"
    assert check().returncode == 0
    path.write_text(path.read_text().replace('"company_share": 0.25', '"company_share": 1'))

    event = assert_refused(check(), "settings", "tampered")

    assert event["fix"] == "company settings init"
    tamper = events("settings-tamper")[-1]
    assert tamper["writer"] == "governor"
    assert tamper["expected_digest"] != tamper["found_digest"]


# The go


def test_a_launch_with_no_word_is_refused(company, check):
    assert company(*INIT).returncode == 0
    week_reading()

    event = assert_refused(check(), "go", "no-go")

    assert event["fix"].startswith("company go real-sessions")


def test_a_word_is_used_up_by_its_launches_and_a_check_uses_none(company, check):
    assert company(*INIT).returncode == 0
    word = go(company, sessions=2)
    week_reading()

    for _ in range(3):
        assert check().returncode == 0
    launch(word)
    result = check()
    assert result.returncode == 0
    assert "1 real launch left" in result.stdout
    launch(word, ALPHA)

    assert_refused(check(), "go", "go-used-up")


def test_a_new_word_opens_launches_again_and_the_oldest_is_spent_first(company, check):
    assert company(*INIT).returncode == 0
    first = go(company, sessions=1)
    week_reading()
    launch(first)
    assert_refused(check(), "go", "go-used-up")

    second = go(company, sessions=1, message="5678")

    assert f"go:{second}" in check().stdout


def test_the_oldest_word_with_launches_left_is_the_one_cited(company, check):
    assert company(*INIT).returncode == 0
    first = go(company, sessions=1)
    go(company, sessions=1, message="5678")
    week_reading()

    assert f"go:{first}" in check().stdout


def test_a_session_on_another_gate_uses_up_no_word(company, check):
    assert company(*INIT).returncode == 0
    go(company, sessions=1)
    start_session(BETA, "probe", week_reading())

    assert check().returncode == 0


def test_the_command_writes_exactly_that_word_as_board(company):
    result = company("go", "real-sessions", "--message", "1234", "--sessions", "3")

    assert result.returncode == 0, result.stderr
    event = events("go-given")[0]
    assert event["writer"] == "board"
    assert event["scope"] == "real-sessions"
    assert event["message"] == "1234"
    assert event["sessions"] == 3
    assert f"event {event['seq']}: a go for 3 real launches" in result.stdout


@pytest.mark.parametrize(
    "args",
    [
        (),
        ("--message", "1234"),
        ("--sessions", "3"),
    ],
)
def test_no_default_grants_a_word(company, args):
    result = company("go", "real-sessions", *args)

    assert result.returncode == 2
    assert events("go-given") == []


@pytest.mark.parametrize(
    ("message", "sessions", "reason"),
    [
        ("1234", "0", "bad-field:sessions"),
        ("1234", "-1", "bad-field:sessions"),
        ("not-digits", "3", "bad-field:message"),
    ],
)
def test_a_word_that_cannot_be_true_is_refused_and_grants_nothing(company, message, sessions, reason):
    result = company("go", "real-sessions", "--message", message, "--sessions", sessions)

    assert result.returncode == 1
    assert events("go-given") == []
    assert events("append-refused")[-1]["reason"] == reason


def test_settings_alone_open_no_gate(company, check):
    assert company(*INIT).returncode == 0
    week_reading()

    assert events("go-given") == []
    assert check().returncode == 1


def test_a_word_is_refused_on_a_broken_ledger(company, company_home, board):
    ledger = company_home / "ledger.jsonl"
    ledger.write_bytes(ledger.read_bytes()[:-5])

    result = company("go", "real-sessions", "--message", "1234", "--sessions", "3")

    assert result.returncode == 1
    assert "LEDGER BROKEN" in result.stdout


# The ledger


def test_an_edited_line_refuses_and_the_refusal_is_logged(company_home, check, ready):
    week_reading()
    ledger = company_home / "ledger.jsonl"
    ledger.write_bytes(ledger.read_bytes().replace(b'"used_percent":40', b'"used_percent":10', 1))

    event = assert_refused(check(), "ledger", "broken")

    assert event["fix"] == "company ledger verify"


def test_a_ledger_that_cannot_take_the_refusal_still_refuses_and_says_so(company_home, check, ready):
    ledger = company_home / "ledger.jsonl"
    ledger.write_bytes(ledger.read_bytes()[:-5])
    before = ledger.read_bytes()

    result = check()

    assert result.returncode == 1
    assert "Refused" in result.stdout
    assert "broken" in result.stdout
    assert "could not be logged" in result.stdout
    assert ledger.read_bytes() == before


# A pause


def pause(bet, scope="cell"):
    fields = {"scope": scope, "reason": "a confirmed finding", "cause_seq": 1}
    if bet:
        fields["bet"] = bet
    Ledger().append("cell-paused", fields, "treasurer")


def resume(bet, scope="cell"):
    fields = {"scope": scope}
    if bet:
        fields["bet"] = bet
    Ledger().append("cell-resumed", fields, "board")


def test_a_paused_bet_refuses_until_it_is_resumed(check, ready):
    assert check("cell", "alpha").returncode == 0
    pause("alpha")

    event = assert_refused(check("cell", "alpha"), "pause", "paused")

    assert event["bet"] == "alpha"
    assert event["fix"] == "company cell resume --bet alpha"
    resume("alpha")
    assert check("cell", "alpha").returncode == 0


def test_a_second_pause_after_a_resume_refuses_again(check, ready):
    pause("alpha")
    resume("alpha")
    pause("alpha")

    assert_refused(check("cell", "alpha"), "pause", "paused")


def test_a_pause_of_one_bet_leaves_another_and_the_other_roles(check, ready):
    pause("alpha")

    assert check("cell", "beta").returncode == 0
    assert check("auditor").returncode == 0


def test_a_cell_paused_with_no_bet_named_refuses_every_bet(check, ready):
    pause(None)

    assert_refused(check("cell", "alpha"), "pause", "paused")


def test_the_company_wide_pause_of_outside_actions_does_not_stop_a_session(check, ready):
    pause(None, scope="outside-actions")

    assert check("cell", "alpha").returncode == 0


def test_a_cell_with_no_bet_is_refused_since_its_pause_cannot_be_read(check, ready):
    event = assert_refused(check("cell"), "pause", "no-bet")

    assert "bet" not in event


def test_a_bet_that_is_no_bet_id_is_refused_and_still_logged(check, ready):
    event = assert_refused(check("cell", "Not A Bet"), "pause", "bad-bet")

    assert "bet" not in event


# The order of the checks


def test_an_unknown_role_is_a_mistake_in_the_command(company, ready):
    result = company("governor", "check", "owner")

    assert result.returncode == 2
    assert events("launch-refused") == []


@pytest.mark.parametrize(
    ("first", "make"),
    [
        ("settings", lambda company: None),
        ("go", lambda company: company(*INIT)),
        ("pause", lambda company: (company(*INIT), go(company), pause("alpha"))),
        ("reading", lambda company: (company(*INIT), go(company))),
    ],
)
def test_the_first_check_that_fails_stops_the_rest_and_logs_one_refusal(company, check, first, make):
    make(company)

    result = check("cell", "alpha")

    assert result.returncode == 1
    assert [event["check"] for event in events("launch-refused")] == [first]
