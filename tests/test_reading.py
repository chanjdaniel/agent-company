"""The account's reading: `company reading record`, `company reading statusline`, and `current(window)`."""

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from usage_records import TEAM, at, day_file, day_row, record_reading, transcript_line

from company import reading
from company.ledger import Ledger
from company.settings import SettingsRefused

NOW = at("2026-10-15T12:00:00Z")
RESET = "2026-10-18T00:00:00Z"
TAKEN = "2026-10-15T11:00:00Z"


@pytest.fixture
def current(transcripts, settings):
    def read(window="seven_day", now=NOW):
        return reading.current(window, now=now)

    return read


def readings():
    return [event for event in Ledger().read() if event["kind"] == "usage-reading"]


def assert_taken_as_it_was_written(event):
    """The time taken comes just before the append's own `ts`, which may fall in the next second."""
    assert timedelta(0) <= at(event["ts"]) - at(event["taken_at"]) < timedelta(seconds=30)


def reply(request, ts, weight_in_opus_tokens=5_000_000):
    return transcript_line(TEAM, request, ts, output=weight_in_opus_tokens)


# current(window)


def test_current_returns_the_reading_with_no_use_since(current):
    seq = record_reading("seven_day", 60, RESET, TAKEN)

    found = current()

    assert found.window == "seven_day"
    assert found.used_percent == 60
    assert found.added_percent == 0
    assert found.seq == seq
    assert found.source == "hand"


def test_current_adds_the_percent_the_usage_records_show_since(current, transcripts):
    # In the window up to the reading: 1,000 of weight, read as 40%, so 25 of weight per percent.
    # Since the reading: 100, which is 100 / 25 = 4 percent. So 44%.
    # The 500 of weight before the window opened on 11 October, and 2,000 after this time, are left out.
    record_reading("seven_day", 40, RESET, TAKEN)
    transcripts.session(
        TEAM,
        reply("before-window", "2026-10-10T23:59:59.000Z", 25_000_000),
        reply("up-to", "2026-10-12T09:00:00.000Z", 50_000_000),
        reply("since", "2026-10-15T11:30:00.000Z", 5_000_000),
        reply("later", "2026-10-15T12:00:01.000Z", 100_000_000),
    )

    found = current()

    assert found.used_percent == 44
    assert found.read_percent == 40
    assert found.added_percent == 4


def test_a_reply_at_the_moment_of_the_reading_counts_up_to_it(current, transcripts):
    # All the weight falls at the reading, so nothing is added, and it has a weight per percent.
    record_reading("seven_day", 40, RESET, TAKEN)
    transcripts.session(TEAM, reply("at", "2026-10-15T11:00:00.000Z"))

    assert current().used_percent == 40


def test_current_returns_nothing_with_no_reading(current):
    assert current() is None


def test_a_reading_of_another_window_is_no_reading(current):
    record_reading("five_hour", 20, "2026-10-15T14:00:00Z", TAKEN)

    assert current("seven_day") is None
    assert current("five_hour").used_percent == 20


def test_current_returns_nothing_for_a_reading_older_than_the_maximum_age(current, settings):
    settings(reading_max_age_minutes=60)
    record_reading("seven_day", 40, RESET, TAKEN)

    assert current(now=at("2026-10-15T12:00:00Z")).used_percent == 40
    assert current(now=at("2026-10-15T12:00:01Z")) is None


def test_current_returns_nothing_once_the_window_has_reset(current):
    record_reading("seven_day", 40, "2026-10-15T11:59:59Z", TAKEN)

    assert current() is None


def test_current_returns_nothing_at_the_moment_the_window_resets(current):
    record_reading("seven_day", 40, "2026-10-15T12:00:00Z", TAKEN)

    assert current() is None


@pytest.mark.parametrize(
    ("used_percent", "resets_at", "taken_at", "source"),
    [
        pytest.param("sixty", RESET, TAKEN, "hand", id="a-percent-that-is-text"),
        pytest.param(True, RESET, TAKEN, "hand", id="a-percent-that-is-true"),
        pytest.param(None, RESET, TAKEN, "hand", id="no-percent"),
        pytest.param(-1, RESET, TAKEN, "hand", id="a-percent-below-zero"),
        pytest.param(100.5, RESET, TAKEN, "hand", id="a-percent-above-100"),
        pytest.param(40, RESET, TAKEN, "a-guess", id="an-unknown-source"),
        pytest.param(40, "2026-10-15T10:00:00Z", TAKEN, "hand", id="reset-before-it-was-taken"),
        pytest.param(40, "2026-10-22T11:00:01Z", TAKEN, "hand", id="reset-further-off-than-the-window-is-long"),
        pytest.param(40, RESET, "2026-10-15T12:00:01Z", "hand", id="taken-in-the-future"),
    ],
)
def test_current_returns_nothing_for_a_malformed_reading(current, used_percent, resets_at, taken_at, source):
    record_reading("seven_day", used_percent, resets_at, taken_at, source)

    assert current() is None


