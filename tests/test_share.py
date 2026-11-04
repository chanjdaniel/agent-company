"""`company treasurer share`: the company's share of each window, the week's cost and each bet's cost."""

import json

import pytest
from usage_records import (
    ALPHA,
    BETA,
    OPUS,
    PROBE,
    SONNET,
    TEAM,
    day_file,
    day_row,
    record_reading,
    start_session,
    transcript_line,
)

from company.usage import Prices

NOW = "2026-10-15T12:00:00Z"
SEVEN_DAY_RESET = "2026-10-18T00:00:00Z"
FIVE_HOUR_RESET = "2026-10-15T14:00:00Z"
TAKEN = "2026-10-15T11:00:00Z"

# The worked week, on a $120 monthly price.
#
# The seven-day window runs to its reset on 18 October, so it opened on 11 October.
# The five-hour window runs to its reset at 14:00, so it opened at 09:00.
# The readings were taken at 11:00: seven-day 60%, five-hour 20%. The report is at 12:00.
#
#   when          session          tokens of output   weight
#   10 Oct        team              50,000,000 Opus   1000 (before both windows: left out)
#   12 Oct        team              40,000,000 Opus    800
#   13 Oct        alpha (bet)        5,000,000 Opus    100
#   13 Oct        beta (bet)         5,000,000 Sonnet   50
#   14 Oct        probe (no bet)     2,500,000 Opus     50
#   15 Oct 10:00  team              10,000,000 Opus    200
#   -- the readings, at 11:00 --
#   15 Oct 11:30  alpha (bet)        5,000,000 Opus    100
#   15 Oct 11:45  team               1,000,000 Opus     20
#   15 Oct 12:30  team              50,000,000 Opus   1000 (after the report's time: left out)
#
# Seven days:
#   up to the reading: 800 + 100 + 50 + 50 + 200 = 1200, at 60%, so 20 of weight per percent.
#   since the reading: 100 + 20 = 120, which is 120 / 20 = 6 percent, so the account has used 66%.
#   all weight 1320; the company's is alpha 200 + beta 50 + probe 50 = 300.
#   company_fraction = 300 / 1320 = 5/22 = 0.227273
#   company_used = 5/22 x 66 = 15.00%
# Five hours:
#   up to the reading: 200, at 20%, so 10 of weight per percent.
#   since the reading: 120, which is 12 percent, so the account has used 32%.
#   all weight 320; the company's is alpha's 100.
#   company_fraction = 100 / 320 = 0.3125
#   company_used = 0.3125 x 32 = 10.00%
# The week's cost, from the seven-day window only:
#   weekly_price = 120 x 12 / 52 = 27.692308, so $27.69
#   company_cost = 15 / 100 x 27.692308 = 4.153846, so $4.15
#   alpha = 200 / 300 x 4.153846 = 2.769231, so $2.77
#   beta = 50 / 300 x 4.153846 = 0.692308, so $0.69
#   overhead, the probe = 50 / 300 x 4.153846 = 0.692308, so $0.69
WORKED_WEEK_REPORT = """\
The company's share at 2026-10-15T12:00:00Z
seven_day: account used 66.00%: 60.00% read at 2026-10-15T11:00:00Z by hand (event 1), and 6.00% since
seven_day: list-price weight 300.000000 of 1320.000000, fraction 0.227273, company used 15.00%
five_hour: account used 32.00%: 20.00% read at 2026-10-15T11:00:00Z by hand (event 2), and 12.00% since
five_hour: list-price weight 100.000000 of 320.000000, fraction 0.312500, company used 10.00%
Weekly price: $27.69
Company cost this week: $4.15
  bet alpha: $2.77
  bet beta: $0.69
  overhead: $0.69
"""


