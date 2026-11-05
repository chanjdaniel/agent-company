"""The honesty loop: a promise checked when due, a broken one pausing its cell, and complaints pausing outside actions.

Every test drives the installed `company` command, or a cell's company tools over stdio, and reads the ledger and the digest.
Each fixture's time is in the past of the real clock, and a boundary sets the check's clock through `ledger_history.run_at`.
"""

import os
from datetime import timedelta

import pytest
from ledger_history import event, run_at, section
from quant_tools import CellTools, text_of
from session_checks import events

from company import launcher, times
from company.ledger import Ledger

DUE = "2026-10-01"
BEFORE_DUE = "2026-09-28T09:00:00Z"
ON_DUE = "2026-10-01T23:00:00Z"
AFTER_DUE = "2026-10-02T00:30:00Z"
PERIOD_TEXT = "The paper period of strategy momentum closes by 2026-10-01."
DRAFT_FIELDS = '{"target_seq": 1, "body": "b", "claims": [], "disclosure": "d", "unsubscribe": "u"}'


def promise(writer="cell:alpha", due=DUE, text="a promise"):
    fields = {"promise": text, "due_date": due}
    if writer == "runner":
        fields["bet"] = "alpha"
    return event("promise-recorded", fields, writer, BEFORE_DUE)


def period(promise_seq):
    """A paper period holding a runner's promise, citing the promise itself where a verdict would go, as only a seq is asked of them."""
    fields = {"registration_seq": promise_seq, "verdict_seq": promise_seq, "end_date": DUE, "drawdown_kill": 0.2, "promise_seq": promise_seq}
    return event("paper-opened", fields, "runner", BEFORE_DUE)


def close(period_seq, when):
    return event("paper-closed", {"period_seq": period_seq, "reason": "end-date", "equity": "100"}, "runner", when)


def checked_results():
    return [(found["promise_seq"], found["result"]) for found in events("promise-checked")]


def nothing_against_the_cell():
    return events("finding") == [] and events("finding-confirmed") == [] and events("cell-paused") == []


@pytest.fixture
def check(company):
    def run():
        done = company("treasurer", "check")
        assert done.returncode == 0, done.stdout + done.stderr
        return done

    return run


@pytest.fixture
def launch_answer(company):
    def run(bet="alpha"):
        return company("governor", "check", "cell", "--bet", bet)

    return run


def honesty_section(company):
    done = company("digest")
    assert done.returncode == 0, done.stderr
    return section(done.stdout, "Honesty")


# A cell's promise


def test_an_overdue_promise_is_a_finding_that_pauses_the_cell_and_refuses_its_next_launch(company, board, check, launch_answer):
    assert launch_answer().returncode == 0
    seq = promise()

    done = check()

    assert checked_results() == [(seq, "broken")]
    finding = events("finding")[0]
    assert (finding["writer"], finding["rubric"], finding["bet"], finding["promise_seq"]) == ("treasurer", "broken-promise", "alpha", seq)
    assert [(found["writer"], found["finding_seq"]) for found in events("finding-confirmed")] == [("treasurer", finding["seq"])]
    pause = events("cell-paused")[0]
    assert (pause["writer"], pause["scope"], pause["bet"], pause["cause_seq"]) == ("treasurer", "cell", "alpha", finding["seq"])
    assert "company cell resume --bet alpha" in done.stdout
    refused = launch_answer()
    assert refused.returncode == 1
    assert "pause check" in refused.stdout
    assert "company cell resume --bet alpha" in refused.stdout
    assert events("launch-refused")[-1]["check"] == "pause"
    assert launch_answer("beta").returncode == 0


def test_a_promise_kept_by_its_due_date_is_logged_as_kept_with_no_finding(company, board, check, launch_answer):
    seq = promise()

    done = company("promise", "kept", str(seq), "--on", DUE, "--note", "delivered")

    assert done.returncode == 0, done.stderr
    kept = events("promise-kept")[0]
    assert (kept["writer"], kept["promise_seq"], kept["kept_date"], kept["note"]) == ("board", seq, DUE, "delivered")
    check()
    assert [(found["promise_seq"], found["result"], found["evidence_seqs"]) for found in events("promise-checked")] == [(seq, "kept", [kept["seq"]])]
    assert nothing_against_the_cell()
    assert launch_answer().returncode == 0


