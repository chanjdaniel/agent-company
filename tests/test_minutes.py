"""Daniel-minutes and the week's share: what `company treasurer charge` writes, and what a correction replaces."""

import pytest
from ledger_history import (
    DIGEST_SETTINGS,
    LAST_FEW_DAYS,
    NOW,
    RESETS,
    TAKEN,
    ask,
    decide,
    event,
    ledger_at,
    money,
    section,
    seven_day_reading,
)
from usage_records import ALPHA, OPUS, PROBE, TEAM, start_session, transcript_line

from company import cli
from company.ledger import Ledger, LedgerBroken

pytestmark = pytest.mark.usefixtures("digest_settings")


def events_of(kind):
    return [e for e in Ledger().read() if e["kind"] == kind]


def charge(company, now=NOW):
    return company("treasurer", "charge", "--now", now)


def minutes_line(company, now=NOW):
    result = company("digest", "--now", now)
    assert result.returncode == 0, result.stderr
    return next(line for line in section(result.stdout, "Resources").splitlines() if line.startswith("Daniel-minutes"))


def sent_draft():
    """A send Daniel confirmed, of a draft that the cell of bet `alpha` wrote; returns its seq."""
    target = event(
        "target-proposed", {"contact": "someone@example.com", "organization": "Example", "reason": "r", "source": "s"}, "cell:alpha"
    )
    draft = event(
        "draft-proposed", {"target_seq": target, "body": "b", "claims": [], "disclosure": "d", "unsubscribe": "u"}, "cell:alpha"
    )
    return event("send-confirmed", {"draft_seq": draft, "sent_at": LAST_FEW_DAYS}, "board")


def test_a_decided_approval_charges_its_action_from_the_table(company):
    seven_day_reading()
    decided = decide(ask(1, action="new-public-artifact", minutes=99, bet="alpha"))

    result = charge(company)

    assert result.returncode == 0, result.stderr
    [charged] = events_of("minutes-charged")
    assert charged["writer"] == "treasurer"
    assert charged["action"] == "new-public-artifact"
    assert charged["minutes"] == 5
    assert charged["subject_seq"] == decided
    assert charged["bet"] == "alpha"


def test_a_refused_approval_took_the_same_minutes(company):
    seven_day_reading()
    decide(ask(1), decision="rejected")

    charge(company)

    assert [e["minutes"] for e in events_of("minutes-charged")] == [0.5]


def test_an_undecided_approval_charges_nothing(company):
    seven_day_reading()
    ask(1)

    charge(company)

    assert events_of("minutes-charged") == []


def test_an_outreach_send_charges_a_message_review_to_the_cell_that_wrote_it(company):
    seven_day_reading()
    sent = sent_draft()

    result = charge(company)

    assert result.returncode == 0, result.stderr
    [charged] = events_of("minutes-charged")
    assert (charged["action"], charged["minutes"], charged["subject_seq"], charged["bet"]) == ("message-review", 2, sent, "alpha")


def test_charging_twice_charges_once(company):
    seven_day_reading()
    decide(ask(1))
    sent_draft()

    charge(company)
    charge(company)

    assert len(events_of("minutes-charged")) == 2


def test_the_digest_totals_the_charges_against_the_weeks_budget(company):
    # 0.5 for the templated approval, 2 for the send, and 15 x 7 = 105 for the week's budget.
    seven_day_reading()
    decide(ask(1))
    sent_draft()
    charge(company)

    assert minutes_line(company) == "Daniel-minutes: 2.5 of 105 in the last seven days"


def test_a_correction_replaces_the_estimate_in_the_total(company):
    # The send's 2 becomes 6, so 0.5 + 6 = 6.5.
    seven_day_reading()
    decide(ask(1))
    sent_draft()
    charge(company)
    charged = events_of("minutes-charged")[-1]["seq"]

    result = company("minutes", "correct", "--charge", str(charged), "--minutes", "6", "--reason", "it took longer")

    assert result.returncode == 0, result.stderr
    [corrected] = events_of("minutes-corrected")
    assert (corrected["writer"], corrected["charge_seq"], corrected["minutes"], corrected["reason"]) == ("board", charged, 6, "it took longer")
    assert minutes_line(company) == "Daniel-minutes: 6.5 of 105 in the last seven days"


def test_the_newest_correction_stands_and_may_be_zero(company):
    seven_day_reading()
    decide(ask(1))
    charge(company)
    charged = events_of("minutes-charged")[0]["seq"]

    company("minutes", "correct", "--charge", str(charged), "--minutes", "9")
    company("minutes", "correct", "--charge", str(charged), "--minutes", "0")

    assert minutes_line(company) == "Daniel-minutes: 0 of 105 in the last seven days"


def test_charging_again_after_a_correction_leaves_it_standing(company):
    seven_day_reading()
    decide(ask(1))
    charge(company)
    company("minutes", "correct", "--charge", str(events_of("minutes-charged")[0]["seq"]), "--minutes", "4")

    charge(company)

    assert minutes_line(company) == "Daniel-minutes: 4 of 105 in the last seven days"


