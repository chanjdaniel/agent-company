"""The Auditor, on a recorded session: `company audit` runs the stub through the real company tools, on a planted transcript.

A cell's run is played first, then the Auditor's script. A reply of a few tokens weighs next to nothing, so no limit is near.
"""

import hashlib
import json
import os
import shlex
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from session_checks import events, patch_every_company, run_file_fails, wait_for
from usage_records import SETTINGS_INIT, TEAM, transcript_line, week_reading

from company import audit, goals, paths, schedule, times, tools, views
from company.ledger import AppendRefused, Ledger

REPORTED = "The backtest returned a Sharpe of 2.40 over the period."
MARKER = "PLANTED-FINDING-TEXT"
COMPANY = str(Path(sys.executable).parent / "company")


@pytest.fixture(autouse=True)
def team_has_used_the_account(transcripts):
    """The team's reply dwarfs every session here, so that the company stays far under its share across them."""
    earlier = times.now() - timedelta(minutes=5)
    transcripts.session(TEAM, transcript_line(TEAM, "team-1", earlier.strftime("%Y-%m-%dT%H:%M:%S.000Z"), output=50_000_000))


@pytest.fixture
def cell_run(company, stub, board):
    """Run a cell's session, which says `said`, and return its `session-started`."""

    def run(*steps, said=REPORTED, bet="alpha"):
        stub.play({"do": "reply", "request": "r1", "output": 10, "text": said}, *steps)
        done = company("session", "start", "cell", "--bet", bet)
        assert done.returncode == 0, done.stdout + done.stderr
        return events("session-started")[-1]

    return run


@pytest.fixture
def audited(company, stub, cell_run):
    """Run a cell's session, then audit it with this script; returns the finished command and the cell's start."""

    def run(*steps, said=REPORTED, bet="alpha"):
        cell = cell_run(said=said, bet=bet)
        stub.play(*steps)
        return company("audit", cell["run"]), cell

    return run


def company_step(*arguments):
    """The stub runs `company` as an agent's shell would, in this test's home; a session's environment does not carry it."""
    return {"do": "run", "command": [COMPANY, *arguments], "env": {"COMPANY_HOME": os.environ["COMPANY_HOME"]}}


def finding_step(session, **more):
    arguments = {"rubric": "false-statement", "summary": f"{MARKER} summary", "evidence": "the transcript's second reply", "audited_session": session, **more}
    return {"do": "tool", "name": "record_finding", "arguments": arguments}


def audit_with_finding(company, stub, cell, **more):
    """Audit this cell's run with one finding on it."""
    stub.play(finding_step(cell["session"], **more))
    done = company("audit", cell["run"])
    assert done.returncode == 0, done.stdout + done.stderr
    return done


def claim_step(session, quote=REPORTED, value=2.40):
    return finding_step(session, rubric=audit.UNSHOWN_RESULT, claim={"quote": quote, "value": value})


def assert_cell_may_start(company, bet="alpha"):
    done = company("governor", "check", "cell", "--bet", bet)
    assert done.returncode == 0, done.stdout


def assert_cell_refused(company, bet="alpha"):
    done = company("governor", "check", "cell", "--bet", bet)
    assert done.returncode == 1
    assert "paused" in done.stdout


def registration(bet="alpha"):
    fields = {
        "strategy": "s",
        "universe": ["SPY"],
        "data_source": "fixture:daily",
        "data_hash": "h",
        "in_sample": {"start": "2026-01-05", "end": "2026-01-09"},
        "holdout": {"start": "2026-01-12", "end": "2026-01-16"},
        "cost_model": {"bps_per_turnover": 1},
        "slippage_model": {"bps_per_turnover": 1},
        "max_configurations": 5,
        "acceptance": {"min_deflated_sharpe": 0.5, "min_holdout_return": 0, "max_drawdown": 0.2},
    }
    return Ledger().append("strategy-registered", fields, f"cell:{bet}")["seq"]


def config_run(registration_seq, **figures):
    fields = {"registration_seq": registration_seq, "config_hash": "c", "status": "ok", "budget_used": 1, **figures}
    return Ledger().append("config-run", fields, "runner")["seq"]


# The session it starts


def test_an_audit_starts_on_the_auditors_model_in_a_fresh_workspace_with_the_ledger_and_the_transcript(audited, stub):
    seen = {"do": "run", "command": ["/bin/sh", "-c", "cat ledger.jsonl; echo ---; ls transcripts; echo ---; cat transcripts/*"]}

    done, cell = audited(seen)

    assert done.returncode == 0, done.stdout + done.stderr
    assert stub.argument("--model") == "claude-sonnet-5-5"
    call = stub.session_calls()[-1]
    workspace = Path(call["cwd"])
    assert workspace.parent == paths.workspaces().resolve()
    started = events("session-started")[-1]
    assert started["role"] == "auditor"
    assert started["audited_runs"] == [cell["run"]]
    assert workspace.name == started["run"]
    assert "bet" not in started
    listed = stub.runs()[-1]["stdout"]
    ledger_copy, names, transcript = listed.split("---\n")
    assert json.loads(ledger_copy.splitlines()[-1])["seq"] == started["seq"] - 1
    assert names.strip() == f"{cell['run']}.jsonl"
    kept = paths.runs() / cell["run"] / "transcript.jsonl"
    assert transcript == kept.read_text()
    assert REPORTED in kept.read_text()


def test_the_prompt_holds_the_goal_and_names_what_was_audited(audited, stub):
    _, cell = audited()

    prompt = stub.session_calls()[-1]["stdin"]
    assert goals.load("auditor").text in prompt
    assert cell["session"] in prompt
    assert f"transcripts/{cell['run']}.jsonl" in prompt
    assert "ledger.jsonl" in prompt
    assert "alpha" in prompt


def test_an_audit_uses_a_word_and_is_refused_with_none_left(company, stub):
    assert company(*SETTINGS_INIT).returncode == 0
    assert company("go", "real-sessions", "--message", "1234", "--sessions", "1").returncode == 0
    week_reading()
    stub.play({"do": "reply", "request": "r1", "output": 10})
    assert company("session", "start", "cell", "--bet", "alpha").returncode == 0
    used = len(stub.session_calls())

    done = company("audit", events("session-started")[-1]["run"])

    assert done.returncode == 1
    assert "go-used-up" in done.stdout
    assert len(stub.session_calls()) == used