def test_a_promise_is_read_as_kept_at_the_first_check_after_daniels_word_even_before_it_falls_due(company, digest_settings, check):
    seq = promise(due="2099-01-01")
    assert company("promise", "kept", str(seq)).returncode == 0

    check()

    assert checked_results() == [(seq, "kept")]


@pytest.mark.parametrize(("clock", "result"), [("2026-10-01T23:59:00Z", []), ("2026-10-02T00:00:00Z", "broken")])
def test_a_promise_falls_overdue_when_its_due_date_has_ended_in_utc(digest_settings, clock, result):
    seq = promise()

    done = run_at(clock, "treasurer", "check")

    assert done.returncode == 0, done.stdout + done.stderr
    assert checked_results() == ([(seq, result)] if result else [])


def test_a_promise_not_yet_due_stays_open_and_nothing_is_logged(company, digest_settings, check):
    promise(due="2099-01-01")
    before = events()

    done = check()

    assert events() == before
    assert "No promise" in done.stdout
    assert "1 made, 0 kept, 0 broken, 1 open" in honesty_section(company)


def test_kept_on_the_due_date_itself_is_in_time(company, digest_settings, check):
    seq = promise()
    assert company("promise", "kept", str(seq), "--on", DUE).returncode == 0

    check()

    assert checked_results() == [(seq, "kept")]


@pytest.mark.parametrize(
    ("make", "reason", "words"),
    [
        (lambda company: 999, None, None),
        (lambda company: promise(writer="runner"), "not-a-cells-promise", "the code's own"),
        (lambda company: event("usage-reading", {"window": "seven_day", "used_percent": 1, "resets_at": ON_DUE, "taken_at": ON_DUE, "source": "hand"}, "board"), "no-such-promise", "no promise"),
    ],
)
def test_daniels_word_on_what_is_no_cells_promise_is_refused_and_logged(company, digest_settings, make, reason, words):
    seq = make(company)
    if reason is None:
        reason, words = "no-such-promise", "no promise"

    done = company("promise", "kept", str(seq), "--on", DUE)

    assert done.returncode == 1
    assert words in done.stderr
    assert "Nothing was recorded" in done.stderr
    assert events("promise-kept") == []
    assert (events("append-refused")[-1]["attempted_kind"], events("append-refused")[-1]["reason"]) == ("promise-kept", reason)


def test_a_word_after_the_due_date_is_refused_since_that_promise_is_broken(company, digest_settings, check):
    seq = promise()

    done = company("promise", "kept", str(seq), "--on", "2026-10-02")

    assert done.returncode == 1
    assert DUE in done.stderr
    assert events("append-refused")[-1]["reason"] == "after-its-due-date"
    check()
    assert checked_results() == [(seq, "broken")]


def test_a_word_with_no_date_means_today_so_it_is_refused_once_the_date_has_passed(company, digest_settings):
    seq = promise()

    done = company("promise", "kept", str(seq))

    assert done.returncode == 1
    assert "--on" in done.stderr
    assert events("promise-kept") == []


def test_a_word_on_a_promise_already_checked_or_already_kept_is_refused(company, digest_settings, check):
    broken = promise()
    check()
    done = company("promise", "kept", str(broken), "--on", DUE)
    assert done.returncode == 1
    assert "broken" in done.stderr
    assert events("append-refused")[-1]["reason"] == "already-checked"

    kept = promise(due="2099-01-01")
    assert company("promise", "kept", str(kept)).returncode == 0
    done = company("promise", "kept", str(kept))
    assert done.returncode == 1
    assert events("append-refused")[-1]["reason"] == "already-kept"
    assert len(events("promise-kept")) == 1


