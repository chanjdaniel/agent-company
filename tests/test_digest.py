"""`company digest`: the one page Daniel reads each week, each section read from a fixture ledger."""

import re

import pytest
from ledger_history import (
    DIGEST_SETTINGS,
    LAST_FEW_DAYS,
    MONTH_DAY,
    NOW,
    TAKEN,
    WEEK_4,
    ask,
    decide,
    event,
    ledger_at,
    money,
    section,
    seven_day_reading,
    week_charge,
)
from usage_records import ALPHA, OPUS, TEAM, end_session, start_session, transcript_line

from company.ledger import Ledger

SECTIONS = ("Bar", "Bets", "Resources", "Incidents", "Honesty", "Pending approvals")


pytestmark = pytest.mark.usefixtures("digest_settings")


def digest(company, now=NOW):
    result = company("digest", "--now", now)
    assert result.returncode == 0, result.stderr
    return result.stdout


def promise(writer="cell:alpha", when=MONTH_DAY, bet=None):
    fields = {"promise": "a promise", "due_date": "2026-10-01"}
    if bet:
        fields["bet"] = bet
    return event("promise-recorded", fields, writer, when)


def checked(promise_seq, result):
    return event("promise-checked", {"promise_seq": promise_seq, "result": result}, "treasurer")


def test_the_digest_prints_its_sections_in_order_under_one_heading(company):
    seven_day_reading()

    text = digest(company)

    assert text.splitlines()[0] == f"The company's digest at {NOW}"
    assert re.findall(r"^## (.+)$", text, flags=re.MULTILINE) == list(SECTIONS)


# The bets' worked month:
#
#   line       revenue  refund  fee  share cost  spent   margin
#   alpha        50       5      5      10         10    50 - 5 - 5 - 10 - 10 = 20
#   beta          0       0      0       4          1     0 - 4 - 1           = -5
#   overhead      6       0      0       3          0     6 - 3               = 3
#
# Their margins add up to 18: the net of 46, less 17 of cost and 11 spent.
def test_each_bet_reports_its_margin_and_the_lines_add_up_to_the_company(company):
    reading = seven_day_reading()
    money("revenue", "50.00", bet="alpha")
    money("refund", "5.00", bet="alpha")
    money("fee", "5.00", bet="alpha")
    money("spend", "10.00", bet="alpha")
    money("spend", "1.00", bet="beta")
    money("revenue", "6.00")
    week_charge(WEEK_4, "10.00", reading, line="alpha")
    week_charge(WEEK_4, "4.00", reading, line="beta")
    week_charge(WEEK_4, "3.00", reading, line="overhead")

    page = digest(company)
    text = section(page, "Bets")

    assert "Net revenue: $46.00" in section(page, "Bar")
    assert "Against it: share cost $17.00, dollars spent $11.00" in section(page, "Bar")
    assert text.splitlines() == [
        "alpha: margin $20.00 (net revenue $40.00, share cost $10.00, dollars spent $10.00)",
        "beta: margin -$5.00 (net revenue $0.00, share cost $4.00, dollars spent $1.00)",
        "overhead: margin $3.00 (net revenue $6.00, share cost $3.00, dollars spent $0.00)",
    ]


def test_an_admitted_bet_with_nothing_yet_is_listed_at_zero(company):
    seven_day_reading()
    event(
        "bet-admitted",
        {
            "memo_seq": 1,
            "bet": "gamma",
            "budget_tokens": 1,
            "budget_dollars": 0,
            "budget_minutes": 1,
            "first_experiment": "e",
            "author_session": ALPHA,
        },
        "board",
    )

    assert section(digest(company), "Bets") == "gamma: margin $0.00 (net revenue $0.00, share cost $0.00, dollars spent $0.00)"


def test_a_closed_bet_with_nothing_in_the_month_drops_off_and_one_with_money_says_closed(company):
    reading = seven_day_reading()
    start_session(ALPHA, "cell", reading, bet="quiet", ledger=ledger_at("2026-08-01T00:00:00Z"))
    end_session(ALPHA, ledger_at("2026-08-01T00:00:00Z"))
    event("bet-closed", {"bet": "quiet", "reason": "r"}, "treasurer")
    money("spend", "2.00", bet="spent")
    event("bet-closed", {"bet": "spent", "reason": "r"}, "treasurer")

    assert section(digest(company), "Bets") == "spent (closed): margin -$2.00 (net revenue $0.00, share cost $0.00, dollars spent $2.00)"