def test_the_command_takes_one_of_a_run_the_sample_or_the_full_pass(company, board):
    assert company("audit").returncode == 2
    assert company("audit", "run", "--sample").returncode == 2
    assert company("audit", "--sample", "--full").returncode == 2


def test_an_audit_inside_a_session_is_refused_and_logged(company, stub, board):
    stub.play(company_step("audit", "--full"))
    done = company("session", "start", "probe")

    assert done.returncode == 0
    assert stub.runs()[-1]["exit"] == 1
    assert events("append-refused")[-1]["reason"] == "inside-a-session"


# On a different model


def test_the_same_model_as_the_cells_setting_is_refused_citing_the_recorded_gap(company, stub, cell_run, repo):
    cell = cell_run()
    assert company("settings", "set", "auditor_model", "claude-opus-5-5").returncode == 0
    before = len(stub.session_calls())

    done = company("audit", cell["run"])

    assert done.returncode == 1
    assert "same-model" in done.stdout
    assert audit.RECORDED_GAP in done.stdout
    assert f"### {audit.RECORDED_GAP}" in (repo / "docs/design.md").read_text()
    assert len(stub.session_calls()) == before
    refused = events("launch-refused")[-1]
    assert refused["check"] == "model"
    assert audit.RECORDED_GAP in refused["reason"]
    assert "auditor_model" in refused["fix"]


def test_the_model_the_audited_session_ran_on_counts_even_if_the_setting_moved(company, stub, cell_run):
    cell = cell_run()
    assert company("settings", "set", "cell_model", "claude-haiku-5-5").returncode == 0
    assert company("settings", "set", "auditor_model", cell["model"]).returncode == 0
    before = len(stub.session_calls())

    done = company("audit", cell["run"])

    assert done.returncode == 1
    assert audit.RECORDED_GAP in done.stdout
    assert len(stub.session_calls()) == before


@pytest.mark.parametrize("name", ["claude-opus-5-5[1m]", "opus", "opus[1m]", "CLAUDE-OPUS-5-5", "claude-opus-4-8"])
def test_another_name_for_the_cells_model_or_its_family_is_the_same_model(company, stub, cell_run, name):
    cell = cell_run()
    assert company("settings", "set", "auditor_model", name).returncode == 0
    before = len(stub.session_calls())

    done = company("audit", cell["run"])

    assert done.returncode == 1
    assert audit.RECORDED_GAP in done.stdout
    assert len(stub.session_calls()) == before


def test_an_auditor_session_started_by_hand_is_refused_on_the_cells_model_too(company, stub, board):
    assert company("settings", "set", "auditor_model", "claude-opus-5-5").returncode == 0

    done = company("session", "start", "auditor")

    assert done.returncode == 1
    assert audit.RECORDED_GAP in done.stdout
    assert stub.session_calls() == []


# What cannot be audited


def test_a_run_the_ledger_does_not_name_is_refused(company, stub, board):
    done = company("audit", "../../etc")

    assert done.returncode == 1
    assert "no-such-run" in done.stdout
    assert stub.session_calls() == []
    assert events("launch-refused")[-1]["check"] == "audit"


def test_a_session_with_no_transcript_is_refused(company, stub, board):
    stub.play()
    assert company("session", "start", "cell", "--bet", "alpha").returncode == 0
    run = events("session-started")[-1]["run"]

    done = company("audit", run)

    assert done.returncode == 1
    assert "no-transcript" in done.stdout


def test_a_session_still_running_is_refused(company, stub, board):
    started = {"session": "bbbbbbbb-0000-4000-8000-000000000000", "role": "cell", "bet": "alpha", "model": "claude-opus-5-5", "run": "open-run", "gate": "go:1", "account_used": 0, "company_used": 0, "reading_seq": 1}
    Ledger().append("session-started", started, "launcher")
    subjects = list(Ledger().read())

    with pytest.raises(audit.NotAuditable) as refused:
        audit.subjects(subjects, ("open-run",))

    assert refused.value.reason == "not-ended"


def test_a_transcript_that_no_longer_matches_its_hash_is_refused(company, stub, cell_run):
    cell = cell_run()
    (paths.runs() / cell["run"] / "transcript.jsonl").write_text("changed\n")
    before = len(stub.session_calls())

    done = company("audit", cell["run"])

    assert done.returncode == 1
    assert "transcript-changed" in done.stdout
    assert len(stub.session_calls()) == before


# Its findings reach Daniel and the ledger


def test_a_finding_goes_to_the_ledger_and_the_digest(company, stub, cell_run):
    cell = cell_run()

    audit_with_finding(company, stub, cell)

    finding = events("finding")[-1]
    assert finding["writer"] == "auditor"
    assert finding["bet"] == "alpha"
    assert finding["session"] == cell["session"]
    assert finding["rubric"] == "false-statement"
    page = company("digest").stdout
    assert f"{MARKER} summary" in page
    assert f"company finding confirm {finding['seq']}" in page


def test_a_tools_arguments_choose_no_writer_and_no_bet(company, stub, cell_run):
    cell = cell_run()

    audit_with_finding(company, stub, cell, writer="board", bet="beta", kind="finding-confirmed")

    finding = events("finding")[-1]
    assert finding["writer"] == "auditor"
    assert finding["bet"] == "alpha"
    assert finding["session"] == cell["session"]
    assert events("finding-confirmed") == []


def test_a_finding_on_a_session_it_was_not_given_is_refused_and_logged(company, stub, cell_run):
    cell = cell_run()
    stub.play(finding_step("aaaaaaaa-0000-4000-8000-000000000000"))

    assert company("audit", cell["run"]).returncode == 0

    assert events("finding") == []
    assert stub.tool_results()[-1]["result"]["isError"] is True
    assert events("append-refused")[-1]["reason"] == "not-audited"


@pytest.mark.parametrize(
    "more",
    [
        {"rubric": "not-a-rubric"},
        {"summary": ""},
        {"evidence": 3},
        {"rubric": "false-statement", "claim": {"quote": "q", "value": 1}},
        {"rubric": audit.UNSHOWN_RESULT, "claim": {"quote": "", "value": 1}},
        {"rubric": audit.UNSHOWN_RESULT, "claim": {"quote": "q", "value": True}},
        {"rubric": audit.UNSHOWN_RESULT, "claim": {"quote": "q"}},
        {"rubric": audit.UNSHOWN_RESULT, "claim": "q"},
    ],
)
def test_a_finding_that_cannot_stand_is_refused(company, stub, cell_run, more):
    cell = cell_run()
    stub.play(finding_step(cell["session"], **more))

    assert company("audit", cell["run"]).returncode == 0

    assert events("finding") == []
    assert events("append-refused")[-1]["reason"] == "bad-arguments"