def test_a_word_after_a_check_stopped_part_way_is_refused_since_it_read_the_promise_as_broken(company, digest_settings, check):
    seq = promise()
    finding = event("finding", {"rubric": "broken-promise", "summary": "s", "evidence": "e", "bet": "alpha", "promise_seq": seq}, "treasurer")

    done = company("promise", "kept", str(seq), "--on", DUE)

    assert done.returncode == 1
    assert str(finding) in done.stderr
    assert "company cell resume --bet alpha" in done.stderr
    assert events("append-refused")[-1]["reason"] == "already-found-broken"
    assert events("promise-kept") == []
    check()
    assert checked_results() == [(seq, "broken")]
    assert [found["finding_seq"] for found in events("finding-confirmed")] == [finding]


def test_a_word_of_a_day_before_the_promise_was_made_is_refused(company, digest_settings):
    seq = promise()

    done = company("promise", "kept", str(seq), "--on", "2001-01-01")

    assert done.returncode == 1
    assert "2026-09-28" in done.stderr
    assert events("append-refused")[-1]["reason"] == "before-it-was-made"
    assert events("promise-kept") == []


def test_a_word_written_past_the_command_with_a_late_day_still_reads_as_broken(digest_settings, check):
    seq = promise()
    event("promise-kept", {"promise_seq": seq, "kept_date": "2026-10-02"}, "board")

    check()

    assert checked_results() == [(seq, "broken")]


@pytest.mark.parametrize("day", ["next week", "2026-13-01", "2999-01-01"])
def test_a_word_on_a_day_that_cannot_be_true_records_nothing(company, digest_settings, day):
    seq = promise(due="2999-12-31")
    before = events()

    done = company("promise", "kept", str(seq), "--on", day)

    assert done.returncode == 2
    assert "Nothing was recorded" in done.stderr
    assert events() == before


# A runner's promise


@pytest.mark.parametrize("closed_late", [False, True], ids=["no-close", "closed-after-the-due-date"])
def test_a_runners_promise_past_its_date_is_not_run_and_nothing_goes_against_the_cell(company, board, check, launch_answer, closed_late):
    seq = promise(writer="runner", text=PERIOD_TEXT)
    opened = period(seq)
    if closed_late:
        close(opened, AFTER_DUE)

    done = check()

    assert checked_results() == [(seq, "not-run")]
    assert nothing_against_the_cell()
    assert launch_answer().returncode == 0
    assert "not run" in done.stdout
    honesty = honesty_section(company).splitlines()
    assert honesty == [f"The code's promise, not run and no cell's doing: event {seq}, bet alpha, due {DUE}: {PERIOD_TEXT}"]


def test_a_runners_promise_with_no_period_at_all_reads_as_not_run(digest_settings, check):
    # A crash between the promise and its period leaves this, and nothing ran.
    seq = promise(writer="runner")

    check()

    assert checked_results() == [(seq, "not-run")]
    assert nothing_against_the_cell()


@pytest.mark.parametrize("when", [BEFORE_DUE, ON_DUE], ids=["before", "on-the-day"])
def test_a_runners_promise_closed_by_its_date_is_kept_and_adds_nothing_to_the_cells_promises(company, digest_settings, check, when):
    seq = promise(writer="runner")
    closed = close(period(seq), when)

    check()

    assert [(found["promise_seq"], found["result"], found["evidence_seqs"]) for found in events("promise-checked")] == [(seq, "kept", [closed])]
    assert nothing_against_the_cell()
    assert honesty_section(company) == "none"


def test_the_digest_names_each_open_promise_so_that_daniel_can_say_it_was_kept(company, digest_settings, check):
    seq = promise(due="2099-01-01", text="deliver\nthe report")
    kept = promise(due="2099-01-01")
    assert company("promise", "kept", str(kept)).returncode == 0
    promise(writer="runner", due="2099-01-01")
    check()

    honesty = honesty_section(company).splitlines()

    assert honesty == [
        "Cells' promises: 2 made, 1 kept, 0 broken, 1 open",
        f"Open: event {seq}, bet alpha, due 2099-01-01, kept only if you say so with `company promise kept {seq}`: deliver the report",
    ]


