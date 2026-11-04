"""The ledger, through the `company` command as a person runs it."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SESSION = "11111111-2222-4333-8444-555555555555"
NOTE = {"session": SESSION, "text": "hello"}
SECRET = "rejected-value-that-must-never-be-logged"


@pytest.fixture
def ledger_file(company_home):
    return company_home / "ledger.jsonl"


@pytest.fixture
def append(company):
    def run(kind, writer, fields):
        return company("ledger", "append", kind, "--writer", writer, "--fields", json.dumps(fields))

    return run


@pytest.fixture
def notes(append):
    """Write a number of good events to the ledger."""

    def write(count=5):
        for number in range(count):
            result = append("session-note", "probe", {**NOTE, "text": f"note {number}"})
            assert result.returncode == 0, result.stderr

    return write


def events(ledger_file):
    return [json.loads(line) for line in ledger_file.read_text().splitlines()]


def test_an_allowed_writer_appends_and_sees_the_event(append, company, ledger_file):
    result = append("session-note", "probe", NOTE)

    assert result.returncode == 0, result.stderr
    printed = json.loads(result.stdout)
    assert printed["kind"] == "session-note"
    assert printed["writer"] == "probe"
    assert printed["seq"] == 1
    assert printed["prev"] is None
    assert printed["text"] == "hello"
    assert printed["ts"].endswith("Z")
    assert events(ledger_file) == [printed]

    shown = company("ledger", "show")
    assert shown.returncode == 0
    assert [json.loads(line) for line in shown.stdout.splitlines()] == [printed]


def test_each_event_chains_from_the_one_before(append, ledger_file):
    append("session-note", "probe", NOTE)
    append("session-note", "probe", NOTE)
    first, second = ledger_file.read_text().splitlines()
    assert json.loads(second)["seq"] == 2
    assert json.loads(second)["prev"] != json.loads(first)["prev"]
    assert len(json.loads(second)["prev"]) == 64


def test_a_disallowed_writer_is_refused_and_logged(append, company, ledger_file):
    result = append("revenue", "cell:quant", {"amount": "5.00", "currency": "USD", "source": SECRET, "record": "r"})

    assert result.returncode == 1
    assert "revenue" in result.stderr
    assert "cell:quant" in result.stderr
    assert "writer-not-allowed" in result.stderr
    assert "Nothing was appended" in result.stderr
    assert "event 1" in result.stderr
    [refusal] = events(ledger_file)
    assert refusal["kind"] == "append-refused"
    assert refusal["attempted_kind"] == "revenue"
    assert refusal["attempted_writer"] == "cell:quant"
    assert refusal["reason"] == "writer-not-allowed"
    assert refusal["writer"] == "treasurer"
    assert SECRET not in ledger_file.read_text()
    assert SECRET not in result.stdout + result.stderr
    assert company("ledger", "verify").returncode == 0


REVENUE = {"amount": "5.00", "currency": "USD", "source": "broker", "record": "r1"}


@pytest.mark.parametrize(
    ("kind", "writer", "fields", "reason"),
    [
        ("session-note", "probe", {"session": SESSION}, "missing-fields:text"),
        ("session-note", "probe", {**NOTE, "extra": SECRET}, "unknown-fields"),
        ("session-note", "probe", {**NOTE, SECRET: 1}, "unknown-fields"),
        ("session-note", "probe", {**NOTE, "seq": 99}, "unknown-fields"),
        ("session-note", "probe", {**NOTE, "prev": SECRET}, "unknown-fields"),
        ("session-note", "probe", {**NOTE, "writer": "treasurer"}, "unknown-fields"),
        ("session-note", "probe", {**NOTE, "kind": "revenue"}, "unknown-fields"),
        ("session-note", "probe", {"session": SECRET, "text": "x"}, "bad-field:session"),
        ("session-note", "probe", [SECRET], "not-an-object"),
        ("no-such-kind", "probe", {"text": SECRET}, "unknown-kind"),
        ("session-note", "nobody", {**NOTE, "text": SECRET}, "unknown-writer"),
        ("session-note", "cell:Not A Bet", {**NOTE, "text": SECRET}, "unknown-writer"),
        ("session-note", "strategy", {**NOTE, "text": SECRET}, "writer-not-allowed"),
        ("revenue", "treasurer", {**REVENUE, "amount": SECRET}, "bad-field:amount"),
        ("revenue", "treasurer", {**REVENUE, "amount": 5}, "bad-field:amount"),
        ("revenue", "treasurer", {**REVENUE, "bet": "Bad Bet!"}, "bad-field:bet"),
        (
            "go-given",
            "board",
            {"scope": "real-sessions", "message": SECRET, "sessions": 1},
            "bad-field:message",
        ),
        (
            "promise-recorded",
            "runner",
            {"promise": "p", "due_date": "next week"},
            "bad-field:due_date",
        ),
        (
            "usage-reading",
            "board",
            {
                "window": "seven_day",
                "used_percent": 1,
                "resets_at": "2026-11-05",
                "taken_at": "2026-11-05T00:00:00Z",
                "source": "hand",
            },
            "bad-field:resets_at",
        ),
        ("cell-paused", "treasurer", {"scope": "cell", "reason": "r", "cause_seq": 1}, "bad-field:cause_seq"),
        ("cell-paused", "treasurer", {"scope": "cell", "reason": "r", "cause_seq": True}, "bad-field:cause_seq"),
        ("promise-checked", "treasurer", {"promise_seq": "1", "result": "kept"}, "bad-field:promise_seq"),
        (
            "promise-checked",
            "treasurer",
            {"promise_seq": 1, "result": "kept", "evidence_seqs": [1]},
            "bad-field:promise_seq",
        ),
        (
            "session-ended",
            "launcher",
            {"session": SESSION, "exit": 0, "transcript_path": "p", "transcript_hash": "h", "weight": "lots"},
            "bad-field:weight",
        ),
        ("minutes-corrected", "board", {"minutes": -1, "charge_seq": 1}, "bad-field:minutes"),
        ("minutes-corrected", "board", {"minutes": "half", "charge_seq": 1}, "bad-field:minutes"),
        (
            "resource-charged",
            "treasurer",
            {
                "week_start": "2026-10-11T00:00:00Z",
                "line": "overhead",
                "weight": 1,
                "fraction": 0.1,
                "company_used": 1,
                "cost": 3.6,
                "reading_seq": 1,
            },
            "bad-field:cost",
        ),
        (
            "resource-charged",
            "treasurer",
            {
                "week_start": "2026-10-11",
                "line": "overhead",
                "weight": 1,
                "fraction": 0.1,
                "company_used": 1,
                "cost": "3.60",
                "reading_seq": 1,
            },
            "bad-field:week_start",
        ),
    ],
)
def test_a_wrong_event_is_refused_and_logged_without_its_values(append, ledger_file, kind, writer, fields, reason):
    result = append(kind, writer, fields)

    assert result.returncode == 1
    assert reason in result.stderr
    assert "Nothing was appended" in result.stderr
    [refusal] = events(ledger_file)
    assert refusal["kind"] == "append-refused"
    assert refusal["reason"] == reason
    assert SECRET not in ledger_file.read_text()
    assert SECRET not in result.stderr


def test_a_label_that_is_no_name_is_not_copied_into_the_ledger(append, ledger_file):
    result = append(f"{SECRET} {SECRET.upper()}", f"Writer {SECRET}", {})

    assert result.returncode == 1
    [refusal] = events(ledger_file)
    assert refusal["attempted_kind"] == "<not-a-name>"
    assert refusal["attempted_writer"] == "<not-a-name>"
    assert SECRET not in ledger_file.read_text()
    assert SECRET not in result.stderr


def test_a_refused_code_writer_logs_its_own_refusal(append, ledger_file):
    append("config-run", "runner", {"registration_seq": 1})

    [refusal] = events(ledger_file)
    assert refusal["writer"] == "runner"
    assert refusal["attempted_writer"] == "runner"


@pytest.mark.parametrize("writer", ["board", "cell:quant", "strategy", "auditor", "retro", "probe", "nobody"])
def test_a_refused_agent_or_person_is_logged_by_the_treasurer(append, ledger_file, writer):
    append("revenue", writer, {})

    [refusal] = events(ledger_file)
    assert refusal["writer"] == "treasurer"


def test_a_field_ending_in_seq_may_cite_an_earlier_event(append, ledger_file):
    append("promise-recorded", "runner", {"promise": "p", "due_date": "2026-12-01", "bet": "quant"})
    result = append("promise-checked", "treasurer", {"promise_seq": 1, "result": "kept", "evidence_seqs": [1]})

    assert result.returncode == 0, result.stderr


def test_a_cell_writes_under_its_own_bet_id(append):
    assert append("session-note", "cell:quant-1", NOTE).returncode == 0


def test_a_field_that_is_not_json_is_a_usage_error_and_appends_nothing(company, ledger_file):
    result = company("ledger", "append", "session-note", "--writer", "probe", "--fields", "{not json")

    assert result.returncode == 2
    assert "Nothing was appended" in result.stderr
    assert not ledger_file.exists()


def test_verify_passes_on_a_good_ledger_and_on_none(company, notes):
    empty = company("ledger", "verify")
    assert empty.returncode == 0
    assert "0 events" in empty.stdout

    notes(5)
    good = company("ledger", "verify")
    assert good.returncode == 0
    assert "5 events" in good.stdout


def rewrite(path, change):
    lines = path.read_text().splitlines(keepends=True)
    path.write_text("".join(change(lines)))


def edit_field(index, field="text", value=SECRET):
    def change(lines):
        event = json.loads(lines[index])
        event[field] = value
        lines[index] = json.dumps(event, separators=(",", ":")) + "\n"
        return lines

    return change


def respace(index):
    def change(lines):
        lines[index] = lines[index].replace(",", ", ", 1)
        return lines

    return change


def remove(index):
    def change(lines):
        del lines[index]
        return lines

    return change


def swap(first, second):
    def change(lines):
        lines[first], lines[second] = lines[second], lines[first]
        return lines

    return change


def insert_copy(index):
    def change(lines):
        lines.insert(index, lines[index])
        return lines

    return change


def cut_short(lines):
    lines[-1] = lines[-1][:10]
    return lines


def add_garbage(lines):
    return [*lines[:2], "not json\n", *lines[2:]]


TAMPERS = {
    "edit the first line": edit_field(0),
    "edit a middle line": edit_field(2),
    "edit the last line": edit_field(-1),
    "edit only the spacing": respace(1),
    "edit a line's seq": edit_field(2, "seq", 9),
    "remove the first line": remove(0),
    "remove a middle line": remove(2),
    "remove the last line": remove(-1),
    "remove the last two lines": lambda lines: lines[:-2],
    "remove every line": lambda lines: [],
    "reorder two lines": swap(1, 2),
    "reorder the last two lines": swap(-1, -2),
    "repeat a line": insert_copy(2),
    "cut the last line short": cut_short,
    "add a line that is no event": add_garbage,
}


@pytest.mark.parametrize("tamper", TAMPERS)
def test_a_changed_past_is_found_by_verify(company, notes, ledger_file, tamper):
    notes(5)
    rewrite(ledger_file, TAMPERS[tamper])

    result = company("ledger", "verify")

    assert result.returncode == 1
    assert "BROKEN" in result.stdout
    assert SECRET not in result.stdout


def test_verify_names_the_line_where_the_chain_breaks(company, notes, ledger_file):
    notes(5)
    rewrite(ledger_file, edit_field(2))

    result = company("ledger", "verify")

    assert "line 4" in result.stdout
    assert "line 3" in result.stdout


def test_deleting_the_ledger_is_found(company, notes, ledger_file):
    notes(2)
    ledger_file.unlink()

    assert company("ledger", "verify").returncode == 1


def test_deleting_the_head_record_is_found(company, notes, company_home):
    notes(2)
    (company_home / "ledger.head").unlink()

    assert company("ledger", "verify").returncode == 1


def test_a_cut_at_the_end_cannot_be_healed_by_a_later_append(append, company, notes, ledger_file):
    notes(3)
    rewrite(ledger_file, remove(-1))

    result = append("session-note", "probe", NOTE)

    assert result.returncode == 1
    assert "Nothing was appended" in result.stderr
    assert len(events(ledger_file)) == 2
    assert company("ledger", "verify").returncode == 1


def test_a_torn_last_line_refuses_the_next_append(append, company, notes, ledger_file):
    notes(3)
    rewrite(ledger_file, cut_short)

    result = append("session-note", "probe", NOTE)

    assert result.returncode == 1
    assert "Nothing was appended" in result.stderr
    assert company("ledger", "verify").returncode == 1


def test_a_crash_between_the_line_and_its_head_record_is_no_break(append, company, notes, company_home):
    notes(3)
    head = company_home / "ledger.head"
    before = head.read_text()
    notes(1)
    head.write_text(before)

    assert company("ledger", "verify").returncode == 0
    assert append("session-note", "probe", NOTE).returncode == 0
    assert company("ledger", "verify").returncode == 0


def test_a_head_record_more_than_one_line_behind_is_found(company, notes, company_home):
    notes(3)
    head = company_home / "ledger.head"
    before = head.read_text()
    notes(2)
    head.write_text(before)

    assert company("ledger", "verify").returncode == 1


def test_show_warns_when_the_chain_is_broken(company, notes, ledger_file):
    notes(3)
    rewrite(ledger_file, edit_field(0))

    result = company("ledger", "show")

    assert result.returncode == 1
    assert "BROKEN" in result.stderr


def test_concurrent_appenders_produce_an_unbroken_chain(company, ledger_file):
    script = Path(sys.executable).parent / "company"
    fields = json.dumps(NOTE)
    good = [script, "ledger", "append", "session-note", "--writer", "probe", "--fields", fields]
    bad = [script, "ledger", "append", "revenue", "--writer", "probe", "--fields", "{}"]
    commands = [good if number % 4 else bad for number in range(48)]

    running = [subprocess.Popen(c, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for c in commands]
    for process in running:
        process.wait(timeout=120)

    assert company("ledger", "verify").returncode == 0
    written = events(ledger_file)
    assert [event["seq"] for event in written] == list(range(1, len(commands) + 1))
    assert sum(event["kind"] == "append-refused" for event in written) == 12


def test_the_ledger_is_readable_only_by_its_owner(notes, ledger_file):
    notes(1)
    assert ledger_file.stat().st_mode & 0o077 == 0


def test_the_ledger_api_matches_the_command(company_home):
    from company.ledger import AppendRefused, Ledger

    ledger = Ledger()
    event = ledger.append("session-note", NOTE, "probe")
    assert ledger.read() == [event]

    with pytest.raises(AppendRefused) as refused:
        ledger.append("revenue", {}, "probe")
    assert refused.value.reason == "writer-not-allowed"
    assert refused.value.refusal_seq == 2
    assert [item["kind"] for item in ledger.read()] == ["session-note", "append-refused"]
    assert ledger.verify().ok


def test_a_value_json_cannot_hold_is_refused(company_home):
    from company.ledger import AppendRefused, Ledger

    ledger = Ledger()
    with pytest.raises(AppendRefused) as refused:
        ledger.append("session-note", {**NOTE, "text": float("nan")}, "probe")
    assert refused.value.reason == "not-json"
    with pytest.raises(AppendRefused):
        ledger.append("session-note", {**NOTE, "text": object()}, "probe")
    assert ledger.verify().ok
