"""The contract data file, held equal to the table in `docs/design.md`."""

import json
import re
from importlib import resources

import pytest


@pytest.fixture
def contract():
    return json.loads(resources.files("company").joinpath("ledger_contract.json").read_text())


def names(cell):
    return re.findall(r"`([^`]+)`", cell)


@pytest.fixture
def design_table(repo):
    """Each kind's row from the design's table, failing if the table has moved."""
    text = (repo / "docs/design.md").read_text()
    section = text.split("### Event kinds", 1)[1].split("Notes on single kinds", 1)[0]
    rows = {}
    for line in section.splitlines():
        if line.startswith("| `"):
            kind, group, writers, required, optional = (c.strip() for c in line.strip().strip("|").split("|"))
            rows[names(kind)[0]] = {
                "group": group,
                "writers": names(writers),
                "required": names(required),
                "optional": names(optional),
            }
    assert len(rows) > 60
    return rows


def test_the_contract_holds_every_kind_in_the_design_and_no_other(contract, design_table):
    assert set(contract["kinds"]) == set(design_table)


def test_each_kind_matches_the_design_row(contract, design_table):
    for kind, row in design_table.items():
        entry = contract["kinds"][kind]
        assert entry["group"] == row["group"], kind
        assert set(entry["writers"]) == set(row["writers"]), kind
        assert set(entry["required"]) == set(row["required"]), kind
        assert set(entry["optional"]) == set(row["optional"]), kind


def test_the_writers_match_the_design(contract, repo):
    text = (repo / "docs/design.md").read_text()
    section = text.split("### Writers", 1)[1].split("**No agent may write", 1)[0]
    lines = {line.split(":**")[0].strip("- *"): names(line) for line in section.splitlines() if ":**" in line}
    assert contract["writers"]["board"] == lines["Board"]
    assert contract["writers"]["code"] == lines["Code"]
    assert contract["writers"]["agents"] == lines["Agents"]


def test_every_writer_in_a_kind_is_a_known_writer(contract):
    known = {writer for group in contract["writers"].values() for writer in group}
    for kind, entry in contract["kinds"].items():
        assert set(entry["writers"]) <= known, kind


def test_agents_write_only_the_kinds_the_design_lists_for_them(contract):
    """No agent may write the Treasurer's money, resource or decision events."""
    agents = set(contract["writers"]["agents"])
    written = {
        agent: {kind for kind, entry in contract["kinds"].items() if agent in entry["writers"]} for agent in agents
    }
    assert written == {
        "cell:<bet>": {
            "strategy-registered",
            "experiment-registered",
            "promise-recorded",
            "target-proposed",
            "draft-proposed",
            "split-proposed",
            "session-note",
        },
        "strategy": {"memo-written"},
        "auditor": {"finding"},
        "retro": {"postmortem", "retro-proposal"},
        "probe": {"session-note"},
    }


def test_no_field_is_both_required_and_optional_or_set_by_the_ledger(contract):
    for kind, entry in contract["kinds"].items():
        assert not set(entry["required"]) & set(entry["optional"]), kind
        assert not {"seq", "ts", "kind", "writer", "prev"} & (set(entry["required"]) | set(entry["optional"])), kind


def test_a_refusal_event_can_be_written_by_every_code_writer(contract):
    assert set(contract["kinds"]["append-refused"]["writers"]) == set(contract["writers"]["code"])