def test_a_cells_promises_are_counted_apart_from_a_runners_not_run(company, digest_settings, check):
    kept = promise(due="2099-01-01")
    assert company("promise", "kept", str(kept)).returncode == 0
    promise()
    promise(due="2099-01-01")
    runner = promise(writer="runner", text=PERIOD_TEXT)

    check()

    honesty = honesty_section(company).splitlines()
    assert honesty[0] == "Cells' promises: 3 made, 1 kept, 1 broken, 1 open"
    assert f"The code's promise, not run and no cell's doing: event {runner}, bet alpha, due {DUE}: {PERIOD_TEXT}" in honesty
    assert "Findings: 1 in the last seven days, 0 unconfirmed in all" in honesty
    assert "Paused now: cell alpha" in honesty


@pytest.mark.parametrize(("clock", "result"), [("2026-10-01T23:59:00Z", []), ("2026-10-02T00:00:00Z", "not-run")])
def test_a_runners_promise_is_not_run_only_when_its_due_date_has_ended_in_utc(digest_settings, clock, result):
    seq = promise(writer="runner")
    period(seq)

    done = run_at(clock, "treasurer", "check")

    assert done.returncode == 0, done.stdout + done.stderr
    assert checked_results() == ([(seq, result)] if result else [])


def test_only_the_close_of_a_promises_own_period_keeps_it(digest_settings, check):
    first, second = promise(writer="runner"), promise(writer="runner")
    period(first)
    closed = close(period(second), BEFORE_DUE)

    check()

    assert [(found["promise_seq"], found["result"], found["evidence_seqs"]) for found in events("promise-checked")] == [(first, "not-run", []), (second, "kept", [closed])]


def test_a_runners_promise_not_yet_due_with_its_period_open_waits(digest_settings, check):
    seq = promise(writer="runner", due="2099-01-01")
    period(seq)
    before = events()

    check()

    assert events() == before


# Safe to run twice


def test_a_second_check_logs_no_second_finding_and_no_second_result(digest_settings, check):
    seq = promise()
    check()
    before = events()

    check()

    assert events() == before
    assert checked_results() == [(seq, "broken")]


def test_a_check_a_late_tick_and_another_check_leave_one_result(digest_settings, check):
    seq = promise(writer="runner")
    opened = period(seq)
    check()
    close(opened, AFTER_DUE)

    check()

    assert checked_results() == [(seq, "not-run")]


def test_two_broken_promises_of_one_cell_are_a_finding_each(digest_settings, check):
    first, second = promise(), promise()

    check()

    assert sorted(found["promise_seq"] for found in events("finding")) == [first, second]
    assert len(events("cell-paused")) == 2


@pytest.mark.parametrize("written", [1, 2, 3], ids=["finding", "confirmed", "paused"])
def test_a_check_stopped_part_way_is_finished_by_the_next_with_nothing_twice(digest_settings, check, written):
    seq = promise()
    finding = event("finding", {"rubric": "broken-promise", "summary": "s", "evidence": "e", "bet": "alpha", "promise_seq": seq}, "treasurer")
    if written >= 2:
        event("finding-confirmed", {"finding_seq": finding}, "treasurer")
    if written >= 3:
        event("cell-paused", {"scope": "cell", "reason": "r", "cause_seq": finding, "bet": "alpha"}, "treasurer")

    check()

    assert [found["seq"] for found in events("finding")] == [finding]
    assert [found["finding_seq"] for found in events("finding-confirmed")] == [finding]
    assert [found["cause_seq"] for found in events("cell-paused")] == [finding]
    assert checked_results() == [(seq, "broken")]


def test_a_check_on_a_broken_ledger_writes_nothing_and_says_so(company, company_home):
    promise()
    with (company_home / "ledger.jsonl").open("a") as file:
        file.write("not an event\n")
    before = (company_home / "ledger.jsonl").read_bytes()

    done = company("treasurer", "check")

    assert done.returncode == 1
    assert "LEDGER BROKEN" in done.stdout
    assert (company_home / "ledger.jsonl").read_bytes() == before


def test_a_check_with_no_settings_still_checks_every_promise(company):
    # Settings are read only for the complaint threshold, so that their loss cannot keep a broken promise unread.
    seq = promise()

    done = company("treasurer", "check")

    assert done.returncode == 0, done.stderr
    assert checked_results() == [(seq, "broken")]