# No cell can write or read them


def test_no_cell_has_a_finding_tool_or_a_way_to_write_one(company, stub, cell_run):
    assert "record_finding" not in tools.ROLE_TOOLS["cell"]
    fields = json.dumps({"rubric": "false-statement", "summary": "s", "evidence": "e"})
    cell_run(
        {"do": "list-tools"},
        finding_step("aaaaaaaa-0000-4000-8000-000000000000"),
        company_step("ledger", "append", "finding", "--writer", "auditor", "--fields", fields),
        company_step("finding", "confirm", "1"),
    )

    assert "record_finding" not in [tool["name"] for tool in stub.tool_lists()[-1]["result"]["tools"]]
    assert stub.tool_results()[-1]["result"]["isError"] is True
    assert [run["exit"] for run in stub.runs()] == [1, 1]
    assert events("finding") == []
    assert events("finding-confirmed") == []
    assert "tool-not-in-role" in [event["reason"] for event in events("append-refused")]
    with pytest.raises(AppendRefused):
        Ledger().append("finding", {"rubric": "false-statement", "summary": "s", "evidence": "e"}, "cell:alpha")


@pytest.mark.parametrize("command", [("digest",), ("ledger", "show")])
def test_a_session_cannot_print_the_findings_through_the_company_command(company, stub, cell_run, command):
    cell = cell_run()
    audit_with_finding(company, stub, cell)

    cell_run(company_step(*command))

    run = stub.runs()[-1]
    assert run["exit"] == 1
    assert MARKER not in run["stdout"] + run["stderr"]
    assert events("append-refused")[-1]["reason"] == "inside-a-session"


def plant_every_honesty_event(company, stub, cell):
    audit_with_finding(company, stub, cell)
    seq = events("finding")[-1]["seq"]
    assert company("finding", "confirm", str(seq)).returncode == 0
    assert company("cell", "resume", "--bet", "alpha").returncode == 0


def test_a_cells_view_holds_its_own_records_and_no_finding(company, stub, cell_run):
    first = cell_run({"do": "tool", "name": "note", "arguments": {"text": "my own note"}})
    other = cell_run({"do": "tool", "name": "note", "arguments": {"text": "ANOTHER-BETS-NOTE"}}, bet="beta")
    Ledger().append("complaint", {"source": "inbox", "summary": "ABOUT-THE-BET", "bet": "alpha"}, "board")
    plant_every_honesty_event(company, stub, first)
    stub.play({"do": "run", "command": ["/bin/cat", "ledger.jsonl"]})

    assert company("session", "start", "cell", "--bet", "alpha").returncode == 0

    view = stub.runs()[-1]["stdout"]
    shown = [json.loads(line) for line in view.splitlines()]
    assert "my own note" in view
    assert first["session"] in view
    for hidden in (MARKER, "ANOTHER-BETS-NOTE", other["session"], "ABOUT-THE-BET"):
        assert hidden not in view
    assert not {"finding", "finding-confirmed", "cell-paused", "cell-resumed", "complaint"} & {event["kind"] for event in shown}
    assert {event["kind"] for event in shown} >= {"session-started", "session-ended", "session-note"}
    # The Auditor's own session is on no bet, so it is no part of the view.
    assert "auditor" not in [event.get("role") for event in shown]


def test_a_cells_view_shows_its_runs_verdict_paper_and_promises_and_not_anothers():
    made = []
    for bet in ("alpha", "beta"):
        registered = registration(bet)
        run = config_run(registered, sharpe=1.5)
        verdict = {"registration_seq": registered, "config_hash": "c", "passed": True, "failed_tests": [], "deflated_sharpe": 0.9, "holdout_return": 0.1, "max_drawdown": 0.1, "trials": 1, "config_run_seqs": [run], "holdout_hash": "h"}
        verdict_seq = Ledger().append("verdict", verdict, "treasurer")["seq"]
        period = Ledger().append("paper-opened", {"registration_seq": registered, "verdict_seq": verdict_seq, "end_date": "2027-01-01", "drawdown_kill": 0.2}, "runner")["seq"]
        reading = Ledger().append("paper-reading", {"period_seq": period, "equity": "1.00", "pnl": "0.00", "taken_at": "2026-11-05T00:00:00Z"}, "runner")["seq"]
        promise = Ledger().append("promise-recorded", {"promise": "p", "due_date": "2026-11-05"}, f"cell:{bet}")["seq"]
        finding = Ledger().append("finding", {"rubric": "broken-promise", "summary": "s", "evidence": "e", "bet": bet, "promise_seq": promise}, "treasurer")["seq"]
        checked = Ledger().append("promise-checked", {"promise_seq": promise, "result": "broken", "evidence_seqs": [finding]}, "treasurer")["seq"]
        made.append({registered, run, verdict_seq, period, reading, promise, checked})

    view = views.cell_view(Ledger().read(), "alpha")

    assert {event["seq"] for event in view} == made[0]
    checked = next(event for event in view if event["kind"] == "promise-checked")
    assert "evidence_seqs" not in checked


def test_a_new_kind_stays_out_of_a_cells_view_until_it_is_named():
    event = {"seq": 1, "kind": "brand-new-kind", "writer": "cell:alpha", "bet": "alpha"}

    assert views.cell_view([event], "alpha") == []


def test_a_link_planted_at_the_views_path_is_replaced_and_its_target_left_alone(company, stub, board, tmp_path):
    target = tmp_path / "daniels-file"
    target.write_text("untouched")
    workspace = paths.workspaces() / "ws"
    workspace.mkdir(parents=True)
    (workspace / "ledger.jsonl").symlink_to(target)
    stub.play()

    done = company("session", "start", "cell", "--bet", "alpha", "--workspace", str(workspace))

    assert done.returncode == 0, done.stdout + done.stderr
    assert target.read_text() == "untouched"
    assert not (workspace / "ledger.jsonl").is_symlink()


