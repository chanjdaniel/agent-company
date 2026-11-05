"""The goal texts: in the package, versioned, and scanned, so that the goal itself rules out deception."""

import pytest

from company import goals, governor

GOOD = "\n".join(["A goal.", *goals.HONESTY_CONSTRAINTS])


def test_every_role_has_a_goal_that_loads():
    for role in governor.ROLES:
        assert goals.load(role).version >= 1


def test_every_goal_file_in_the_package_passes_the_scan_and_is_versioned():
    found = goals.every_goal_file()
    assert len(found) >= len(governor.ROLES)
    for name, text in found.items():
        assert goals.problems(text) == [], name
        assert goals._FILE.fullmatch(name), name


@pytest.mark.parametrize(
    "phrase",
    ["whatever it takes", "at all costs", "Whatever It Takes", "AT ALL COSTS", "whatever\nit  takes"],
)
def test_the_scan_fails_on_a_banned_phrase(phrase):
    assert goals.problems(f"{GOOD}\nDo {phrase}.") != []


@pytest.mark.parametrize("constraint", goals.HONESTY_CONSTRAINTS)
def test_the_scan_fails_on_a_goal_without_a_constraint(constraint):
    assert goals.problems(GOOD.replace(constraint, "")) != []


def test_the_scan_passes_a_good_goal_even_when_a_sentence_is_wrapped():
    assert goals.problems(GOOD.replace(" ", "\n", 1)) == []


@pytest.fixture
def goal_files(monkeypatch):
    """Put these in place of the package's goal files."""

    def plant(files):
        monkeypatch.setattr(goals, "every_goal_file", lambda: files)

    return plant


def test_the_newest_version_is_the_one_loaded(goal_files):
    goal_files({"probe.v1.md": GOOD, "probe.v10.md": GOOD + "\nnewest", "probe.v2.md": GOOD})
    assert goals.load("probe").version == 10
    assert "newest" in goals.load("probe").text


def test_a_role_with_no_goal_is_refused(goal_files):
    goal_files({"cell.v1.md": GOOD})
    with pytest.raises(goals.GoalRefused):
        goals.load("probe")


def test_a_goal_that_fails_the_scan_is_refused_at_load(goal_files):
    goal_files({"probe.v1.md": GOOD + "\nwhatever it takes"})
    with pytest.raises(goals.GoalRefused, match="whatever it takes"):
        goals.load("probe")