# Only Daniel resumes


def test_a_paused_cell_resumes_by_daniels_command_logged_as_board(company, board, check, launch_answer):
    promise()
    check()
    assert launch_answer().returncode == 1

    done = company("cell", "resume", "--bet", "alpha", "--message", "1234")

    assert done.returncode == 0, done.stderr
    resumed = events("cell-resumed")[0]
    assert (resumed["writer"], resumed["scope"], resumed["bet"], resumed["message"]) == ("board", "cell", "alpha", "1234")
    assert launch_answer().returncode == 0
    assert "Paused now" not in honesty_section(company)


def test_a_check_does_not_pause_again_for_a_promise_daniel_has_resumed_past(company, board, check, launch_answer):
    promise()
    check()
    assert company("cell", "resume", "--bet", "alpha").returncode == 0

    check()

    assert launch_answer().returncode == 0
    assert len(events("cell-paused")) == 1


def test_a_check_finishing_after_a_resume_does_not_pause_again(company, digest_settings, check):
    # The pause is written and resumed, and the check that wrote it stopped before its `promise-checked`.
    seq = promise()
    finding = event("finding", {"rubric": "broken-promise", "summary": "s", "evidence": "e", "bet": "alpha", "promise_seq": seq}, "treasurer")
    event("finding-confirmed", {"finding_seq": finding}, "treasurer")
    event("cell-paused", {"scope": "cell", "reason": "r", "cause_seq": finding, "bet": "alpha"}, "treasurer")
    assert company("cell", "resume", "--bet", "alpha").returncode == 0

    check()

    assert len(events("cell-paused")) == 1
    assert checked_results() == [(seq, "broken")]


def test_resuming_one_cell_leaves_another_paused(company, board, check, launch_answer):
    promise()
    promise(writer="cell:beta")
    check()

    assert company("cell", "resume", "--bet", "alpha").returncode == 0

    assert launch_answer("alpha").returncode == 0
    assert launch_answer("beta").returncode == 1


def test_a_resume_with_nothing_paused_is_refused_and_logged(company, digest_settings):
    done = company("cell", "resume", "--bet", "alpha")

    assert done.returncode == 1
    assert "not paused" in done.stderr
    assert events("cell-resumed") == []
    assert (events("append-refused")[-1]["attempted_kind"], events("append-refused")[-1]["reason"]) == ("cell-resumed", "not-paused")


@pytest.mark.parametrize("arguments", [(), ("--bet", "alpha", "--outside-actions")])
def test_a_resume_names_one_cell_or_the_outside_actions(company, arguments):
    assert company("cell", "resume", *arguments).returncode == 2


@pytest.mark.parametrize("writer", ["treasurer", "governor", "scheduler", "cell:alpha", "auditor"])
def test_no_writer_but_board_can_resume_a_cell(company, writer):
    done = company("ledger", "append", "cell-resumed", "--writer", writer, "--fields", '{"scope": "cell", "bet": "alpha"}')

    assert done.returncode == 1
    assert events("cell-resumed") == []


@pytest.mark.parametrize(
    "arguments",
    [
        ("cell", "resume", "--bet", "alpha"),
        ("promise", "kept", "1"),
        ("complaint", "record", "--source", "inbox", "--summary", "s"),
        ("spam-flag", "record", "--source", "inbox"),
        ("treasurer", "check"),
        ("schedule", "run", "treasurer-check"),
    ],
)
def test_none_of_daniels_honesty_commands_runs_inside_a_session(company, arguments):
    env = {**os.environ, launcher.SESSION_VARIABLE: "eeeeeeee-0000-4000-8000-000000000000"}

    done = company(*arguments, env=env)

    assert done.returncode == 1
    assert "only through its company tools" in done.stderr
    assert [found["kind"] for found in events()] == ["append-refused"]


# Complaints and spam flags


def complaint(company):
    done = company("complaint", "record", "--source", "inbox", "--summary", "a person wrote to say so", "--bet", "alpha")
    assert done.returncode == 0, done.stdout + done.stderr
    return done