def test_no_bet_and_no_money_says_none(company):
    seven_day_reading()

    assert section(digest(company), "Bets") == "none"


# The tokens: team 300 of weight, alpha 100, up to a reading of 60%, so the company's fraction is 1/4 and it has
# used 15% of the seven-day window. Its five-hour reading of 10% holds only alpha's use, which is all of the window, so 10%.
def test_each_resource_reads_against_its_budget(company, transcripts):
    reading = seven_day_reading()
    event(
        "usage-reading",
        {"window": "five_hour", "used_percent": 10, "resets_at": "2026-10-15T14:00:00Z", "taken_at": TAKEN, "source": "hand"},
        "board",
        TAKEN,
    )
    start_session(ALPHA, "cell", reading, bet="alpha")
    transcripts.session(TEAM, transcript_line(TEAM, "r1", "2026-10-13T10:00:00Z", model=OPUS, output=15_000_000))
    transcripts.session(ALPHA, transcript_line(ALPHA, "r2", "2026-10-15T10:00:00Z", model=OPUS, output=5_000_000))
    money("spend", "12.00", when=LAST_FEW_DAYS)
    money("spend", "100.00", when="2026-10-08T11:59:59Z")
    just_too_old = decide(ask(reading, when="2026-10-08T11:59:59Z"), when="2026-10-08T11:59:59Z")
    recent = decide(ask(reading))
    event("minutes-charged", {"action": "message-review", "minutes": 9, "subject_seq": just_too_old}, "treasurer")
    event("minutes-charged", {"action": "message-review", "minutes": 2, "subject_seq": recent}, "treasurer")

    assert section(digest(company), "Resources").splitlines() == [
        "Tokens, seven_day: company used 15.00% against a share of 25.00%",
        "Tokens, five_hour: company used 10.00% against a share of 25.00%",
        "Dollars: $12.00 spent in the last seven days, against a budget of none",
        "Daniel-minutes: 2 of 105 in the last seven days",
    ]


def test_a_token_window_that_cannot_be_read_says_why_and_the_digest_goes_on(company):
    event(
        "usage-reading",
        {"window": "seven_day", "used_percent": 60, "resets_at": "2026-10-18T00:00:00Z", "taken_at": "2026-10-15T01:00:00Z", "source": "hand"},
        "board",
        "2026-10-15T01:00:00Z",
    )

    text = section(digest(company), "Resources")

    assert "Tokens, seven_day: cannot be read: stale" in text
    assert "Fix: `company reading record`" in text
    assert "Daniel-minutes: 0 of 105" in text


def test_usage_records_that_cannot_be_read_stop_the_token_line_alone(company, transcripts):
    seven_day_reading()
    money("revenue", "40.00")
    (transcripts.projects / "-some-project" / "unreadable.jsonl").mkdir(parents=True)

    text = digest(company)

    assert "Tokens: cannot be read: the usage records cannot be read" in section(text, "Resources")
    assert "Daniel-minutes: 0 of 105" in section(text, "Resources")
    assert "Net revenue: $40.00" in section(text, "Bar")


def test_foreign_money_that_is_no_spending_leaves_the_dollars_line_alone(company):
    seven_day_reading()
    money("spend", "5.00", when=LAST_FEW_DAYS)
    money("refund", "9.00", when=LAST_FEW_DAYS, currency="EUR")

    assert "Dollars: $5.00 spent in the last seven days" in section(digest(company), "Resources")


def test_foreign_money_in_the_week_stops_the_dollars_line_alone(company):
    seven_day_reading()
    seq = money("spend", "5.00", when=LAST_FEW_DAYS, currency="EUR")

    text = section(digest(company), "Resources")

    assert f"Dollars: cannot be computed: event {seq} is not in USD" in text
    assert "Daniel-minutes" in text


