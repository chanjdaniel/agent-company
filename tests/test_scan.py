"""The scan: clean on this repository, and shown catching each thing it bans in a temporary copy."""

import shutil
import subprocess

import pytest
from scan_rules import scan, tracked_files

from company import banned

# Assembled, so that no secret scanner mistakes this file for holding a real key.
ANTHROPIC_KEY = "sk-ant-" + "api03-" + "x1y2z3" * 8
OPENAI_KEY = "sk-" + "a1B2c3D4" * 6
GITHUB_TOKEN = "ghp_" + "a1B2c3D4" * 5
AWS_KEY = "AKIA" + "ABCD1234" * 2
PAPER_KEY = "PK" + "ABCD1234" * 2 + "XY"
LIVE_KEY = "AK" + "ABCD1234" * 2 + "XY"
PRIVATE_KEY = "-----BEGIN RSA " + "PRIVATE KEY-----"
LIVE_HOST = "api." + "alpaca.markets"
PAPER_HOST = "paper-api.alpaca.markets"
DATA_HOST = "data.alpaca.markets"

PLANTS = [
    ("model-key-variable", 'os.environ["ANTHROPIC_API_KEY"]'),
    ("model-key-variable", "ANTHROPIC_AUTH_TOKEN=x"),
    ("model-key-variable", "ANTHROPIC_BASE_URL=x"),
    ("model-key-variable", "CLAUDE_CODE_USE_BEDROCK=1"),
    ("model-key-variable", "CLAUDE_CODE_USE_VERTEX=1"),
    ("model-key-variable", "CLAUDE_CODE_USE_FOUNDRY=1"),
    ("model-key-variable", "CLAUDE_CODE_OAUTH_TOKEN=x"),
    ("model-key-variable", "AWS_BEARER_TOKEN_BEDROCK=x"),
    ("model-key-variable", "OPENAI_API_KEY=x"),
    ("model-key-variable", "GEMINI_API_KEY=x"),
    ("model-vendor-host", "host = 'api.anthropic.com'"),
    ("model-vendor-host", "host = 'api.openai.com'"),
    ("model-vendor-host", "host = 'generativelanguage.googleapis.com'"),
    ("model-vendor-host", "host = 'bedrock-runtime.us-east-1.amazonaws.com'"),
    ("model-vendor-host", "host = 'openrouter.ai'"),
    ("model-sdk", "import anthropic"),
    ("model-sdk", "from anthropic import Anthropic"),
    ("model-sdk", "import openai"),
    ("model-sdk", "from claude_agent_sdk import query"),
    ("model-sdk", "from google import genai"),
    ("model-sdk", "import google.generativeai"),
    ("model-sdk", 'dependencies = [\n  "anthropic>=1",\n]'),
    ("model-sdk", 'name = "anthropic"'),
    ("model-sdk", "require('@anthropic-ai/sdk')"),
    ("api-key-helper", '{"apiKeyHelper": "./key.sh"}'),
    ("bare-mode", 'command = ["claude", "-p", "--bare"]'),
    ("extra-usage-setting", '{"extraUsage": true}'),
    ("extra-usage-setting", "extra_usage = True"),
    ("extra-usage-setting", "--extra-usage"),
    ("extra-usage-setting", '{"allowOverage": true}'),
    ("extra-usage-setting", "overage_enabled = True"),
    ("live-broker-host", f"host = '{LIVE_HOST}'"),
    ("live-broker-host", f"host = '{LIVE_HOST.upper()}'"),
    ("broker-key-variable", "APCA_API_KEY_ID=x"),
    ("broker-key-variable", 'os.environ["APCA_API_SECRET_KEY"]'),
    ("broker-key-variable", "APCA_API_BASE_URL=x"),
    ("paper-reach", f"host = '{PAPER_HOST}'"),
    ("paper-reach", f"host = '{DATA_HOST}'"),
    ("paper-reach", '{"APCA-API-KEY-ID": key}'),
    ("real-key-shape", f"key = '{ANTHROPIC_KEY}'"),
    ("real-key-shape", f"key = '{LIVE_KEY}'"),
    ("real-key-shape", f"key = '{OPENAI_KEY}'"),
    ("real-key-shape", f"key = '{GITHUB_TOKEN}'"),
    ("real-key-shape", f"key = '{AWS_KEY}'"),
    ("real-key-shape", f"key = '{PAPER_KEY}'"),
    ("real-key-shape", PRIVATE_KEY),
    ("url", "see https://example.com/page"),
    ("url", "see http://example.com"),
    ("url", "see wss://example.com/socket"),
]