def spam_flag(company):
    done = company("spam-flag", "record", "--source", "inbox", "--contact", "someone@example.com")
    assert done.returncode == 0, done.stdout + done.stderr
    return done


def draft(company):
    return company("ledger", "append", "draft-proposed", "--writer", "cell:alpha", "--fields", DRAFT_FIELDS)


@pytest.fixture
def daniels_settings(company):
    from usage_records import SETTINGS_INIT

    done = company(*SETTINGS_INIT)
    assert done.returncode == 0, done.stderr


def sends(number):
    subject = event("session-note", {"session": "eeeeeeee-0000-4000-8000-000000000000", "text": "n"}, "probe", times.stamp(times.now()))
    ledger = Ledger()
    for _ in range(number):
        ledger.append("send-confirmed", {"draft_seq": subject, "sent_at": times.stamp(times.now())}, "board")


def test_daniels_complaints_and_spam_flags_are_recorded_as_board_and_counted(company, daniels_settings):
    complaint(company)
    event_of = events("complaint")[0]
    assert (event_of["writer"], event_of["source"], event_of["bet"]) == ("board", "inbox", "alpha")

    assert honesty_section(company) == "Complaints: 1 in the last seven days"


def test_below_the_threshold_a_new_outside_action_goes_ahead(company, daniels_settings):
    done = complaint(company)

    assert "1" in done.stdout
    assert events("cell-paused") == []
    assert draft(company).returncode == 0


def test_at_the_threshold_new_outside_actions_are_refused_company_wide_until_daniel_reviews(company, daniels_settings):
    complaint(company)
    done = spam_flag(company)

    pause = events("cell-paused")[0]
    assert (pause["writer"], pause["scope"]) == ("treasurer", "outside-actions")
    assert pause["cause_seq"] == events("spam-flag")[0]["seq"]
    assert "company cell resume --outside-actions" in done.stdout
    refused = draft(company)
    assert refused.returncode == 1
    assert "outside-actions-paused" in refused.stderr
    assert events("draft-proposed") == []
    last = events("append-refused")[-1]
    assert (last["attempted_kind"], last["attempted_writer"], last["reason"]) == ("draft-proposed", "cell:alpha", "outside-actions-paused")
    assert "Paused now: all outside actions" in honesty_section(company)

    assert company("cell", "resume", "--outside-actions", "--message", "1234").returncode == 0

    resumed = events("cell-resumed")[0]
    assert (resumed["writer"], resumed["scope"], resumed["message"]) == ("board", "outside-actions", "1234")
    assert draft(company).returncode == 0


@pytest.mark.parametrize(
    ("kind", "fields", "writer"),
    [
        ("target-proposed", {"contact": "c", "organization": "o", "reason": "r", "source": "s"}, "cell:alpha"),
        ("draft-proposed", {"target_seq": 1, "body": "b", "claims": [], "disclosure": "d", "unsubscribe": "u"}, "cell:alpha"),
        (
            "experiment-registered",
            {"experiment": "e", "hypothesis": "h", "metric": "m", "keep_threshold": 1, "kill_threshold": 0, "budget_tokens": 1, "budget_dollars": 0, "budget_minutes": 1, "end_date": "2099-01-01"},
            "cell:alpha",
        ),
    ],
)
def test_the_hold_reaches_every_way_a_cell_starts_an_outside_action(company, daniels_settings, kind, fields, writer):
    from company.ledger import AppendRefused

    complaint(company)
    Ledger().append(kind, fields, writer)
    spam_flag(company)

    with pytest.raises(AppendRefused, match="outside-actions-paused"):
        Ledger().append(kind, fields, writer)

    assert len(events(kind)) == 1


def test_a_daniels_record_of_a_send_already_made_is_not_refused(company, daniels_settings):
    # A fact stays a fact: the hold stops what the company starts, and never what Daniel says happened.
    complaint(company)
    spam_flag(company)

    sends(1)

    assert len(events("send-confirmed")) == 1