def test_a_directory_planted_at_the_views_path_refuses_the_launch(company, stub, board):
    workspace = paths.workspaces() / "ws"
    (workspace / "ledger.jsonl").mkdir(parents=True)
    stub.play()

    done = company("session", "start", "cell", "--bet", "alpha", "--workspace", str(workspace))

    assert done.returncode == 1
    assert "no-context" in done.stdout
    assert stub.session_calls() == []


# What a refused launch leaves


FILLED_THEN = {
    "the kill switch pulled during the launch": ["import company.launcher", "company.launcher._really_prepare = company.launcher._prepare", "def prepare(*given):", "    prepared = company.launcher._really_prepare(*given)", "    company.launcher.kill_state.present = lambda: True", "    return prepared", "company.launcher._prepare = prepare"],
    "a start that cannot be logged": ["import company.ledger", "company.ledger.Ledger.really_append = company.ledger.Ledger.append", "def append(self, kind, *rest, **more):", "    if kind == 'session-started':", "        raise OSError('the disk is full')", "    return self.really_append(kind, *rest, **more)", "company.ledger.Ledger.append = append"],
    "a claude that cannot start": ["import company.launcher", "def spawn(launch):", "    raise OSError(13, 'Permission denied')", "company.launcher._spawn = spawn"],
    "a copy that fails part way": ["import company.views", "really_write = company.views.write", "def write(path, content):", "    if path.parent.name == 'transcripts':", "        raise OSError('the disk is full')", "    really_write(path, content)", "company.views.write = write"],
    "a start's record that cannot be written": run_file_fails("path.name == 'session.json'"),
}


@pytest.mark.parametrize("what", FILLED_THEN)
def test_an_auditor_launch_refused_after_its_workspace_was_filled_leaves_no_copy_there(company, stub, cell_run, tmp_path, monkeypatch, what):
    cell = cell_run()
    patch_every_company(tmp_path, monkeypatch, *FILLED_THEN[what])

    done = company("audit", cell["run"])

    assert done.returncode == 1, done.stdout + done.stderr
    assert events("launch-refused")[-1]["role"] == "auditor"
    assert [path for path in paths.workspaces().rglob(views.FILE) if path.parent.name != cell["run"]] == []
    assert list(paths.workspaces().rglob(audit.TRANSCRIPTS)) == []


def test_an_auditor_whose_group_cannot_be_recorded_is_stopped_and_leaves_no_copy_there(company, stub, cell_run, tmp_path, monkeypatch):
    cell = cell_run()
    stub.play({"do": "hang"})
    patch_every_company(tmp_path, monkeypatch, *run_file_fails("path.name == 'session.json' and value.get('group')"))

    done = company("audit", cell["run"])

    assert done.returncode == 1, done.stdout + done.stderr
    assert events("session-stopped")[-1]["reason"] == "not-recorded"
    assert [path for path in paths.workspaces().rglob(views.FILE) if path.parent.name != cell["run"]] == []
    assert list(paths.workspaces().rglob(audit.TRANSCRIPTS)) == []


# Confirmed by code


def test_a_result_no_record_shows_is_found_on_a_planted_transcript_and_confirmed_by_code(company, stub, cell_run):
    cell = cell_run()
    assert_cell_may_start(company)
    stub.play(claim_step(cell["session"]))

    done = company("audit", cell["run"])

    assert done.returncode == 0, done.stdout + done.stderr
    finding = events("finding")[-1]
    assert finding["writer"] == "auditor"
    assert finding["rubric"] == audit.UNSHOWN_RESULT
    confirmed = events("finding-confirmed")[-1]
    assert confirmed["writer"] == "treasurer"
    assert confirmed["finding_seq"] == finding["seq"]
    paused = events("cell-paused")[-1]
    assert (paused["writer"], paused["bet"], paused["cause_seq"]) == ("treasurer", "alpha", finding["seq"])
    assert_cell_refused(company)
    assert "confirmed by code" in done.stdout
    assert "company cell resume --bet alpha" in done.stdout
    assert f"Finding {finding['seq']}, {audit.UNSHOWN_RESULT}, bet alpha, confirmed by code" in company("digest").stdout


def assert_waits(company):
    assert events("finding-confirmed") == []
    assert events("cell-paused") == []
    assert_cell_may_start(company)
    assert company("treasurer", "check").returncode == 0
    assert events("finding-confirmed") == []


def test_a_result_a_config_run_shows_waits_for_daniel(company, stub, cell_run):
    config_run(registration(), sharpe=2.4049, total_return=0.1, max_drawdown=0.1)
    cell = cell_run()
    stub.play(claim_step(cell["session"]))

    assert company("audit", cell["run"]).returncode == 0

    assert len(events("finding")) == 1
    assert_waits(company)


def test_a_result_a_verdict_shows_waits_for_daniel(company, stub, cell_run):
    registered = registration()
    verdict = {"registration_seq": registered, "config_hash": "c", "passed": False, "failed_tests": [], "deflated_sharpe": 2.4, "holdout_return": 0.1, "max_drawdown": 0.1, "trials": 1, "config_run_seqs": [], "holdout_hash": "h"}
    Ledger().append("verdict", verdict, "treasurer")
    cell = cell_run()
    stub.play(claim_step(cell["session"]))

    assert company("audit", cell["run"]).returncode == 0

    assert_waits(company)


@pytest.mark.parametrize(
    ("figure", "said"),
    [
        ({"skew": 0.31}, "a skew of 0.31"),
        ({"kurtosis": 3.7}, "a kurtosis of 3.7"),
        ({"n_returns": 251}, "over 251 returns"),
    ],
)
def test_any_figure_a_config_run_holds_is_shown(company, stub, cell_run, figure, said):
    config_run(registration(), **figure)
    cell = cell_run(said=said)
    stub.play(claim_step(cell["session"], said, next(iter(figure.values()))))

    assert company("audit", cell["run"]).returncode == 0

    assert_waits(company)


def test_the_trials_a_verdict_holds_are_shown(company, stub, cell_run):
    registered = registration()
    verdict = {"registration_seq": registered, "config_hash": "c", "passed": False, "failed_tests": [], "deflated_sharpe": 0.1, "holdout_return": 0.1, "max_drawdown": 0.1, "trials": 37, "config_run_seqs": [], "holdout_hash": "h"}
    Ledger().append("verdict", verdict, "treasurer")
    said = "It took 37 trials."
    cell = cell_run(said=said)
    stub.play(claim_step(cell["session"], said, 37))

    assert company("audit", cell["run"]).returncode == 0

    assert_waits(company)