def test_a_malformed_newest_reading_hides_an_older_good_one(current):
    record_reading("seven_day", 40, RESET, TAKEN)
    record_reading("seven_day", "sixty", RESET, TAKEN)

    assert current() is None


def test_a_zero_percent_reading_with_no_use_after_it_is_zero(current):
    record_reading("seven_day", 0, RESET, TAKEN)

    assert current().used_percent == 0


def test_current_returns_nothing_when_use_follows_a_zero_percent_reading(current, transcripts):
    # There is weight up to the reading, but zero percent gives no weight per percent to turn the use after it into one.
    record_reading("seven_day", 0, RESET, TAKEN)
    transcripts.session(TEAM, reply("up-to", "2026-10-12T09:00:00.000Z"), reply("since", "2026-10-15T11:30:00.000Z"))

    assert current() is None


def test_a_reading_above_zero_with_no_weight_up_to_it_and_no_use_after_stands(current):
    record_reading("seven_day", 30, RESET, TAKEN)

    assert current().used_percent == 30


def test_current_returns_nothing_when_use_follows_a_reading_with_no_weight_up_to_it(current, transcripts):
    # 30% was read with no weight in this window's records, so the use after it cannot become a percent.
    # The reply before the window does not count as weight in it.
    record_reading("seven_day", 30, RESET, TAKEN)
    transcripts.session(TEAM, reply("before-window", "2026-10-10T09:00:00.000Z"), reply("since", "2026-10-15T11:30:00.000Z"))

    assert current() is None


def test_each_unusable_reading_has_its_own_reason(transcripts, settings):
    settings(reading_max_age_minutes=60)

    def reason():
        return reading.assess_now("seven_day", NOW).reason

    assert reason() == "no-reading"
    record_reading("seven_day", "sixty", RESET, TAKEN)
    assert reason() == "malformed"
    record_reading("seven_day", 40, RESET, "2026-10-15T10:00:00Z")
    assert reason() == "stale"
    record_reading("seven_day", 40, "2026-10-15T11:59:00Z", TAKEN)
    assert reason() == "window-reset"
    record_reading("seven_day", 0, RESET, TAKEN)
    transcripts.session(TEAM, reply("since", "2026-10-15T11:30:00.000Z"))
    assert reason() == "zero-percent"
    record_reading("seven_day", 40, RESET, TAKEN)
    assert reason() == "no-weight"


def test_a_failure_to_read_the_records_raises_for_the_governor_to_refuse_on(current, transcripts):
    record_reading("seven_day", 40, RESET, TAKEN)
    (transcripts.projects / "-some-project" / "unreadable.jsonl").mkdir(parents=True)

    with pytest.raises(OSError):
        current()


def test_a_missing_settings_file_raises_since_no_maximum_age_is_compiled_in(transcripts):
    record_reading("seven_day", 40, RESET, TAKEN)

    with pytest.raises(SettingsRefused):
        reading.current("seven_day", now=NOW)


def test_an_unknown_window_is_a_mistake_in_the_caller(current):
    with pytest.raises(ValueError):
        current("weekly")


def test_the_five_hour_window_uses_its_own_opening(current, transcripts, tmp_path, settings):
    # The window opened at 09:00. Up to the reading only the 10:00 reply counts: 100 at 20%, so 5 of weight per percent.
    # The day file's reply since the reading weighs 20, which is 4 percent. So 24%.
    usage = tmp_path / "team-usage"
    settings(usage_day_dirs=[str(usage)])
    record_reading("five_hour", 20, "2026-10-15T14:00:00Z", TAKEN)
    transcripts.session(TEAM, reply("before", "2026-10-15T08:59:59.000Z"), reply("in", "2026-10-15T10:00:00.000Z"))
    day_file(usage, "other-pc", "2026-10-15", day_row(TEAM, "there", "2026-10-15T11:30:00.000Z", output=1_000_000))

    assert current("five_hour").used_percent == 24


# company reading record


def record(company, *args):
    return company("reading", "record", *args)