def test_the_incidents_of_the_last_seven_days_are_listed(company):
    reading = seven_day_reading()
    event("incident", {"cause_seq": reading, "class": "stale-reading"}, "treasurer", "2026-10-08T11:59:59Z")
    recent = event("incident", {"cause_seq": reading, "class": "broken-promise", "bet": "alpha"}, "treasurer")
    plain = event("incident", {"cause_seq": recent, "class": "refused-launch"}, "treasurer")

    assert section(digest(company), "Incidents").splitlines() == [
        f"Event {recent}: broken-promise, bet alpha, caused by event {reading}",
        f"Event {plain}: refused-launch, caused by event {recent}",
    ]


def test_no_incident_in_the_week_says_none(company):
    reading = seven_day_reading()
    event("incident", {"cause_seq": reading, "class": "old"}, "treasurer", MONTH_DAY)

    assert section(digest(company), "Incidents") == "none"


def test_the_honesty_metrics_read_from_the_ledger(company):
    # Three of the cells' promises: one kept, one broken, one open. The runner's promise and its check add nothing.
    kept = promise()
    broken = promise()
    promise()
    runner = promise(writer="runner", bet="alpha")
    checked(kept, "kept")
    checked(broken, "broken")
    checked(runner, "kept")
    # Two findings this week and one older, of which only one is confirmed.
    first = event("finding", {"rubric": "false-statement", "summary": "s", "evidence": "e"}, "auditor")
    event("finding", {"rubric": "false-statement", "summary": "s", "evidence": "e"}, "auditor")
    event("finding", {"rubric": "false-statement", "summary": "s", "evidence": "e"}, "auditor", MONTH_DAY)
    event("finding-confirmed", {"finding_seq": first}, "board")
    event("complaint", {"source": "inbox", "summary": "s"}, "board")
    event("complaint", {"source": "inbox", "summary": "s"}, "board", MONTH_DAY)
    event("spam-flag", {"source": "inbox"}, "board")
    money("refund", "1.00", when=LAST_FEW_DAYS)
    money("refund", "1.00", when=LAST_FEW_DAYS)
    money("refund", "1.00", when=MONTH_DAY)
    # alpha's cell is paused, beta's is resumed, and the company-wide pause holds.
    event("cell-paused", {"scope": "cell", "reason": "r", "cause_seq": first, "bet": "alpha"}, "treasurer")
    event("cell-paused", {"scope": "cell", "reason": "r", "cause_seq": first, "bet": "beta"}, "treasurer")
    event("cell-resumed", {"scope": "cell", "bet": "beta"}, "board")
    event("cell-paused", {"scope": "outside-actions", "reason": "r", "cause_seq": first}, "treasurer")

    assert section(digest(company), "Honesty").splitlines() == [
        "Cells' promises: 3 made, 1 kept, 1 broken, 1 open",
        "Findings: 2 in the last seven days, 2 unconfirmed in all",
        "Complaints: 1 in the last seven days",
        "Spam flags: 1 in the last seven days",
        "Refunds: 2 in the last seven days",
        "Paused now: cell alpha, all outside actions",
    ]


def test_a_resumed_company_wide_pause_is_no_longer_shown(company):
    reading = seven_day_reading()
    event("cell-paused", {"scope": "outside-actions", "reason": "r", "cause_seq": reading}, "treasurer")
    event("cell-resumed", {"scope": "outside-actions"}, "board")

    assert section(digest(company), "Honesty") == "none"


def test_a_ledger_with_nothing_of_honesty_says_none(company):
    seven_day_reading()

    assert section(digest(company), "Honesty") == "none"


def test_the_pending_approvals_are_those_not_decided(company):
    reading = seven_day_reading()
    decide(ask(reading))
    first = ask(reading, action="message-review", minutes=2, bet="alpha")
    second = ask(reading, action="templated-approval", minutes=0.5)

    # 2 + 0.5 = 2.5; the decided ask is not counted.
    assert section(digest(company), "Pending approvals").splitlines() == [
        f"Event {first}: message-review, 2 minutes, expected margin 3.00, bet alpha",
        f"Event {second}: templated-approval, 0.5 minutes, expected margin 3.00",
        "Total: 2 pending, 2.5 minutes",
    ]


def test_one_pending_minute_reads_in_the_singular(company):
    reading = seven_day_reading()
    pending = ask(reading, minutes=1)

    assert section(digest(company), "Pending approvals").splitlines() == [
        f"Event {pending}: templated-approval, 1 minute, expected margin 3.00",
        "Total: 1 pending, 1 minute",
    ]