@pytest.fixture
def worked_week(transcripts, settings):
    record_reading("seven_day", 60, SEVEN_DAY_RESET, TAKEN)
    five_hour = record_reading("five_hour", 20, FIVE_HOUR_RESET, TAKEN)
    start_session(ALPHA, "cell", five_hour, bet="alpha")
    start_session(BETA, "cell", five_hour, bet="beta")
    start_session(PROBE, "probe", five_hour)
    transcripts.session(
        TEAM,
        transcript_line(TEAM, "t-old", "2026-10-10T09:00:00.000Z", output=50_000_000),
        transcript_line(TEAM, "t-1", "2026-10-12T09:00:00.000Z", output=40_000_000),
        transcript_line(TEAM, "t-2", "2026-10-15T10:00:00.000Z", output=10_000_000),
        transcript_line(TEAM, "t-3", "2026-10-15T11:45:00.000Z", output=1_000_000),
        transcript_line(TEAM, "t-late", "2026-10-15T12:30:00.000Z", output=50_000_000),
    )
    transcripts.session(
        ALPHA,
        transcript_line(ALPHA, "a-1", "2026-10-13T09:00:00.000Z", output=5_000_000),
        transcript_line(ALPHA, "a-2", "2026-10-15T11:30:00.000Z", output=5_000_000),
    )
    transcripts.session(BETA, transcript_line(BETA, "b-1", "2026-10-13T09:00:00.000Z", model=SONNET, output=5_000_000))
    transcripts.session(PROBE, transcript_line(PROBE, "p-1", "2026-10-14T09:00:00.000Z", output=2_500_000))


def share(company):
    return company("treasurer", "share", "--now", NOW)


def lines_for(report, start):
    return [line for line in report.splitlines() if line.startswith(start)]


def test_the_worked_week_prints_each_number_worked_by_hand(company, worked_week):
    result = share(company)

    assert result.returncode == 0, result.stderr
    assert result.stdout == WORKED_WEEK_REPORT
    assert result.stderr == ""


def test_the_same_fixture_gives_the_same_numbers_every_run(company, worked_week):
    assert [share(company).stdout for _ in range(3)] == [WORKED_WEEK_REPORT] * 3


def test_no_reporting_line_calls_a_list_price_weight_a_cost(company, worked_week):
    for line in share(company).stdout.splitlines():
        if "weight" in line:
            assert "cost" not in line.lower()
            assert "$" not in line
        if "cost" in line.lower():
            assert "weight" not in line


def test_a_reading_with_no_five_hour_window_reports_the_week_alone(company, transcripts, settings):
    # The whole seven-day use is at the reading: 800 of team weight, 200 of alpha's, at 50%.
    # So the fraction is 200 / 1000 = 0.2, company_used 0.2 x 50 = 10%, and the cost 10 / 100 x 27.692308 = $2.77.
    seq = record_reading("seven_day", 50, SEVEN_DAY_RESET, TAKEN)
    start_session(ALPHA, "cell", seq, bet="alpha")
    transcripts.session(TEAM, transcript_line(TEAM, "t-1", "2026-10-12T09:00:00.000Z", output=40_000_000))
    transcripts.session(ALPHA, transcript_line(ALPHA, "a-1", "2026-10-13T09:00:00.000Z", output=10_000_000))

    result = share(company)

    assert result.returncode == 0, result.stderr
    assert "five_hour: no reading" in result.stdout
    assert "fraction 0.200000, company used 10.00%" in result.stdout
    assert "Company cost this week: $2.77" in result.stdout
    assert "  bet alpha: $2.77" in result.stdout
    assert "  overhead: $0.00" in result.stdout


def test_a_usable_week_with_an_unusable_five_hour_reading_says_why(company, transcripts, settings):
    record_reading("seven_day", 50, SEVEN_DAY_RESET, TAKEN)
    record_reading("five_hour", 20, "2026-10-15T11:30:00Z", TAKEN)
    transcripts.session(TEAM, transcript_line(TEAM, "t-1", "2026-10-12T09:00:00.000Z", output=1_000_000))

    result = share(company)

    assert result.returncode == 0, result.stderr
    assert "five_hour: unreadable: " in result.stdout
    assert "Company cost this week: $0.00" in result.stdout


