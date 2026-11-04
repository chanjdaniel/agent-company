"""The ladder: the bar reached and the margin against the next, over a trailing month of four complete windows."""

import pytest
from ledger_history import (
    DIGEST_SETTINGS,
    LAST_FEW_DAYS,
    MONTH_DAY,
    NOW,
    THIS_WEEK,
    WEEK_1,
    WEEK_2,
    WEEK_3,
    WEEK_4,
    ledger_at,
    money,
    section,
    seven_day_reading,
    week_charge,
)
from usage_records import ALPHA, start_session

# The worked month, on a $130 monthly price, so a weekly price of 130 x 12 / 52 = $30.
#
#   share cost: 6 + 5 + 4 + 5                 = $20
#   dollars spent                             = $10
#   bar 1's line: 20 + 10                     = $30
#   the trial: 0.1 x 0.25 x 30 x 4 = $3, plus its $0 of dollars
#   bar 2's line: 30 + 3                      = $33
#   bar 3's line: the $130 price + 10         = $140
#
#   bar  revenue  refunds  fees  net   margin against the next bar
#   0      40       5       10    25   25 - 30  = -5, against bar 1
#   1      50       5       13    32   32 - 33  = -1, against bar 2
#   2     100       5        5    90   90 - 140 = -50, against bar 3
#   3     160       5        5   150   none: bar 3 is the top


@pytest.fixture(autouse=True)
def digest_settings(settings, transcripts):
    settings(**DIGEST_SETTINGS)


@pytest.fixture
def month():
    """The worked month's costs, and a way to add its net revenue."""
    reading = seven_day_reading()
    for week, cost in ((WEEK_1, "6.00"), (WEEK_2, "5.00"), (WEEK_3, "4.00"), (WEEK_4, "5.00")):
        week_charge(week, cost, reading)
    money("spend", "10.00")

    def takings(revenue: str, refunds: str, fees: str):
        money("revenue", revenue)
        money("refund", refunds)
        money("fee", fees)

    return takings


def bar_section(company, now=NOW):
    result = company("digest", "--now", now)
    assert result.returncode == 0, result.stderr
    return section(result.stdout, "Bar")


@pytest.mark.parametrize(
    ("revenue", "refunds", "fees", "reached", "net", "margin"),
    [
        ("40.00", "5.00", "10.00", "Bar reached: 0 (Running)", "$25.00", "Margin against bar 1 (Own share): -$5.00 (its line is $30.00)"),
        ("50.00", "5.00", "13.00", "Bar reached: 1 (Own share)", "$32.00", "Margin against bar 2 (Self-funding): -$1.00 (its line is $33.00)"),
        ("100.00", "5.00", "5.00", "Bar reached: 2 (Self-funding)", "$90.00", "Margin against bar 3 (Whole subscription): -$50.00 (its line is $140.00)"),
        ("160.00", "5.00", "5.00", "Bar reached: 3 (Whole subscription)", "$150.00", "Margin against the next bar: none, this is the top bar"),
    ],
)
def test_a_month_reports_its_bar_and_the_margin_against_the_next(company, month, revenue, refunds, fees, reached, net, margin):
    month(revenue, refunds, fees)

    text = bar_section(company)

    assert reached in text
    assert f"Net revenue: {net} (revenue ${revenue}, refunds ${refunds}, fees ${fees})" in text
    assert "Against it: share cost $20.00, dollars spent $10.00" in text
    assert margin in text


def test_the_section_names_the_four_windows_it_read(company, month):
    month("40.00", "5.00", "10.00")

    assert f"over the four windows from {WEEK_1} to {THIS_WEEK}" in bar_section(company)


@pytest.mark.parametrize(
    ("revenue", "reached"),
    [
        ("30.00", "Bar reached: 1"),
        ("33.00", "Bar reached: 2"),
        ("140.00", "Bar reached: 3"),
        ("29.99", "Bar reached: 0"),
    ],
)
def test_net_revenue_equal_to_a_line_covers_it(company, month, revenue, reached):
    month(revenue, "0.00", "0.00")

    assert reached in bar_section(company)


def test_the_trial_prices_its_dollars_too(company, month, settings):
    # The trial's dollars add to bar 2's line: 33 + 4 = 37, so a net of 36 falls short of it by 1.
    settings(**{**DIGEST_SETTINGS, "portfolio": {"new_bet_token_share": 0.1, "new_bet_dollars": 4}})
    month("36.00", "0.00", "0.00")

    text = bar_section(company)

    assert "Bar reached: 1" in text
    assert "Margin against bar 2 (Self-funding): -$1.00 (its line is $37.00)" in text