def test_a_correction_must_cite_a_charge(company):
    reading = seven_day_reading()

    result = company("minutes", "correct", "--charge", str(reading), "--minutes", "4")

    assert result.returncode == 1
    assert f"event {reading} is not a minutes charge" in result.stderr
    assert "Nothing was recorded" in result.stderr
    assert events_of("minutes-corrected") == []
    [refused] = events_of("append-refused")
    assert (refused["attempted_kind"], refused["attempted_writer"], refused["reason"]) == ("minutes-corrected", "board", "not-a-charge")
    assert f"event {refused['seq']} in the ledger" in result.stderr


def test_a_negative_correction_is_refused_and_logged(company):
    seven_day_reading()
    decide(ask(1))
    charge(company)

    result = company("minutes", "correct", "--charge", str(events_of("minutes-charged")[0]["seq"]), "--minutes", "-4")

    assert result.returncode == 1
    assert events_of("minutes-corrected") == []
    assert events_of("append-refused")[-1]["reason"] == "bad-field:minutes"


def test_minutes_count_in_the_week_of_the_decision_however_late_the_charge_or_correction(company):
    # The decision is weeks before NOW, and both its charge and the correction are written on the real clock, after it.
    seven_day_reading()
    decide(ask(1, when="2026-09-25T09:00:00Z"), when="2026-09-25T09:00:00Z")
    charge(company)
    charged = events_of("minutes-charged")[0]["seq"]

    company("minutes", "correct", "--charge", str(charged), "--minutes", "8")

    assert minutes_line(company) == "Daniel-minutes: 0 of 105 in the last seven days"


def test_a_second_charge_of_one_subject_counts_once(company):
    # Two charges racing can both read that a subject has none yet; the total still counts it once.
    seven_day_reading()
    decided = decide(ask(1))
    for _ in range(2):
        event("minutes-charged", {"action": "templated-approval", "minutes": 0.5, "subject_seq": decided}, "treasurer")

    assert minutes_line(company) == "Daniel-minutes: 0.5 of 105 in the last seven days"


def test_a_correction_of_the_second_of_two_racing_charges_still_stands(company):
    seven_day_reading()
    decided = decide(ask(1))
    for _ in range(2):
        event("minutes-charged", {"action": "templated-approval", "minutes": 0.5, "subject_seq": decided}, "treasurer")

    company("minutes", "correct", "--charge", str(events_of("minutes-charged")[1]["seq"]), "--minutes", "3")

    assert minutes_line(company) == "Daniel-minutes: 3 of 105 in the last seven days"


def test_a_decision_not_charged_yet_is_said_beside_the_total(company):
    seven_day_reading()
    decide(ask(1))
    sent_draft()

    assert minutes_line(company) == (
        "Daniel-minutes: 0 of 105 in the last seven days; 2 decisions are not charged yet: `company treasurer charge` charges them, or says why not"
    )


def test_an_action_missing_from_the_table_is_said_and_the_rest_are_charged(company):
    seven_day_reading()
    unknown = decide(ask(1, action="something-else"))
    known = decide(ask(1))

    result = charge(company)

    assert result.returncode == 1
    assert f"event {unknown}" in result.stderr
    assert "not in the minutes table" in result.stderr
    assert [e["subject_seq"] for e in events_of("minutes-charged")] == [known]


def test_a_decision_citing_no_ask_is_said(company):
    reading = seven_day_reading()
    decided = decide(reading)

    result = charge(company)

    assert result.returncode == 1
    assert f"event {decided}" in result.stderr
    assert events_of("minutes-charged") == []


@pytest.mark.parametrize(
    "table",
    [None, "lots", {"templated-approval": -1}, {"templated-approval": "half"}, {"templated-approval": True}],
)
def test_a_bad_minutes_table_refuses_and_charges_nothing(company, settings, table):
    settings(**{**DIGEST_SETTINGS, "minutes_table": table})
    seven_day_reading()
    decide(ask(1))

    result = charge(company)

    assert result.returncode == 1
    assert "minutes_table" in result.stderr
    assert "Nothing was charged" in result.stderr
    assert events_of("minutes-charged") == []


# The worked charge, on a $130 monthly price, so a weekly price of $30.
#
#   team         15,000,000 Opus   300 of weight
#   alpha (bet)   5,000,000 Opus   100
#   probe         5,000,000 Opus   100 (no bet: overhead)
#
#   all weight 500; the company's 200; the reading says 60%, and no use follows it.
#   company_fraction = 200 / 500 = 0.4, company_used = 0.4 x 60 = 24%, company_cost = 24 / 100 x 30 = $7.20
#   alpha:    fraction 100 / 500 = 0.2, company_used 12%, cost 7.20 / 2 = $3.60
#   overhead: the same.
@pytest.fixture
def worked_week(transcripts):
    reading = seven_day_reading()
    start_session(ALPHA, "cell", reading, bet="alpha")
    start_session(PROBE, "probe", reading)
    day = "2026-10-13T10:00:00Z"
    transcripts.session(TEAM, transcript_line(TEAM, "r1", day, model=OPUS, output=15_000_000))
    transcripts.session(ALPHA, transcript_line(ALPHA, "r2", day, model=OPUS, output=5_000_000))
    transcripts.session(PROBE, transcript_line(PROBE, "r3", day, model=OPUS, output=5_000_000))
    return reading