def test_a_session_is_the_companys_only_when_a_session_started_event_names_it(company, transcripts, settings):
    # Three sessions weigh 100 each, and only one has a `session-started` event, so the fraction is 100 / 300.
    seq = record_reading("seven_day", 60, SEVEN_DAY_RESET, TAKEN)
    start_session(ALPHA, "cell", seq, bet="alpha")
    for session in (ALPHA, BETA, TEAM):
        transcripts.session(session, transcript_line(session, f"r-{session}", "2026-10-13T09:00:00.000Z", output=5_000_000))

    result = share(company)

    assert "list-price weight 100.000000 of 300.000000, fraction 0.333333" in result.stdout
    assert lines_for(result.stdout, "  bet") == ["  bet alpha: $5.54"]


def test_a_reply_repeated_across_a_forked_transcript_counts_once(company, transcripts, settings):
    # The fork's copy holds the same request id, under its own session, later in the listing.
    # Counted once it weighs 100; counted twice it would weigh 200.
    record_reading("seven_day", 60, SEVEN_DAY_RESET, TAKEN)
    line = transcript_line(TEAM, "same", "2026-10-13T09:00:00.000Z", output=5_000_000)
    transcripts.session(TEAM, line)
    transcripts.session(BETA, {**line, "sessionId": BETA})

    assert "list-price weight 0.000000 of 100.000000" in share(company).stdout


def test_a_repeated_reply_takes_each_counts_largest_value(company, transcripts, settings):
    # Claude Code writes a line per content block, and an early line can hold a partial output.
    # The largest output, 5,000,000, and the largest cache read, 1,000,000 at 0.2, weigh 100 + 0.2.
    record_reading("seven_day", 60, SEVEN_DAY_RESET, TAKEN)
    transcripts.session(
        TEAM,
        transcript_line(TEAM, "same", "2026-10-13T09:00:00.000Z", output=10, cache_read=1_000_000),
        transcript_line(TEAM, "same", "2026-10-13T09:00:01.000Z", output=5_000_000, cache_read=0),
        transcript_line(TEAM, "same", "2026-10-13T09:00:02.000Z", output=20),
    )

    assert "of 100.200000," in share(company).stdout


def test_a_reply_in_a_transcript_and_a_day_file_counts_once_at_its_largest(company, transcripts, settings, tmp_path):
    # The day file holds the same request with a larger output: 5,000,000 weighs 100, and 10 would weigh next to nothing.
    usage = tmp_path / "team-usage"
    settings(usage_day_dirs=[str(usage)])
    record_reading("seven_day", 60, SEVEN_DAY_RESET, TAKEN)
    transcripts.session(TEAM, transcript_line(TEAM, "same", "2026-10-13T09:00:00.000Z", output=10))
    day_file(usage, "other-pc", "2026-10-13", day_row(TEAM, "same", "2026-10-13T09:00:00.000Z", output=5_000_000))

    assert "of 100.000000," in share(company).stdout


def test_a_day_file_adds_another_machines_replies(company, transcripts, settings, tmp_path):
    # A day file holds what this machine's transcripts do not: 100 here and 300 from the other machine.
    usage = tmp_path / "team-usage"
    settings(usage_day_dirs=[str(usage)])
    record_reading("seven_day", 60, SEVEN_DAY_RESET, TAKEN)
    transcripts.session(TEAM, transcript_line(TEAM, "here", "2026-10-13T09:00:00.000Z", output=5_000_000))
    day_file(usage, "other-pc", "2026-10-14", day_row(BETA, "there", "2026-10-14T09:00:00.000Z", output=15_000_000))
    # A time day file sits under the machine too, and holds no replies; a day older than the window is not read.
    day_file(usage / "other-pc", "time", "2026-10-14", day_row(BETA, "not-a-reply", "2026-10-14T09:00:00.000Z", output=1_000_000))
    day_file(usage, "other-pc", "2026-10-01", day_row(BETA, "old", "2026-10-01T09:00:00.000Z", output=1_000_000))

    assert "of 400.000000," in share(company).stdout


def test_without_the_setting_no_day_file_is_read(company, transcripts, settings, tmp_path):
    record_reading("seven_day", 60, SEVEN_DAY_RESET, TAKEN)
    transcripts.session(TEAM, transcript_line(TEAM, "here", "2026-10-13T09:00:00.000Z", output=5_000_000))
    day_file(tmp_path / "team-usage", "other-pc", "2026-10-14", day_row(BETA, "there", "2026-10-14T09:00:00.000Z", output=15_000_000))

    assert "of 100.000000," in share(company).stdout