@pytest.mark.parametrize(
    ("said", "quote", "value"),
    [
        ("A Sharpe of 11.50 it was.", "1.5", 1.5),
        ("A Sharpe of 2.40 it was.", "Sharpe of 2", 2),
        ("A Sharpe of 2.40 it was.", ".40 it was", 0.4),
        ("A Sharpe of 2.40 it was.", "40 it was", 40),
        ("A Sharpe of 2.40 it was.", "Sharpe of 2.4", 2.4),
        ("Its Sharpe of 2.40 it was.", "ts Sharpe of 2.40", 2.4),
    ],
)
def test_a_quote_cut_out_of_the_middle_of_a_word_or_a_number_waits_for_daniel(company, stub, cell_run, said, quote, value):
    cell = cell_run(said=said)
    stub.play(claim_step(cell["session"], quote, value))

    assert company("audit", cell["run"]).returncode == 0

    assert len(events("finding")) == 1
    assert_waits(company)


def test_a_percent_of_a_recorded_fraction_is_shown(company, stub, cell_run):
    config_run(registration(), total_return=0.1234)
    said = "The backtest returned 12.3%."
    cell = cell_run(said=said)
    stub.play(claim_step(cell["session"], said, 12.3))

    assert company("audit", cell["run"]).returncode == 0

    assert_waits(company)


def test_another_bets_record_does_not_show_this_cells_result(company, stub, cell_run):
    config_run(registration("beta"), sharpe=2.4)
    cell = cell_run()
    stub.play(claim_step(cell["session"]))

    assert company("audit", cell["run"]).returncode == 0

    assert len(events("finding-confirmed")) == 1


def test_a_record_made_after_the_session_does_not_show_what_it_reported(company, stub, cell_run):
    cell = cell_run()
    config_run(registration(), sharpe=2.4)
    stub.play(claim_step(cell["session"]))

    assert company("audit", cell["run"]).returncode == 0

    assert len(events("finding-confirmed")) == 1


def test_a_quote_the_transcript_does_not_hold_waits_for_daniel(company, stub, cell_run):
    cell = cell_run()
    stub.play(claim_step(cell["session"], quote="The backtest returned a Sharpe of 9.90.", value=9.9))

    assert company("audit", cell["run"]).returncode == 0

    assert len(events("finding")) == 1
    assert_waits(company)


def test_a_value_the_quote_does_not_hold_waits_for_daniel(company, stub, cell_run):
    cell = cell_run()
    stub.play(claim_step(cell["session"], value=7.7))

    assert company("audit", cell["run"]).returncode == 0

    assert_waits(company)


@pytest.mark.parametrize("block", [{"type": "thinking", "thinking": REPORTED}, {"type": "thinking", "text": REPORTED}])
def test_a_quote_from_the_cells_reasoning_is_no_report_and_waits_for_daniel(company, stub, board, block):
    stub.play({"do": "reply", "request": "r1", "output": 10, "content": [block]})
    assert company("session", "start", "cell", "--bet", "alpha").returncode == 0
    cell = events("session-started")[-1]
    stub.play(claim_step(cell["session"]))

    assert company("audit", cell["run"]).returncode == 0

    assert_waits(company)


def test_a_quote_wrapped_differently_is_still_the_quote(company, stub, cell_run):
    cell = cell_run(said="The backtest returned\n  a Sharpe of 2.40 over the period.")
    stub.play(claim_step(cell["session"]))

    assert company("audit", cell["run"]).returncode == 0

    assert len(events("finding-confirmed")) == 1


def test_a_changed_transcript_confirms_nothing(company, stub, cell_run):
    cell = cell_run()
    fields = {"rubric": audit.UNSHOWN_RESULT, "summary": "s", "evidence": "e", "bet": "alpha", "session": cell["session"], "claim": {"quote": REPORTED, "value": 2.4}}
    Ledger().append("finding", fields, "auditor")
    (paths.runs() / cell["run"] / "transcript.jsonl").write_text("changed\n")

    assert company("treasurer", "check").returncode == 0

    assert events("finding-confirmed") == []


def test_a_finding_an_audit_left_is_confirmed_by_the_next_check_with_nothing_twice(company, stub, cell_run):
    cell = cell_run()
    fields = {"rubric": audit.UNSHOWN_RESULT, "summary": "s", "evidence": "e", "bet": "alpha", "session": cell["session"], "claim": {"quote": REPORTED, "value": 2.4}}
    Ledger().append("finding", fields, "auditor")

    first = company("treasurer", "check")
    second = company("treasurer", "check")

    assert first.returncode == 0, first.stderr
    assert "confirmed by code" in first.stdout
    assert "confirmed by code" not in second.stdout
    assert len(events("finding-confirmed")) == 1
    assert len(events("cell-paused")) == 1


def test_a_check_stopped_between_the_confirmation_and_the_pause_is_finished(company, stub, cell_run):
    cell = cell_run()
    fields = {"rubric": audit.UNSHOWN_RESULT, "summary": "s", "evidence": "e", "bet": "alpha", "session": cell["session"], "claim": {"quote": REPORTED, "value": 2.4}}
    seq = Ledger().append("finding", fields, "auditor")["seq"]
    Ledger().append("finding-confirmed", {"finding_seq": seq}, "treasurer")

    assert company("treasurer", "check").returncode == 0

    assert len(events("finding-confirmed")) == 1
    assert events("cell-paused")[-1]["cause_seq"] == seq


def test_a_daniels_word_stopped_before_its_pause_is_finished_by_the_check_though_code_would_not_confirm(company, stub, cell_run):
    cell = cell_run()
    fields = {"rubric": audit.UNSHOWN_RESULT, "summary": "s", "evidence": "e", "bet": "alpha", "session": cell["session"], "claim": {"quote": "Words it never said, 9.9.", "value": 9.9}}
    seq = Ledger().append("finding", fields, "auditor")["seq"]
    Ledger().append("finding-confirmed", {"finding_seq": seq}, "board")

    assert company("treasurer", "check").returncode == 0

    assert len(events("finding-confirmed")) == 1
    assert events("cell-paused")[-1]["cause_seq"] == seq