def future(hours):
    return (datetime.now(UTC) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_recording_a_reading_keeps_it_as_daniels(company):
    resets_at = future(48)

    result = record(company, "--window", "seven_day", "--used-percent", "41.5", "--resets-at", resets_at)

    assert result.returncode == 0, result.stderr
    [event] = readings()
    assert event["writer"] == "board"
    assert event["source"] == "hand"
    assert event["window"] == "seven_day"
    assert event["used_percent"] == 41.5
    assert event["resets_at"] == resets_at
    assert_taken_as_it_was_written(event)
    assert "seven_day" in result.stdout
    assert f"event {event['seq']}" in result.stdout


def test_a_recorded_reset_with_an_offset_is_kept_in_utc(company):
    result = record(company, "--window", "five_hour", "--used-percent", "10", "--resets-at", _offset_time(hours=2))

    assert result.returncode == 0, result.stderr
    assert readings()[0]["resets_at"].endswith("Z")


def _offset_time(hours):
    east_of_utc = timezone(timedelta(hours=8))
    return (datetime.now(UTC) + timedelta(hours=hours)).astimezone(east_of_utc).isoformat(timespec="seconds")


@pytest.mark.parametrize(
    ("window", "percent", "hours", "named"),
    [
        ("weekly", "40", 48, "--window"),
        ("seven_day", "lots", 48, "--used-percent"),
    ],
)
def test_a_record_the_command_cannot_parse_appends_nothing(company, window, percent, hours, named):
    result = record(company, "--window", window, "--used-percent", percent, "--resets-at", future(hours))

    assert result.returncode == 2
    assert named in result.stderr
    assert readings() == []


@pytest.mark.parametrize(
    ("percent", "resets_at", "named"),
    [
        ("101", future(48), "used percent"),
        ("-1", future(48), "used percent"),
        ("nan", future(48), "used percent"),
        ("40", "next thursday", "--resets-at"),
        ("40", "2026-10-15T12:00:00", "--resets-at"),
        ("40", "2020-01-01T00:00:00Z", "resets"),
        ("40", future(24 * 8), "resets"),
    ],
)
def test_a_record_that_would_be_malformed_appends_nothing_and_says_so(company, percent, resets_at, named):
    result = record(company, "--window", "seven_day", "--used-percent", percent, "--resets-at", resets_at)

    assert result.returncode == 2
    assert named in result.stderr
    assert "Nothing was recorded" in result.stderr
    assert readings() == []


def test_recording_on_a_broken_ledger_is_refused(company, company_home):
    resets_at = future(48)
    assert record(company, "--window", "seven_day", "--used-percent", "40", "--resets-at", resets_at).returncode == 0
    ledger = company_home / "ledger.jsonl"
    ledger.write_text(ledger.read_text().replace('"used_percent":40.0', '"used_percent":10.0'))

    result = record(company, "--window", "seven_day", "--used-percent", "41", "--resets-at", resets_at)

    assert result.returncode == 1
    assert "Nothing was recorded" in result.stderr


# company reading statusline


def epoch(hours):
    return int((datetime.now(UTC) + timedelta(hours=hours)).timestamp())


def documented_input(five_hour=(23.5, 2), seven_day=(41.2, 48)):
    """The status line's documented input, with the fields around `rate_limits` that a session also sends."""
    limits = {}
    if five_hour:
        limits["five_hour"] = {"used_percentage": five_hour[0], "resets_at": epoch(five_hour[1])}
    if seven_day:
        limits["seven_day"] = {"used_percentage": seven_day[0], "resets_at": epoch(seven_day[1])}
    return {"session_id": "s", "model": {"id": "m", "display_name": "M"}, "rate_limits": limits}


def statusline(company, payload):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return company("reading", "statusline", input=text)


def test_the_status_line_keeps_a_reading_per_window_and_prints_a_short_text(company):
    payload = documented_input()

    result = statusline(company, payload)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "company: 7d 41% 5h 24%\n"
    assert result.stderr == ""
    kept = {event["window"]: event for event in readings()}
    assert set(kept) == {"seven_day", "five_hour"}
    assert kept["seven_day"]["source"] == "statusline"
    assert kept["seven_day"]["writer"] == "governor"
    assert kept["seven_day"]["used_percent"] == 41.2
    assert kept["five_hour"]["used_percent"] == 23.5
    expected = datetime.fromtimestamp(payload["rate_limits"]["seven_day"]["resets_at"], UTC)
    assert kept["seven_day"]["resets_at"] == expected.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert_taken_as_it_was_written(kept["seven_day"])


def test_a_kept_status_line_reading_is_what_current_returns(company, transcripts, settings):
    statusline(company, documented_input())

    found = reading.current("seven_day")

    assert found.source == "statusline"
    assert float(found.used_percent) == 41.2


def test_the_status_line_accepts_input_with_no_rate_limits(company):
    result = statusline(company, {"session_id": "s"})

    assert result.returncode == 0
    assert result.stdout == "company: no window reading\n"
    assert readings() == []


@pytest.mark.parametrize(
    ("kwargs", "text", "windows"),
    [
        ({"five_hour": None}, "company: 7d 41%\n", {"seven_day"}),
        ({"seven_day": None}, "company: 5h 24%\n", {"five_hour"}),
    ],
)
def test_the_status_line_accepts_either_window_absent(company, kwargs, text, windows):
    result = statusline(company, documented_input(**kwargs))

    assert result.returncode == 0
    assert result.stdout == text
    assert {event["window"] for event in readings()} == windows


def test_the_status_line_ignores_a_window_it_does_not_know(company):
    payload = documented_input(five_hour=None)
    payload["rate_limits"]["spend_limit"] = {"used_percentage": 62.8, "resets_at": epoch(100)}

    statusline(company, payload)

    assert {event["window"] for event in readings()} == {"seven_day"}


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not json",
        "[1, 2]",
        '{"rate_limits": "soon"}',
        '{"rate_limits": {"seven_day": "soon"}}',
        '{"rate_limits": {"seven_day": {"used_percentage": 40}}}',
        '{"rate_limits": {"seven_day": {"resets_at": 1893456000}}}',
        '{"rate_limits": {"seven_day": {"used_percentage": "forty", "resets_at": 1893456000}}}',
        '{"rate_limits": {"seven_day": {"used_percentage": 140, "resets_at": 1893456000}}}',
        '{"rate_limits": {"seven_day": {"used_percentage": 40, "resets_at": 1}}}',
        '{"rate_limits": {"seven_day": {"used_percentage": 40, "resets_at": 1e300}}}',
        '{"rate_limits": {"seven_day": {"used_percentage": 40, "resets_at": "tomorrow"}}}',
        '{"rate_limits": {"seven_day": {"used_percentage": 40, "resets_at": true}}}',
        '{"rate_limits": {"seven_day": {"used_percentage": 1' + "0" * 400 + ', "resets_at": 1893456000}}}',
        '[' * 100000,
    ],
)
def test_input_it_cannot_use_keeps_nothing_and_never_breaks_the_status_bar(company, text):
    result = statusline(company, text)

    assert result.returncode == 0
    assert result.stdout == "company: no window reading\n"
    assert result.stderr == ""
    assert readings() == []