def test_a_subagents_reply_counts_to_its_parent_session(company, transcripts, settings):
    # The parent is a bet's session with 100 of its own; its subagent adds 50, under an id of the subagent's own.
    # The team has 150, so alpha has 150 of 300, whichever id the subagent's lines carry.
    seq = record_reading("seven_day", 60, SEVEN_DAY_RESET, TAKEN)
    start_session(ALPHA, "cell", seq, bet="alpha")
    transcripts.session(ALPHA, transcript_line(ALPHA, "a-1", "2026-10-13T09:00:00.000Z", output=5_000_000))
    transcripts.subagent(
        ALPHA,
        transcript_line("not-the-parents-id", "a-2", "2026-10-13T09:01:00.000Z", output=1_250_000, agent="one"),
        transcript_line(ALPHA, "a-3", "2026-10-13T09:02:00.000Z", output=1_250_000, agent="one"),
    )
    transcripts.session(TEAM, transcript_line(TEAM, "t-1", "2026-10-13T09:00:00.000Z", output=7_500_000))

    assert "list-price weight 150.000000 of 300.000000" in share(company).stdout


def test_a_missing_cache_lifetime_is_one_hour_in_a_main_session_and_five_minutes_in_a_subagent(company, transcripts, settings):
    # One million tokens written, on Opus: 8 at the one-hour price, and 5 at the five-minute price.
    record_reading("seven_day", 60, SEVEN_DAY_RESET, TAKEN)
    transcripts.session(TEAM, transcript_line(TEAM, "main", "2026-10-13T09:00:00.000Z", write=1_000_000))
    transcripts.subagent(TEAM, transcript_line(TEAM, "sub", "2026-10-13T09:01:00.000Z", write=1_000_000, agent="one"))

    assert "of 13.000000," in share(company).stdout


def test_a_recorded_cache_lifetime_is_weighed_at_its_own_price(company, transcripts, settings):
    # 1,000,000 at the one-hour 8 and 2,000,000 at the five-minute 5 weigh 8 + 10.
    record_reading("seven_day", 60, SEVEN_DAY_RESET, TAKEN)
    line = transcript_line(TEAM, "main", "2026-10-13T09:00:00.000Z", write=3_000_000, lifetimes=(1_000_000, 2_000_000))
    transcripts.session(TEAM, line)

    assert "of 18.000000," in share(company).stdout


def test_a_model_with_above_prices_uses_them_past_its_threshold(company, transcripts, settings):
    # Haiku's output is 0.5 per million, and 2.5 once the prompt is over 100,000 tokens.
    # A prompt of 100,000 exactly: 100,000 x 0.1 / 1,000,000 = 0.01 of input and 1,000,000 x 0.5 / 1,000,000 = 0.5 of output.
    # A prompt of 120,000: 120,000 x 0.5 / 1,000,000 = 0.06 of input and 1,000,000 x 2.5 / 1,000,000 = 2.5 of output.
    # In all, 0.01 + 0.5 + 0.06 + 2.5 = 3.07.
    record_reading("seven_day", 60, SEVEN_DAY_RESET, TAKEN)
    haiku = "claude-haiku-5-5"
    transcripts.session(
        TEAM,
        transcript_line(TEAM, "at", "2026-10-13T09:00:00.000Z", model=haiku, input_tokens=100_000, output=1_000_000),
        transcript_line(TEAM, "over", "2026-10-13T09:01:00.000Z", model=haiku, input_tokens=120_000, output=1_000_000),
    )

    assert "of 3.070000," in share(company).stdout