def test_finishing_daniels_word_is_not_called_the_codes(company, stub, cell_run):
    cell = cell_run()
    fields = {"rubric": audit.UNSHOWN_RESULT, "summary": "s", "evidence": "e", "bet": "alpha", "session": cell["session"], "claim": {"quote": REPORTED, "value": 2.4}}
    seq = Ledger().append("finding", fields, "auditor")["seq"]
    Ledger().append("finding-confirmed", {"finding_seq": seq}, "board")

    done = company("treasurer", "check")

    assert "confirmed by code" not in done.stdout
    assert events("cell-paused")[-1]["cause_seq"] == seq


def test_a_claim_on_any_other_rubric_is_not_confirmed_by_code(company, stub, cell_run):
    cell = cell_run()
    fields = {"rubric": "false-statement", "summary": "s", "evidence": "e", "bet": "alpha", "session": cell["session"], "claim": {"quote": REPORTED, "value": 2.4}}
    Ledger().append("finding", fields, "auditor")

    assert_waits(company)


def test_a_resumed_cell_is_not_paused_again_for_the_same_finding(company, stub, cell_run):
    cell = cell_run()
    stub.play(claim_step(cell["session"]))
    assert company("audit", cell["run"]).returncode == 0
    assert company("cell", "resume", "--bet", "alpha").returncode == 0

    assert company("treasurer", "check").returncode == 0

    assert_cell_may_start(company)


# Confirmed by Daniel


def test_a_finding_code_cannot_check_waits_and_the_cell_runs_until_daniel_confirms(company, stub, cell_run):
    cell = cell_run()
    audit_with_finding(company, stub, cell)
    seq = events("finding")[-1]["seq"]
    assert_waits(company)
    assert cell_run()["bet"] == "alpha"

    done = company("finding", "confirm", str(seq), "--message", "1234")

    assert done.returncode == 0, done.stderr
    confirmed = events("finding-confirmed")[-1]
    assert (confirmed["writer"], confirmed["finding_seq"], confirmed["message"]) == ("board", seq, "1234")
    paused = events("cell-paused")[-1]
    assert (paused["writer"], paused["bet"], paused["cause_seq"], paused["scope"]) == ("treasurer", "alpha", seq, "cell")
    assert_cell_refused(company)
    assert "company cell resume --bet alpha" in done.stdout
    assert company("cell", "resume", "--bet", "alpha").returncode == 0
    assert_cell_may_start(company)


def test_the_digest_says_a_confirmed_finding_needs_no_more_word(company, stub, cell_run):
    cell = cell_run()
    audit_with_finding(company, stub, cell)
    seq = events("finding")[-1]["seq"]
    assert company("finding", "confirm", str(seq)).returncode == 0

    page = company("digest").stdout

    assert f"{MARKER} summary" in page
    assert f"company finding confirm {seq}" not in page
    assert "Paused now: cell alpha" in page


@pytest.mark.parametrize("seq", ["999", "1"])
def test_only_a_finding_can_be_confirmed(company, board, seq):
    done = company("finding", "confirm", seq)

    assert done.returncode == 1
    assert "is no finding" in done.stderr
    assert events("append-refused")[-1]["reason"] == "no-such-finding"
    assert events("finding-confirmed") == []


def test_a_finding_is_confirmed_once(company, stub, cell_run):
    cell = cell_run()
    audit_with_finding(company, stub, cell)
    seq = str(events("finding")[-1]["seq"])
    assert company("finding", "confirm", seq).returncode == 0

    done = company("finding", "confirm", seq)

    assert done.returncode == 1
    assert "already confirmed" in done.stderr
    assert len(events("finding-confirmed")) == 1
    assert len(events("cell-paused")) == 1


def test_a_confirm_stopped_before_its_pause_is_finished_by_saying_it_again(company, board):
    seq = Ledger().append("finding", {"rubric": "false-statement", "summary": "s", "evidence": "e", "bet": "alpha"}, "auditor")["seq"]
    Ledger().append("finding-confirmed", {"finding_seq": seq}, "board")

    done = company("finding", "confirm", str(seq))

    assert done.returncode == 0, done.stderr
    assert len(events("finding-confirmed")) == 1
    assert events("cell-paused")[-1]["cause_seq"] == seq


def test_a_finding_on_no_bet_is_confirmed_with_no_pause_and_says_so(company, board):
    seq = Ledger().append("finding", {"rubric": "false-statement", "summary": "s", "evidence": "e"}, "auditor")["seq"]

    done = company("finding", "confirm", str(seq))

    assert done.returncode == 0, done.stderr
    assert events("cell-paused") == []
    assert "no bet" in done.stdout


# Read-only, with only its finding tool


def test_the_auditor_has_read_only_file_tools_and_only_its_finding_tool(audited, stub):
    audited({"do": "list-tools"})

    assert stub.argument("--tools") == "Read,Glob,Grep"
    assert stub.argument("--allowedTools") == "Read,Glob,Grep,mcp__company__record_finding"
    assert [tool["name"] for tool in stub.tool_lists()[-1]["result"]["tools"]] == ["record_finding"]
    for tool in ("Write", "Edit", "Bash", "WebFetch", "WebSearch"):
        assert tool not in stub.argument("--allowedTools").split(",")


def test_a_recorded_auditor_that_tries_to_write_elsewhere_is_refused_and_logged(audited, stub):
    attempts = [
        {"do": "tool", "name": "note", "arguments": {"text": "written elsewhere"}},
        {"do": "tool", "name": "record_promise", "arguments": {"promise": "p", "due_date": "2099-01-01"}},
        {"do": "tool", "name": "register_strategy", "arguments": {}},
        company_step("ledger", "append", "finding-confirmed", "--writer", "treasurer", "--fields", '{"finding_seq": 1}'),
        company_step("finding", "confirm", "1"),
    ]

    done, _ = audited(*attempts)

    assert done.returncode == 0, done.stdout + done.stderr
    assert all(result["result"]["isError"] for result in stub.tool_results())
    assert [run["exit"] for run in stub.runs()] == [1, 1]
    assert events("session-note") == []
    assert events("promise-recorded") == []
    assert events("finding-confirmed") == []
    refused = events("append-refused")
    assert [(event["attempted_kind"], event["reason"]) for event in refused] == [
        ("session-note", "tool-not-in-role"),
        ("promise-recorded", "tool-not-in-role"),
        ("strategy-registered", "tool-not-in-role"),
        ("finding-confirmed", "inside-a-session"),
        ("finding-confirmed", "inside-a-session"),
    ]