def test_a_cells_own_pause_holds_no_outside_action_of_the_company(company, daniels_settings):
    seq = promise()
    assert company("treasurer", "check").returncode == 0
    assert checked_results() == [(seq, "broken")]

    assert draft(company).returncode == 0


def test_two_percent_of_the_outside_actions_counts_when_it_is_the_higher(company, daniels_settings):
    # 150 sends in the month: 2% is 3, which is above the count of 2, so two flags do not reach it and a third does.
    sends(150)
    complaint(company)
    complaint(company)
    assert events("cell-paused") == []

    complaint(company)

    assert len(events("cell-paused")) == 1


def test_the_count_stands_when_two_percent_of_the_outside_actions_is_lower(company, daniels_settings):
    # 10 sends: 2% is 0.2, so the count of 2 is what must be reached.
    sends(10)
    complaint(company)
    assert events("cell-paused") == []
    complaint(company)
    assert len(events("cell-paused")) == 1


def test_a_flag_outside_the_trailing_days_does_not_count(company, daniels_settings):
    old = times.stamp(times.now() - timedelta(days=31))
    event("complaint", {"source": "inbox", "summary": "s"}, "board", old)

    complaint(company)

    assert events("cell-paused") == []


def test_a_flag_inside_the_trailing_days_counts(company, daniels_settings):
    recent = times.stamp(times.now() - timedelta(days=29))
    event("complaint", {"source": "inbox", "summary": "s"}, "board", recent)

    complaint(company)

    assert len(events("cell-paused")) == 1


def test_the_threshold_is_read_from_daniels_settings(company, daniels_settings):
    assert company("settings", "set", "complaint_threshold", '{"count": 3, "days": 30, "outside_action_fraction": 0.02}').returncode == 0
    complaint(company)
    complaint(company)
    assert events("cell-paused") == []

    complaint(company)

    assert len(events("cell-paused")) == 1


def test_a_review_counts_only_what_comes_after_it(company, daniels_settings, check):
    complaint(company)
    complaint(company)
    assert company("cell", "resume", "--outside-actions").returncode == 0

    # The two already reviewed are still in the month, and do not pause it again.
    check()
    assert len(events("cell-paused")) == 1
    complaint(company)
    assert len(events("cell-paused")) == 1
    assert draft(company).returncode == 0

    complaint(company)
    assert len(events("cell-paused")) == 2


def test_resuming_a_cell_is_no_review_of_the_complaints(company, daniels_settings):
    seq = promise()
    assert company("treasurer", "check").returncode == 0
    assert checked_results() == [(seq, "broken")]
    complaint(company)
    assert company("cell", "resume", "--bet", "alpha").returncode == 0

    complaint(company)

    assert [found["scope"] for found in events("cell-paused")] == ["cell", "outside-actions"]


def test_a_hold_outlasting_its_flags_is_still_said_to_stand(company, daniels_settings, check):
    # Each flag has aged out of the month, and only Daniel's review lifts the hold.
    aged = event("complaint", {"source": "inbox", "summary": "s"}, "board", times.stamp(times.now() - timedelta(days=40)))
    event("cell-paused", {"scope": "outside-actions", "reason": "r", "cause_seq": aged}, "treasurer")

    assert "company cell resume --outside-actions" in check().stdout

    done = complaint(company)
    assert "company cell resume --outside-actions" in done.stdout
    assert draft(company).returncode == 1


def test_a_flag_past_the_threshold_with_the_hold_on_writes_no_second_pause(company, daniels_settings):
    complaint(company)
    complaint(company)

    done = complaint(company)

    assert len(events("cell-paused")) == 1
    assert "company cell resume --outside-actions" in done.stdout


def test_the_check_pauses_for_flags_no_command_paused_for(company, daniels_settings, check):
    # A record the command could not act on, say with the settings mended since.
    event("complaint", {"source": "inbox", "summary": "s"}, "board", times.stamp(times.now()))
    event("spam-flag", {"source": "inbox"}, "board", times.stamp(times.now()))
    assert events("cell-paused") == []

    check()
    check()

    assert [found["scope"] for found in events("cell-paused")] == ["outside-actions"]