# Where the documents may name a thing, and what they still may not.
DOCUMENT_TEXT = [
    ("model-key-variable", "ANTHROPIC_API_KEY"),
    ("api-key-helper", "apiKeyHelper"),
    ("bare-mode", "--bare"),
    ("url", "https://example.com/source"),
]
DOCUMENTS = ["docs/design.md", "docs/first-run.md", "docs/research/2026-11-02-org-and-profit-loops/report.md"]
OUTSIDE_DOCUMENTS = [
    "README.md",
    "CLAUDE.md",
    "docs/other.md",
    "docs/runs/report.md",
    "docs/design.md.bak",
    "src/company/planted.py",
    "tests/planted.py",
    "tests/harness/planted.py",
    ".github/workflows/ci.yml",
]


@pytest.fixture(scope="module")
def copy(tmp_path_factory, request):
    """A git-listed copy of every tracked file, shared because each test puts back what it planted."""
    source = request.config.rootpath
    root = tmp_path_factory.mktemp("repository-copy")
    for path in tracked_files(source):
        if (source / path).is_file():
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / path, root / path)
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    return root


@pytest.fixture
def plant(copy):
    """Add text to a file in the copy, and restore the file when the test ends."""
    restore = []

    def write(path, text):
        file = copy / path
        file.parent.mkdir(parents=True, exist_ok=True)
        before = file.read_bytes() if file.exists() else None
        restore.append((file, before))
        with file.open("a") as out:
            out.write(f"\n{text}\n")

    yield write
    for file, before in reversed(restore):
        if before is None:
            file.unlink()
        else:
            file.write_bytes(before)


def rules_found(root, path):
    return {finding.rule for finding in scan(root) if finding.path == path}


def test_this_repository_is_clean(repo):
    assert [str(finding) for finding in scan(repo)] == []


def test_the_scan_walks_the_repository(repo):
    files = tracked_files(repo)
    assert {"README.md", "pyproject.toml", "docs/design.md", ".github/workflows/ci.yml"} <= set(files)
    assert "src/company/ledger.py" in files


def test_the_copy_starts_clean(copy):
    assert scan(copy) == []


@pytest.mark.parametrize(("rule", "text"), PLANTS)
def test_each_banned_thing_is_caught(copy, plant, rule, text):
    plant("src/company/planted.py", text)
    assert rule in rules_found(copy, "src/company/planted.py")


@pytest.mark.parametrize(("rule", "text"), DOCUMENT_TEXT)
@pytest.mark.parametrize("path", DOCUMENTS)
def test_the_documents_may_name_these(copy, plant, path, rule, text):
    plant(path, text)
    assert rule not in rules_found(copy, path)


@pytest.mark.parametrize(("rule", "text"), DOCUMENT_TEXT)
@pytest.mark.parametrize("path", OUTSIDE_DOCUMENTS)
def test_the_same_text_is_caught_outside_the_documents(copy, plant, path, rule, text):
    plant(path, text)
    assert rule in rules_found(copy, path)


@pytest.mark.parametrize("path", DOCUMENTS)
@pytest.mark.parametrize(
    ("rule", "text"),
    [
        ("real-key-shape", ANTHROPIC_KEY),
        ("live-broker-host", LIVE_HOST),
        ("model-vendor-host", "api.anthropic.com"),
    ],
)
def test_the_documents_are_not_exempt_from_these(copy, plant, path, rule, text):
    plant(path, text)
    assert rule in rules_found(copy, path)


def test_a_finding_never_holds_the_matched_text(copy, plant):
    plant("src/company/planted.py", f"key = '{ANTHROPIC_KEY}'")
    [finding] = [item for item in scan(copy) if item.path == "src/company/planted.py"]
    assert ANTHROPIC_KEY not in str(finding)
    assert finding.line == 2