def test_a_model_with_no_price_is_weighed_at_the_dearest_with_a_warning(company, transcripts, settings):
    # The dearest model in the table is Fable, at 50 per million of output, so 1,000,000 tokens weigh 50.
    record_reading("seven_day", 60, SEVEN_DAY_RESET, TAKEN)
    transcripts.session(TEAM, transcript_line(TEAM, "new", "2026-10-13T09:00:00.000Z", model="claude-unknown-9", output=1_000_000))

    result = share(company)

    assert result.returncode == 0, result.stderr
    assert "of 50.000000," in result.stdout
    assert "claude-unknown-9" in result.stderr
    assert "claude-fable-5-1" in result.stderr
    assert "warning" in result.stderr
    assert "cost" not in result.stderr.lower()


def test_lines_that_are_no_reply_are_left_out(company, transcripts, settings):
    record_reading("seven_day", 60, SEVEN_DAY_RESET, TAKEN)
    good = transcript_line(TEAM, "good", "2026-10-13T09:00:00.000Z", output=5_000_000)
    no_request = {**transcript_line(TEAM, "x", "2026-10-13T09:00:00.000Z", output=5_000_000), "requestId": None}
    no_time = transcript_line(TEAM, "y", "not a time", output=5_000_000)
    user = {**transcript_line(TEAM, "z", "2026-10-13T09:00:00.000Z", output=5_000_000), "type": "user"}
    text = "\n".join(json.dumps(line) for line in (good, no_request, no_time, user)) + '\n{"type":"assistant","cut sho'
    transcripts.raw(TEAM, text)

    result = share(company)

    assert result.returncode == 0, result.stderr
    assert "of 100.000000," in result.stdout


def test_a_week_with_no_replies_at_all_costs_nothing(company, transcripts, settings):
    record_reading("seven_day", 40, SEVEN_DAY_RESET, TAKEN)

    result = share(company)

    assert result.returncode == 0, result.stderr
    assert "account used 40.00%" in result.stdout
    assert "fraction 0.000000, company used 0.00%" in result.stdout
    assert "Company cost this week: $0.00" in result.stdout


def test_with_no_seven_day_reading_it_refuses_to_print_a_number(company, transcripts, settings):
    result = share(company)

    assert result.returncode == 1
    assert "no-reading" in result.stdout
    assert "company reading record" in result.stdout
    assert "$" not in result.stdout


def test_with_no_settings_it_says_nothing_was_computed(company, transcripts):
    record_reading("seven_day", 60, SEVEN_DAY_RESET, TAKEN)

    result = share(company)

    assert result.returncode == 1
    assert "settings" in result.stderr
    assert "Nothing was computed" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize(
    "change",
    [{"monthly_price": None}, {"monthly_price": "120"}, {"monthly_price": -1}, {"monthly_price": True}, {"reading_max_age_minutes": 0}, {"usage_day_dirs": "a-string"}],
)
def test_a_setting_it_cannot_use_is_named_and_no_value_is_assumed(company, transcripts, settings, change):
    settings(**change)
    record_reading("seven_day", 60, SEVEN_DAY_RESET, TAKEN)

    result = share(company)

    assert result.returncode == 1
    assert next(iter(change)) in result.stderr
    assert result.stdout == ""


def test_a_broken_ledger_prints_no_numbers(company, company_home, worked_week):
    ledger = company_home / "ledger.jsonl"
    ledger.write_text(ledger.read_text().replace('"used_percent":60', '"used_percent":10'))

    result = share(company)

    assert result.returncode == 1
    assert "LEDGER BROKEN" in result.stdout
    assert "$" not in result.stdout


def test_a_time_it_cannot_read_is_refused(company, worked_week):
    result = company("treasurer", "share", "--now", "tomorrow")

    assert result.returncode == 2
    assert "--now" in result.stderr


def test_usage_records_it_cannot_read_are_named_and_nothing_is_computed(company, transcripts, settings):
    record_reading("seven_day", 60, SEVEN_DAY_RESET, TAKEN)
    (transcripts.projects / "-some-project" / "unreadable.jsonl").mkdir(parents=True)

    result = share(company)

    assert result.returncode == 1
    assert "usage records" in result.stderr
    assert "Nothing was computed" in result.stderr
    assert result.stdout == ""


def test_the_worked_week_relies_on_these_list_prices():
    prices = Prices.load()
    assert prices.models[OPUS]["output"] == 20
    assert prices.models[SONNET]["output"] == 10