def test_a_complaint_with_no_settings_is_still_recorded_and_says_it_was_not_weighed(company):
    done = company("complaint", "record", "--source", "inbox", "--summary", "s")

    assert done.returncode == 1
    assert len(events("complaint")) == 1
    assert "threshold" in done.stderr
    assert events("cell-paused") == []


def test_a_check_with_a_flag_and_no_settings_checks_its_promises_and_says_why_it_stopped_there(company):
    seq = promise()
    event("complaint", {"source": "inbox", "summary": "s"}, "board")

    done = company("treasurer", "check")

    assert done.returncode == 1
    assert "threshold" in done.stderr
    assert checked_results() == [(seq, "broken")]


def test_a_threshold_that_cannot_hold_is_refused_by_the_settings(company, daniels_settings):
    for bad in ('{"count": 0, "days": 30, "outside_action_fraction": 0.02}', '{"count": 2, "days": 0, "outside_action_fraction": 0.02}', '{"count": 2, "days": 1e12, "outside_action_fraction": 0.02}'):
        assert company("settings", "set", "complaint_threshold", bad).returncode == 1


# A cell's tool


def test_a_cell_records_a_promise_through_its_tool_under_its_own_name(company):
    tools = CellTools(bet="alpha")
    try:
        answer = tools.call("record_promise", {"promise": "a delivery", "due_date": "2099-01-01", "counterparty": "a buyer", "bet": "beta", "writer": "board"})
    finally:
        tools.close()

    assert not answer["isError"], answer
    recorded = events("promise-recorded")[0]
    assert (recorded["writer"], recorded["promise"], recorded["due_date"], recorded["counterparty"]) == ("cell:alpha", "a delivery", "2099-01-01", "a buyer")
    assert "bet" not in recorded
    assert str(recorded["seq"]) in text_of(answer)


@pytest.mark.parametrize(
    "arguments",
    [
        {"due_date": "2099-01-01"},
        {"promise": "", "due_date": "2099-01-01"},
        {"promise": "a delivery"},
        {"promise": "a delivery", "due_date": "next week"},
        {"promise": "a delivery", "due_date": "2020-01-01"},
        {"promise": "a delivery", "due_date": "2026-1-1"},
        {"promise": "a delivery", "due_date": ""},
        {"promise": "a delivery", "due_date": "2099-01-01", "counterparty": 7},
        {"promise": 7, "due_date": "2099-01-01"},
    ],
)
def test_a_promise_that_cannot_be_checked_is_refused_and_logged(company, arguments):
    tools = CellTools()
    try:
        answer = tools.call("record_promise", arguments)
    finally:
        tools.close()

    assert answer["isError"]
    assert events("promise-recorded") == []
    assert events("append-refused")[-1]["attempted_kind"] == "promise-recorded"


def test_a_promise_dated_in_the_past_is_told_so(company):
    tools = CellTools()
    try:
        answer = tools.call("record_promise", {"promise": "a delivery", "due_date": "2020-01-01"})
    finally:
        tools.close()

    assert answer["isError"]
    assert "due-date-past" in text_of(answer)
    assert events("append-refused")[-1]["reason"] == "due-date-past"


@pytest.mark.parametrize("day", ["2026-1-1", ""])
def test_a_due_date_that_is_no_date_is_not_called_past(company, day):
    tools = CellTools()
    try:
        tools.call("record_promise", {"promise": "a delivery", "due_date": day})
    finally:
        tools.close()

    assert events("append-refused")[-1]["reason"] == "bad-arguments"


def test_no_tool_of_a_cells_says_a_promise_was_kept():
    from company import tools

    assert "record_promise" in tools.ROLE_TOOLS["cell"]
    assert "record_promise" not in tools.ROLE_TOOLS["probe"]
    assert not any("kept" in name or "keep" in name for names in tools.ROLE_TOOLS.values() for name in names)


def test_a_cell_cannot_write_that_its_own_promise_was_kept(company):
    done = company("ledger", "append", "promise-kept", "--writer", "cell:alpha", "--fields", '{"promise_seq": 1, "kept_date": "2026-10-01"}')

    assert done.returncode == 1
    assert events("promise-kept") == []
