"""The project's shape: no runtime dependency, one test command, and a CI workflow that holds no trust."""

import ast
import os
import re
import sys
import tomllib
from pathlib import Path

import pytest


@pytest.fixture
def pyproject(repo):
    return tomllib.loads((repo / "pyproject.toml").read_text())


@pytest.fixture
def workflow(repo):
    return (repo / ".github/workflows/ci.yml").read_text()


def test_the_runtime_declares_no_dependency(pyproject):
    assert pyproject["project"]["dependencies"] == []
    assert pyproject["project"]["requires-python"].startswith(">=3.13")


def test_pytest_is_the_one_development_dependency(pyproject):
    assert [re.split(r"[<>=~! ]", item)[0] for item in pyproject["dependency-groups"]["dev"]] == ["pytest"]


def test_the_package_imports_only_the_standard_library(repo):
    allowed = set(sys.stdlib_module_names) | {"company"}
    for path in (repo / "src/company").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                roots = [node.module.split(".")[0]]
            else:
                continue
            assert set(roots) <= allowed, f"{path}: {roots}"


def test_the_company_command_is_installed():
    assert (Path(sys.executable).parent / "company").is_file()


def test_runtime_state_defaults_outside_the_repository(monkeypatch):
    from company import paths

    monkeypatch.delenv("COMPANY_HOME")
    monkeypatch.delenv("COMPANY_CONFIG")
    user_home = Path(os.environ["HOME"])

    assert paths.home() == user_home / ".local/state/agent-company"
    assert paths.config() == user_home / ".config/agent-company"


def test_transcripts_default_to_claude_codes_own_place_and_follow_its_variable(monkeypatch, tmp_path):
    from company import paths

    monkeypatch.delenv("CLAUDE_CONFIG_DIR")
    assert paths.claude_projects() == Path(os.environ["HOME"]) / ".claude/projects"

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    assert paths.claude_projects() == tmp_path / "projects"


def test_runtime_state_follows_its_variables(monkeypatch, tmp_path):
    from company import paths

    monkeypatch.setenv("COMPANY_HOME", str(tmp_path / "h"))
    monkeypatch.setenv("COMPANY_CONFIG", str(tmp_path / "c"))

    assert paths.home() == tmp_path / "h"
    assert paths.config() == tmp_path / "c"


def test_the_ci_job_is_named_test_and_runs_the_test_command(workflow):
    jobs = re.findall(r"^  ([\w-]+):$", workflow.split("\njobs:\n", 1)[1], re.MULTILINE)
    assert jobs == ["test"]
    assert re.search(r"^\s+- run: uv run --locked pytest$", workflow, re.MULTILINE)


def test_the_ci_gives_the_strategy_runner_a_bwrap_that_can_start_before_the_tests(workflow):
    """Ubuntu's runner restricts unprivileged user namespaces, and `bwrap` needs one, so installing it alone would not do."""
    install = workflow.index("apt-get install -y bubblewrap")
    allow = workflow.index("kernel.apparmor_restrict_unprivileged_userns=0")
    assert max(install, allow) < workflow.index("uv run --locked pytest")


def test_the_ci_runs_on_each_pr_to_dev_and_main(workflow):
    assert re.search(r"^  pull_request:\n    branches: \[dev, main\]$", workflow, re.MULTILINE)


def test_the_ci_pins_each_action_by_commit_hash(workflow):
    used = re.findall(r"uses:\s*(\S+)", workflow)
    assert used
    for action in used:
        assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", action), action


def test_the_ci_is_read_only_and_holds_no_secret(workflow):
    assert re.search(r"^permissions:\n  contents: read$", workflow, re.MULTILINE)
    assert len(re.findall(r"permissions:", workflow)) == 1
    assert "secrets." not in workflow
    assert "github.token" not in workflow
    assert "pull_request_target" not in workflow
    assert "persist-credentials: false" in workflow
