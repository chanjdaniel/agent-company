"""What no tracked file may hold: the rule "no model API key, no model API, and no outside host but the paper broker's".

This file, `test_scan.py` and the package's `banned.py` are the only files exempt from every rule, since they must name what they ban.
A finding names the file, line and rule, and never the matched text, since that may be a real key.
"""

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from company import banned

# These must name the banned settings to explain the rule, so a few rules do not apply to them.
DOCUMENTS = ("docs/design.md", "docs/first-run.md", "docs/research/")
PAPER_MODULE = "src/company/paper.py"
PAPER_HOSTS = ("paper-api.alpaca.markets", "data.alpaca.markets")
LIVE_BROKER_HOST = "api.alpaca.markets"
SCAN_FILES = ("tests/scan_rules.py", "tests/test_scan.py", "src/company/banned.py")


def _is_document(path):
    return path.startswith(DOCUMENTS[2]) or path in DOCUMENTS[:2]


def _never(path):
    return False


def _url_allowed(path):
    # A lock file records where each package came from; the paper module is checked by _paper_urls.
    return _is_document(path) or path == "uv.lock" or path == PAPER_MODULE


def _paper_reach_allowed(path):
    return _is_document(path) or path == PAPER_MODULE


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern
    exempt: object = _never


SDKS = (
    r"anthropic|openai|claude_agent_sdk|claude_code_sdk|google\.generativeai|google\.genai|mistralai|cohere"
    r"|litellm|langchain\w*|groq"
)
URL = re.compile(r"\b(?:https?|wss?|ftp)://[^\s\"'<>)\]]+", re.IGNORECASE)

RULES = (
    Rule("model-key-variable", banned.MODEL_KEY_VARIABLE, _is_document),
    Rule(
        "model-vendor-host",
        re.compile(
            r"(?<![\w.-])(?:"
            r"api\.anthropic\.com|console\.anthropic\.com|claude\.ai/api"
            r"|api\.openai\.com|generativelanguage\.googleapis\.com|aiplatform\.googleapis\.com"
            r"|bedrock-runtime\.[\w.-]+\.amazonaws\.com|[\w-]+\.openai\.azure\.com"
            r"|api\.mistral\.ai|api\.cohere\.(?:com|ai)|openrouter\.ai|api\.groq\.com|api\.x\.ai"
            r"|api\.deepseek\.com|api\.together\.xyz"
            r")",
            re.IGNORECASE,
        ),
    ),
    Rule(
        "model-sdk",
        re.compile(
            rf"^\s*(?:import|from)\s+(?:{SDKS})\b"
            rf"|^\s*from\s+google\s+import\s+(?:genai|generativeai)\b"
            rf'|^name = "(?:{SDKS})"'
            rf"|^\s*[\"'](?:{SDKS})[\"'<>=~! ]"
            r"|@anthropic-ai/",
            re.MULTILINE,
        ),
    ),
    # Any other name of the broker's: only the two hosts have a reason to be named, and the documents cite its documentation's.
    Rule("other-broker-host", re.compile(r"(?<![\w.-])(?!(?:paper-api|data|docs)\.alpaca\.markets)[\w.-]*alpaca\.markets", re.IGNORECASE)),
    Rule("broker-key-variable", banned.BROKER_KEY_VARIABLE),
    Rule("paper-reach", re.compile(r"(?<![\w.-])(?:paper-api|data)\.alpaca\.markets|APCA-API-", re.IGNORECASE), _paper_reach_allowed),
    Rule("api-key-helper", re.compile(r"apiKeyHelper"), _is_document),
    Rule("bare-mode", re.compile(r"(?<![\w-])--bare\b"), _is_document),
    Rule(
        "extra-usage-setting",
        re.compile(r"(?i:extra[_-]?usage)|(?<![a-zA-Z])(?:[Oo]verage|OVERAGE)|[a-z]Overage"),
        _is_document,
    ),
    # On a boundary, since the paper host's name holds the live host's.
    Rule("live-broker-host", re.compile(r"(?<![\w.-])api\.alpaca\.markets", re.IGNORECASE)),
    Rule(
        "real-key-shape",
        re.compile(
            r"\bsk-ant-[\w-]{8,}"
            r"|\bsk-(?:proj-)?[A-Za-z0-9]{20,}"
            r"|\bAIza[\w-]{30,}"
            r"|\bgh[pousr]_[A-Za-z0-9]{20,}"
            r"|\bgithub_pat_\w{20,}"
            r"|\bxox[abprs]-[\w-]{10,}"
            r"|\bAKIA[0-9A-Z]{16}\b"
            r"|\b[PA]K[0-9A-Z]{18}\b"
            r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
        ),
    ),
    Rule("url", URL, _url_allowed),
)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str

    def __str__(self):
        return f"{self.path}:{self.line}: {self.rule}"


def tracked_files(root):
    """Every file git tracks or would track: a new file is caught before it is ever added."""
    env = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return sorted(path for path in listed.stdout.split("\0") if path)


def _paper_urls(path, text):
    """The paper module is the one place with a URL, and only to the paper broker's two hosts."""
    if path != PAPER_MODULE:
        return
    for match in URL.finditer(text):
        host = re.sub(r"^[^/]*//", "", match.group()).split("/")[0].split(":")[0].lower()
        if host not in PAPER_HOSTS:
            yield Finding(path, text.count("\n", 0, match.start()) + 1, "url")


def scan_text(path, text):
    """The findings in one file's text, whose path decides which rules apply."""
    if path in SCAN_FILES:
        return []
    found = []
    for rule in RULES:
        if rule.exempt(path):
            continue
        for match in rule.pattern.finditer(text):
            found.append(Finding(path, text.count("\n", 0, match.start()) + 1, rule.name))
    found.extend(_paper_urls(path, text))
    return found


def scan(root):
    """Every finding in the repository at `root`."""
    found = []
    for path in tracked_files(root):
        file = Path(root) / path
        if file.is_file():
            found.extend(scan_text(path, file.read_bytes().decode("utf-8", "replace")))
    return found