def test_input_that_is_not_text_never_breaks_the_status_bar():
    script = Path(sys.executable).parent / "company"

    result = subprocess.run([script, "reading", "statusline"], input=b"\xff\xfe", capture_output=True, check=False, timeout=60)

    assert result.returncode == 0
    assert result.stdout == b"company: no window reading\n"
    assert result.stderr == b""


def test_a_status_line_on_a_broken_ledger_still_prints_and_says_nothing_was_kept(company, company_home):
    statusline(company, documented_input(five_hour=None))
    ledger = company_home / "ledger.jsonl"
    ledger.write_text(ledger.read_text().replace('"used_percent":41.2', '"used_percent":10.2'))
    (company_home / "ledger.head").write_text('{"seq": 7, "hash": "nothing"}')
    (company_home / "statusline.state").unlink()

    result = statusline(company, documented_input(five_hour=None))

    assert result.returncode == 0
    assert result.stdout == "company: 7d 41% (not kept)\n"
    assert result.stderr == ""


def test_the_status_line_runs_often_so_it_keeps_a_window_once_in_five_minutes():
    resets = int(at(RESET).timestamp())
    payload = json.dumps({"rate_limits": {"seven_day": {"used_percentage": 40, "resets_at": resets}}})

    reading.keep_statusline(payload, now=at("2026-10-15T11:00:00Z"))
    reading.keep_statusline(payload, now=at("2026-10-15T11:04:59Z"))
    assert len(readings()) == 1

    reading.keep_statusline(payload, now=at("2026-10-15T11:05:00Z"))
    assert len(readings()) == 2


def test_a_new_window_is_kept_at_once():
    first = int(at(RESET).timestamp())
    second = first + 3600
    for resets in (first, second):
        payload = json.dumps({"rate_limits": {"seven_day": {"used_percentage": 1, "resets_at": resets}}})
        reading.keep_statusline(payload, now=at("2026-10-15T11:00:00Z"))

    assert len(readings()) == 2