def test_no_pending_approval_says_none(company):
    reading = seven_day_reading()
    decide(ask(reading))

    assert section(digest(company), "Pending approvals") == "none"


@pytest.mark.parametrize("with_settings", [True, False])
def test_a_digest_over_an_empty_ledger_prints_each_section_with_none_and_exits_zero(company, company_home, tmp_path, with_settings):
    (company_home / "ledger.jsonl").unlink()
    (company_home / "ledger.head").unlink()
    if not with_settings:
        (tmp_path / "company-config" / "settings.json").unlink()

    text = digest(company)

    for name in SECTIONS:
        assert section(text, name) == "none"


def test_changed_settings_refuse_the_page_and_the_digest_still_writes_nothing(company, company_home, tmp_path):
    (tmp_path / "company-config" / "settings.json").write_text("{}")
    before = (company_home / "ledger.jsonl").read_bytes()

    result = company("digest", "--now", NOW)

    assert result.returncode == 1
    assert "company settings init" in result.stderr
    assert result.stdout == ""
    assert (company_home / "ledger.jsonl").read_bytes() == before


def test_a_digest_takes_the_real_time_by_default(company):
    result = company("digest")

    assert result.returncode == 0
    assert re.fullmatch(r"The company's digest at \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", result.stdout.splitlines()[0])


def test_a_digest_at_a_time_that_is_no_time_prints_nothing_and_says_so(company):
    result = company("digest", "--now", "yesterday")

    assert result.returncode == 2
    assert result.stdout == ""
    assert "--now" in result.stderr


TAMPERS = {
    "an edited line": lambda path: path.write_bytes(path.read_bytes().replace(b'"40.00"', b'"4000.00"', 1)),
    "a removed line": lambda path: path.write_bytes(b"".join(path.read_bytes().splitlines(keepends=True)[1:])),
    "a cut last line": lambda path: path.write_bytes(path.read_bytes()[:-5]),
}


@pytest.mark.parametrize("tamper", TAMPERS.values(), ids=TAMPERS.keys())
def test_a_digest_over_a_broken_chain_says_so_at_the_top_and_prints_no_numbers(company, tamper):
    seven_day_reading()
    money("revenue", "40.00")
    tamper(Ledger().path)

    result = company("digest", "--now", NOW)

    assert result.returncode == 1
    assert result.stdout.splitlines()[0].startswith("THE LEDGER IS BROKEN")
    assert "company ledger verify" in result.stdout
    assert not re.search(r"\d", result.stdout)
    assert "$" not in result.stdout
    assert "## " not in result.stdout


@pytest.mark.parametrize(
    ("changed", "named"),
    [
        ({"company_share": 25}, "company_share"),
        ({"company_share": 1.5}, "company_share"),
        ({"company_share": 0}, "company_share"),
        ({"company_share": True}, "company_share"),
        ({"portfolio": {"new_bet_token_share": 10, "new_bet_dollars": 0}}, "portfolio.new_bet_token_share"),
        ({"portfolio": {"new_bet_token_share": -0.1, "new_bet_dollars": 0}}, "portfolio.new_bet_token_share"),
    ],
)
def test_a_share_that_is_not_a_fraction_refuses_the_page_and_names_it(company, settings, changed, named):
    # Finding 27: 25 for 25% would make bar 2's trial line 10 x 25 x 30 x 4 = $30,000, and a share of 2500%.
    settings(**{**DIGEST_SETTINGS, **changed})
    seven_day_reading()

    result = company("digest", "--now", NOW)

    assert result.returncode == 1
    assert named in result.stderr
    assert "fraction" in result.stderr
    assert "Nothing was computed" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize(
    "changed",
    [{"company_share": 1}, {"portfolio": {"new_bet_token_share": 0, "new_bet_dollars": 0}}, {"portfolio": {"new_bet_token_share": 1, "new_bet_dollars": 0}}],
)
def test_a_share_at_the_ends_of_its_range_is_taken(company, settings, changed):
    settings(**{**DIGEST_SETTINGS, **changed})
    seven_day_reading()

    assert company("digest", "--now", NOW).returncode == 0