def test_the_week_is_charged_line_by_line_from_the_share(company, worked_week):
    result = charge(company)

    assert result.returncode == 0, result.stderr
    lines = {e["line"]: e for e in events_of("resource-charged")}
    assert set(lines) == {"alpha", "overhead"}
    for line in lines.values():
        assert line["writer"] == "treasurer"
        assert line["week_start"] == "2026-10-11T00:00:00Z"
        assert line["weight"] == pytest.approx(100)
        assert line["fraction"] == pytest.approx(0.2)
        assert line["company_used"] == pytest.approx(12)
        assert line["cost"] == "3.600000"
        assert line["reading_seq"] == worked_week


def test_charging_the_week_again_with_nothing_new_writes_nothing(company, worked_week):
    charge(company)
    charge(company)

    assert len(events_of("resource-charged")) == 2


def test_charging_the_week_after_more_use_writes_what_changed(company, transcripts, worked_week):
    charge(company)
    # 2,500,000 more on alpha is 50 more of weight, up to the same 60%, so all 550, and 60% of the $30 is $18.
    # alpha's 150 costs 150 / 550 x 18 = 4.909091, and overhead's 100 costs 100 / 550 x 18 = 3.272727.
    transcripts.session(
        ALPHA,
        transcript_line(ALPHA, "r2", "2026-10-13T10:00:00Z", model=OPUS, output=5_000_000),
        transcript_line(ALPHA, "r4", "2026-10-13T11:00:00Z", model=OPUS, output=2_500_000),
    )

    charge(company)

    assert [(e["line"], e["cost"]) for e in events_of("resource-charged")[2:]] == [("alpha", "4.909091"), ("overhead", "3.272727")]


def test_a_charged_week_reaches_the_ladder_once_its_window_is_complete(company, worked_week):
    # The window reset on 18 October. A week on, it is a complete window, whose $7.20 is in bar 1's line.
    money("revenue", "10.00", when="2026-10-14T09:00:00Z")
    charge(company)

    result = company("digest", "--now", "2026-10-19T12:00:00Z")

    assert result.returncode == 0, result.stderr
    text = section(result.stdout, "Bar")
    assert "Bar reached: 1 (Own share)" in text
    assert "Against it: share cost $7.20, dollars spent $0.00" in text
    assert "Net revenue: $10.00" in text


def test_a_week_that_cannot_be_read_is_said_and_the_minutes_are_still_charged(company):
    decided = ledger_at(LAST_FEW_DAYS).append(
        "usage-reading",
        {"window": "five_hour", "used_percent": 1, "resets_at": RESETS, "taken_at": TAKEN, "source": "hand"},
        "board",
    )["seq"]
    decide(ask(decided))

    result = charge(company)

    assert result.returncode == 1
    assert "no-reading" in result.stderr
    assert "company reading record" in result.stderr
    assert len(events_of("minutes-charged")) == 1
    assert events_of("resource-charged") == []


def test_a_charge_at_a_time_that_is_no_time_charges_nothing_and_says_so(company):
    seven_day_reading()
    decide(ask(1))

    result = company("treasurer", "charge", "--now", "yesterday")

    assert result.returncode == 2
    assert "Nothing was charged" in result.stderr
    assert events_of("minutes-charged") == []


def _refuse_appends(*_args, **_kwargs):
    raise LedgerBroken("the ledger's end does not match its head record")


def test_a_charge_stopped_part_way_says_so_and_that_running_it_again_is_safe(monkeypatch, capsys):
    seven_day_reading()
    decide(ask(1))
    monkeypatch.setattr(Ledger, "append", _refuse_appends)

    assert cli.main(["treasurer", "charge", "--now", NOW]) == 1

    message = capsys.readouterr().err
    assert "The charge stopped there" in message
    assert "charges only what is still owed" in message


def test_a_correction_the_ledger_will_not_take_says_nothing_was_recorded(monkeypatch, capsys, company):
    seven_day_reading()
    decide(ask(1))
    charge(company)
    charged = events_of("minutes-charged")[0]["seq"]
    monkeypatch.setattr(Ledger, "append", _refuse_appends)

    assert cli.main(["minutes", "correct", "--charge", str(charged), "--minutes", "4"]) == 1

    assert "Nothing was recorded" in capsys.readouterr().err


def test_charging_on_a_broken_ledger_writes_nothing(company):
    seven_day_reading()
    decide(ask(1))
    path = Ledger().path
    path.write_bytes(path.read_bytes().replace(b'"hand"', b'"hend"', 1))
    before = path.read_bytes()

    result = charge(company)

    assert result.returncode == 1
    assert "LEDGER BROKEN" in result.stdout
    assert path.read_bytes() == before