def tool_use(name, identifier="toolu_1"):
    return {"type": "tool_use", "id": identifier, "name": name, "input": {"file_path": "/elsewhere"}}


def test_a_recorded_auditor_that_tries_a_built_in_write_has_it_logged(audited, stub):
    calls = [tool_use("Write", "toolu_1"), tool_use("Bash", "toolu_2"), tool_use("Read", "toolu_3"), tool_use("mcp__company__record_finding", "toolu_4")]

    done, _ = audited({"do": "reply", "request": "r9", "output": 10, "content": calls})

    assert done.returncode == 0, done.stdout + done.stderr
    # What refuses it is `--tools` and the settings, which only a real session can prove: ticket 13's probe.
    assert "Write" not in stub.argument("--tools").split(",")
    started = events("session-started")[-1]
    refused = events("append-refused")
    assert [(event["tool"], event["reason"], event["attempted_writer"], event["session"]) for event in refused] == [
        ("write", "tool-not-in-role", "auditor", started["session"]),
        ("bash", "tool-not-in-role", "auditor", started["session"]),
    ]
    assert refused[-1]["seq"] < events("session-ended")[-1]["seq"]


def test_the_auditors_whole_ledger_copy_does_not_outlive_its_session(audited, stub):
    audited()

    workspace = Path(stub.session_calls()[-1]["cwd"])
    assert workspace.is_dir()
    assert not (workspace / "ledger.jsonl").exists()
    assert not (workspace / "transcripts").exists()