def test_a_file_that_is_not_text_is_still_scanned(copy, plant):
    file = copy / "src/company/planted.bin"
    file.write_bytes(b"\xff\xfe\x00" + ANTHROPIC_KEY.encode())
    try:
        assert "real-key-shape" in rules_found(copy, "src/company/planted.bin")
    finally:
        file.unlink()


def test_the_word_coverage_is_no_extra_usage_setting(copy, plant):
    plant("src/company/planted.py", "coverage = Coverage()  # COVERAGE")
    assert rules_found(copy, "src/company/planted.py") == set()


@pytest.mark.parametrize("text", [PAPER_HOST, DATA_HOST, f"https://{PAPER_HOST}/v2/account"])
def test_the_paper_module_may_name_the_paper_hosts(copy, plant, text):
    plant("src/company/paper.py", text)
    assert rules_found(copy, "src/company/paper.py") == set()


@pytest.mark.parametrize("path", ["src/company/planted.py", "README.md", "docs/design.md"])
@pytest.mark.parametrize("host", [PAPER_HOST, DATA_HOST])
def test_a_paper_host_is_not_mistaken_for_the_live_host(copy, plant, path, host):
    plant(path, host)
    assert "live-broker-host" not in rules_found(copy, path)


@pytest.mark.parametrize("path", ["src/company/paper.py", "src/company/planted.py", "docs/design.md", "README.md"])
@pytest.mark.parametrize("text", [LIVE_HOST, f"https://{LIVE_HOST}/v2/account"])
def test_the_live_host_is_caught_everywhere(copy, plant, path, text):
    plant(path, text)
    assert "live-broker-host" in rules_found(copy, path)


@pytest.mark.parametrize("path", ["src/company/paper.py", "src/company/planted.py", "docs/design.md", "README.md"])
@pytest.mark.parametrize(("rule", "text"), [("broker-key-variable", "APCA_API_KEY_ID=x"), ("real-key-shape", f"key = '{LIVE_KEY}'"), ("real-key-shape", f"key = '{PAPER_KEY}'")])
def test_a_broker_credential_is_caught_everywhere(copy, plant, path, rule, text):
    plant(path, text)
    assert rule in rules_found(copy, path)


@pytest.mark.parametrize("path", ["src/company/paper.py", *DOCUMENTS])
@pytest.mark.parametrize("text", [PAPER_HOST, DATA_HOST, "APCA-API-KEY-ID"])
def test_the_paper_module_and_the_documents_alone_may_name_how_the_broker_is_reached(copy, plant, path, text):
    plant(path, text)
    assert "paper-reach" not in rules_found(copy, path)


def test_a_url_in_the_paper_module_must_be_a_paper_host(copy, plant):
    plant("src/company/paper.py", "see https://example.com/page")
    assert rules_found(copy, "src/company/paper.py") == {"url"}


@pytest.mark.parametrize("text", [f"https://{PAPER_HOST}/v2", f"https://{DATA_HOST}/v2"])
def test_a_paper_host_url_outside_the_paper_module_is_caught(copy, plant, text):
    plant("src/company/planted.py", text)
    assert "url" in rules_found(copy, "src/company/planted.py")


def test_the_lock_file_may_hold_urls_and_nothing_else_banned(copy, plant):
    plant("uv.lock", "https://example.com/package.tar.gz")
    assert rules_found(copy, "uv.lock") == set()
    plant("uv.lock", ANTHROPIC_KEY)
    assert rules_found(copy, "uv.lock") == {"real-key-shape"}


def test_only_the_scan_itself_is_exempt(copy, plant):
    for path in ["tests/scan_rules.py", "tests/test_scan.py"]:
        plant(path, "ANTHROPIC_API_KEY")
        assert rules_found(copy, path) == set()
    plant("tests/test_something_else.py", "ANTHROPIC_API_KEY")
    assert rules_found(copy, "tests/test_something_else.py") == {"model-key-variable"}


@pytest.mark.parametrize("name", ["APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "APCA_API_BASE_URL"])
def test_no_variable_of_the_brokers_may_reach_a_session(name):
    assert banned.is_banned(name)