def test_money_and_charges_outside_the_month_do_not_count(company):
    # Inside: revenue 40 against a cost of 5, so bar 1's line is 5 and the net is 40.
    # Before the month, or in the window still open, none of the rest counts.
    reading = seven_day_reading()
    money("revenue", "40.00", when=WEEK_1)
    week_charge(WEEK_4, "5.00", reading)
    money("revenue", "1000.00", when="2026-09-12T23:59:59Z")
    money("spend", "1000.00", when="2026-09-12T23:59:59Z")
    week_charge("2026-09-06T00:00:00Z", "999.00", reading)
    money("revenue", "2000.00", when=THIS_WEEK)
    money("spend", "2000.00", when=LAST_FEW_DAYS)
    week_charge(THIS_WEEK, "888.00", reading)

    text = bar_section(company)

    assert "Net revenue: $40.00 (revenue $40.00, refunds $0.00, fees $0.00)" in text
    assert "Against it: share cost $5.00, dollars spent $0.00" in text


def test_the_newest_charge_of_a_window_and_line_replaces_the_earlier(company):
    # A charge runs more than once a window, and each is the window so far, so only the newest counts.
    reading = seven_day_reading()
    money("revenue", "40.00")
    week_charge(WEEK_4, "1.00", reading)
    week_charge(WEEK_4, "3.00", reading)
    week_charge(WEEK_4, "7.00", reading, line="alpha")

    assert "Against it: share cost $10.00" in bar_section(company)


@pytest.mark.parametrize("read_apart", ["2026-10-04T00:01:00Z", "2026-10-03T23:59:00Z"])
def test_a_window_whose_reset_was_read_a_minute_apart_is_still_one_window(company, read_apart):
    # Daniel's reading from the usage page gives its reset to the minute, so two charges of a window can differ.
    reading = seven_day_reading()
    money("revenue", "40.00")
    week_charge(WEEK_4, "3.00", reading)
    week_charge(read_apart, "4.00", reading)

    assert "Against it: share cost $4.00" in bar_section(company)


def test_no_net_revenue_claims_no_bar_even_with_nothing_to_cover(company):
    seven_day_reading()

    text = bar_section(company)

    assert "Bar reached: 0 (Running)" in text
    assert "Margin against bar 1 (Own share): $0.00 (its line is $0.00)" in text


def test_a_window_with_sessions_and_no_charge_claims_no_bar(company):
    # Its cost is unknown, so bar 1's line of 5 is too low: the margin is at most 35, and no bar is claimed.
    reading = seven_day_reading()
    week_charge(WEEK_3, "5.00", reading)
    money("revenue", "40.00")
    start_session(ALPHA, "cell", reading, bet="alpha", ledger=ledger_at(WEEK_4))

    text = bar_section(company)

    assert "Bar reached: 0 (Running)" in text
    assert f"the window opening {WEEK_4} holds sessions and no charge" in text
    assert "Margin against bar 1 (Own share): at most $35.00" in text


def test_money_in_another_currency_stops_the_sums_and_says_which(company):
    seven_day_reading()
    money("revenue", "40.00")
    seq = money("revenue", "500.00", currency="EUR")

    result = company("digest", "--now", NOW)

    assert result.returncode == 0
    for name in ("Bar", "Bets"):
        text = section(result.stdout, name)
        assert f"cannot be computed: event {seq} is not in USD" in text
        assert "$" not in text


def test_with_no_reading_the_windows_step_back_from_now(company):
    money("revenue", "40.00", when="2026-09-17T12:00:00Z")
    money("revenue", "1000.00", when="2026-09-17T11:59:59Z")

    text = bar_section(company)

    assert "over the four windows from 2026-09-17T12:00:00Z to 2026-10-15T12:00:00Z" in text
    assert "Net revenue: $40.00" in text


def test_a_malformed_reading_does_not_set_the_windows(company):
    # A reading that cannot be true says nothing of the account's windows, so the sound one before it sets them.
    seven_day_reading()
    ledger_at(NOW).append(
        "usage-reading",
        {"window": "seven_day", "used_percent": 500, "resets_at": "2026-10-17T05:00:00Z", "taken_at": NOW, "source": "hand"},
        "board",
    )

    assert f"from {WEEK_1} to {THIS_WEEK}" in bar_section(company)


@pytest.mark.parametrize(
    "change",
    [
        {"company_share": None},
        {"monthly_price": 0},
        {"daily_minutes": "lots"},
        {"portfolio": None},
        {"portfolio": {"new_bet_dollars": 0}},
        {"portfolio": {"new_bet_token_share": 0.1, "new_bet_dollars": -1}},
    ],
)
def test_a_setting_the_digest_needs_refuses_it_with_no_value_assumed(company, settings, change):
    settings(**{**DIGEST_SETTINGS, **change})
    seven_day_reading()

    result = company("digest", "--now", NOW)

    assert result.returncode == 1
    assert result.stdout == ""
    assert "Nothing was computed" in result.stderr


def test_a_digest_writes_nothing_to_the_ledger(company, month):
    month("40.00", "5.00", "10.00")
    before = ledger_at(MONTH_DAY).path.read_bytes()

    assert company("digest", "--now", NOW).returncode == 0

    assert ledger_at(MONTH_DAY).path.read_bytes() == before