def test_the_copy_goes_even_if_the_auditors_launcher_died(company, stub, cell_run):
    cell = cell_run()
    stub.play({"do": "hang"})
    launch = subprocess.Popen([COMPANY, "audit", cell["run"]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wait_for(lambda: any("hanging" in line for line in stub.progress()))
    workspace = Path(stub.session_calls()[-1]["cwd"])
    assert (workspace / "ledger.jsonl").exists()
    launch.kill()
    launch.wait()
    stub.play()

    assert company("session", "start", "probe").returncode == 0

    assert events("session-stopped")[-1]["reason"] == "launcher-gone"
    assert not (workspace / "ledger.jsonl").exists()
    assert not (workspace / "transcripts").exists()


def test_an_auditor_given_nothing_to_audit_leaves_its_workspace_alone(company, stub, board):
    workspace = paths.workspaces() / "ws"
    workspace.mkdir(parents=True)
    (workspace / "ledger.jsonl").write_text("a cell's view\n")
    stub.play()

    assert company("session", "start", "auditor", "--workspace", str(workspace)).returncode == 0

    assert (workspace / "ledger.jsonl").read_text() == "a cell's view\n"


def test_a_cells_view_is_left_in_place_for_it(company, stub, cell_run):
    cell_run()

    assert (Path(stub.session_calls()[-1]["cwd"]) / "ledger.jsonl").exists()


def test_the_auditors_settings_deny_the_ledger_and_keep_it_in_its_workspace(audited, stub):
    audited()

    settings = stub.settings()
    assert settings["permissions"]["blockWritesOutsideWorkingDirectories"] is True
    assert settings["permissions"]["blockReadsOutsideWorkingDirectories"] is True
    assert f"Edit(//{str(paths.home()).lstrip('/')}/ledger*)" in settings["permissions"]["deny"]


# Its goal


def test_the_goal_states_its_rubric_and_that_it_reports_to_daniel_only_and_passes_the_scan():
    goal = goals.load("auditor")

    assert goals.problems(goal.text) == []
    for rubric in audit.RUBRICS:
        assert f"`{rubric}`" in goal.text
    flat = " ".join(goal.text.split())
    assert "You report to Daniel only" in flat
    assert "record_finding" in flat
    assert "no web read" in flat


def test_the_rubric_is_the_designs_four(repo):
    assert audit.RUBRICS == ("false-statement", "broken-promise", "unshown-result", "rule-broken")
    design = (repo / "docs/design.md").read_text()
    for rubric in audit.RUBRICS:
        assert f"`{rubric}`" in design


# The daily sample and the weekly full pass


def ended_cell(run, ended, bet="alpha", role="cell", transcript=True):
    """A session's two events as the ledger holds them, with its transcript kept."""
    session = hashlib.md5(run.encode(), usedforsecurity=False).hexdigest()
    session = f"{session[:8]}-{session[8:12]}-4{session[13:16]}-8{session[17:20]}-{session[20:32]}"
    path, digest = "none", "none"
    if transcript:
        directory = paths.runs() / run
        directory.mkdir(parents=True)
        kept = directory / "transcript.jsonl"
        kept.write_text("{}\n")
        path, digest = str(kept), hashlib.sha256(kept.read_bytes()).hexdigest()
    stamp = times.stamp(ended)
    started = {"seq": 0, "ts": stamp, "kind": "session-started", "writer": "launcher", "session": session, "role": role, "model": "claude-opus-5-5", "run": run}
    if bet:
        started["bet"] = bet
    closing = {"seq": 0, "ts": stamp, "kind": "session-ended", "writer": "launcher", "session": session, "exit": 0, "transcript_path": path, "transcript_hash": digest, "weight": 0.0}
    return [started, closing]


def numbered(*pairs):
    return [{**event, "seq": seq} for seq, event in enumerate((event for pair in pairs for event in pair), start=1)]


def test_the_sample_is_one_of_the_last_days_cell_sessions():
    now = times.now()
    given = numbered(
        ended_cell("old", now - timedelta(hours=25)),
        ended_cell("new-1", now - timedelta(hours=2)),
        ended_cell("new-2", now - timedelta(hours=1)),
        ended_cell("a-probe", now - timedelta(hours=1), bet=None, role="probe"),
        ended_cell("no-record", now - timedelta(hours=1), transcript=False),
    )

    seen = {tuple(audit.sample(given, now)) for _ in range(40)}

    assert seen == {("new-1",), ("new-2",)}


def test_the_sample_of_a_quiet_day_is_nothing():
    now = times.now()

    assert audit.sample(numbered(ended_cell("old", now - timedelta(days=2))), now) == []


def test_the_full_pass_is_every_cell_session_of_the_last_seven_days():
    now = times.now()
    given = numbered(
        ended_cell("too-old", now - timedelta(days=8)),
        ended_cell("week-old", now - timedelta(days=6)),
        ended_cell("new", now - timedelta(hours=1), bet="beta"),
        ended_cell("a-probe", now - timedelta(hours=1), bet=None, role="probe"),
    )

    assert audit.full_pass(given, now) == ["week-old", "new"]


def test_an_audits_findings_are_its_own_sessions_and_no_others():
    session = "bbbbbbbb-0000-4000-8000-000000000000"
    other = "cccccccc-0000-4000-8000-000000000000"
    started = {"kind": "session-started", "writer": "launcher", "session": session}
    finding = {"kind": "finding", "writer": "auditor", "rubric": "r", "summary": "s", "evidence": "e"}
    given = [
        {**finding, "seq": 1},
        {**started, "seq": 2},
        {**finding, "seq": 3},
        {**finding, "seq": 4, "writer": "treasurer"},
        {"kind": "session-note", "writer": "probe", "session": other, "seq": 5},
        {"kind": "session-ended", "writer": "launcher", "session": session, "seq": 6},
        {**finding, "seq": 7},
    ]

    assert audit.findings_of(given, session) == 1


def test_the_sample_and_the_full_pass_are_jobs(company, systemctl):
    assert ("audit", "--sample", "--scheduled") in [job.command for job in schedule.JOBS]
    assert ("audit", "--full", "--scheduled") in [job.command for job in schedule.JOBS]

    done = company("schedule", "list")

    assert "audit-sample: `company audit --sample --scheduled`, on *-*-* 01:00:00 UTC" in done.stdout
    assert "audit-full: `company audit --full --scheduled`, on Mon *-*-* 02:00:00 UTC" in done.stdout


def test_by_hand_the_sample_needs_a_word_and_says_when_there_is_nothing(company, stub, board):
    done = company("audit", "--sample")

    assert done.returncode == 0, done.stderr
    assert "Nothing to audit" in done.stdout
    assert stub.session_calls() == []


def test_the_full_pass_by_hand_audits_every_run_in_one_session(company, stub, cell_run):
    first, second = cell_run(), cell_run(bet="beta")
    stub.play(finding_step(first["session"]), finding_step(second["session"], summary="second"))

    done = company("audit", "--full")

    assert done.returncode == 0, done.stdout + done.stderr
    assert events("session-started")[-1]["audited_runs"] == [first["run"], second["run"]]
    assert [event["bet"] for event in events("finding")] == ["alpha", "beta"]
    assert "Findings from this audit: 2" in done.stdout


@pytest.fixture
def schedule_on(company, board, systemctl):
    done = company("schedule", "enable", "--message", "1234")
    assert done.returncode == 0, done.stderr


def test_the_sample_job_starts_a_session_with_the_schedule_on_and_uses_no_word(company, stub, cell_run, schedule_on):
    cell = cell_run()
    stub.play({"do": "list-tools"})

    done = company("schedule", "run", "audit-sample")

    assert done.returncode == 0, done.stdout + done.stderr
    started = events("session-started")[-1]
    assert started["role"] == "auditor"
    assert started["gate"] == "schedule"
    assert started["audited_runs"] == [cell["run"]]


def test_the_full_pass_job_with_nothing_to_audit_starts_nothing_and_fails_nothing(company, stub, schedule_on):
    done = company("schedule", "run", "audit-full")

    assert done.returncode == 0, done.stdout + done.stderr
    assert stub.session_calls() == []
    assert events("job-failed") == []


def test_a_refused_audit_on_the_schedule_is_a_job_that_failed(company, stub, cell_run, schedule_on):
    cell_run()
    assert company("settings", "set", "auditor_model", "claude-opus-5-5").returncode == 0

    done = company("schedule", "run", "audit-sample")

    assert done.returncode == 1
    assert events("job-failed")[-1]["job"] == "audit-sample"
    assert "audit-sample" in company("digest").stdout


# `claude` from a timer


def _unit(name):
    return (paths.systemd_user() / f"company-{name}.service").read_text()


def test_a_job_finds_the_claude_install_resolved_on_the_blockers_path(company, stub, cell_run, schedule_on, monkeypatch):
    """The user manager's own path may not hold `claude`, so the blocker's path stands in for it: only the unit can say where it is."""
    cell = cell_run()
    stub.play({"do": "list-tools"})
    blockers_path = os.environ["PATH"]
    monkeypatch.delenv("COMPANY_CLAUDE_BIN")
    monkeypatch.setenv("PATH", f"{stub.directory}{os.pathsep}{blockers_path}")
    done = company("schedule", "install")
    assert done.returncode == 0, done.stderr
    monkeypatch.setenv("PATH", blockers_path)
    before = len(stub.session_calls())

    lines = _unit("audit-sample").splitlines()
    carried = dict(shlex.split(line.removeprefix("Environment="))[0].split("=", 1) for line in lines if line.startswith("Environment="))
    command = shlex.split(next(line for line in lines if line.startswith("ExecStart=")).removeprefix("ExecStart="))

    assert carried["COMPANY_CLAUDE_BIN"] == str(stub.binary)
    environment = {name: value for name, value in os.environ.items() if name != "COMPANY_CLAUDE_BIN"} | carried
    environment["PATH"] = blockers_path
    fired = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=60, check=False)

    assert fired.returncode == 0, fired.stdout + fired.stderr
    assert len(stub.session_calls()) == before + 1
    assert events("session-started")[-1]["audited_runs"] == [cell["run"]]


def test_an_install_finding_no_claude_says_so_and_writes_the_units_without_it(company, systemctl, monkeypatch, tmp_path):
    empty = tmp_path / "no-claude-here"
    empty.mkdir()
    monkeypatch.delenv("COMPANY_CLAUDE_BIN", raising=False)
    monkeypatch.setenv("PATH", f"{systemctl.directory}{os.pathsep}{empty}")

    done = company("schedule", "install")

    assert done.returncode == 0, done.stderr
    assert "no-binary" in done.stderr
    assert "COMPANY_CLAUDE_BIN" not in _unit("audit-sample")


def test_enable_carries_it_too(company, stub, board, systemctl):
    assert company("schedule", "enable", "--message", "1234").returncode == 0

    assert f"COMPANY_CLAUDE_BIN={stub.binary}" in _unit("audit-full")
