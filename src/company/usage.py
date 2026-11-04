"""What the account has used: every reply in Claude Code's transcripts and the team's day files, weighed at list prices.

A reply is one line per request id, wherever it appears, in a forked session's copy or a day file: it takes each
count's largest value, since an early line can hold a partial output, and the rest from its earliest line.
The weight is an apportioning key between sessions, and never a cost.
"""

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from fractions import Fraction
from importlib import resources
from pathlib import Path

from company import paths

COUNTS = ("input", "cache_write_1h", "cache_write_5m", "cache_read", "output")
_DAY_FILE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\.jsonl")
_PER_TOKENS = 1_000_000


def _count(value) -> int:
    return max(value, 0) if isinstance(value, int) and not isinstance(value, bool) else 0


def _time(text) -> datetime | None:
    """A reply's time, which must say its zone; a line whose time cannot be read is no reply."""
    if not isinstance(text, str):
        return None
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    return when if when.tzinfo is not None else None


@dataclass(frozen=True)
class Prices:
    """The list-price table, held exactly, so that a sum of weights does not depend on the order of its replies."""

    models: dict
    dearest: str

    @classmethod
    def load(cls) -> "Prices":
        text = resources.files("company").joinpath("prices.json").read_text()
        models = json.loads(text, parse_float=Fraction)["models"]
        return cls(models, max(models, key=lambda model: sum(models[model][count] for count in COUNTS)))

    def weigh(self, model: str, counts: dict) -> Fraction:
        prices = self.models.get(model, self.models[self.dearest])
        above = prices.get("above")
        prompt = counts["input"] + counts["cache_write_1h"] + counts["cache_write_5m"] + counts["cache_read"]
        if above and prompt > above["tokens"]:
            prices = above
        return sum((Fraction(counts[count]) * prices[count] for count in COUNTS), Fraction(0)) / _PER_TOKENS


@dataclass(frozen=True)
class WeighedReply:
    at: datetime
    session: str
    weight: Fraction


@dataclass(frozen=True)
class Records:
    """The replies that were read, and the models among them with no price, and so weighed at `dearest`."""

    replies: tuple[WeighedReply, ...]
    unpriced: frozenset[str]
    dearest: str

    def weights(self, start: datetime, end: datetime) -> dict[str, Fraction]:
        """Each session's weight in the replies after `start` and up to `end`, so that two spans add up."""
        found: dict[str, Fraction] = {}
        for reply in self.replies:
            if start < reply.at <= end:
                found[reply.session] = found.get(reply.session, Fraction(0)) + reply.weight
        return found

    def warnings(self) -> list[str]:
        return [
            f"warning: the price table has no model {model!r}, so it is weighed at the prices of {self.dearest}"
            for model in sorted(self.unpriced)
        ]


def load(since: datetime, day_dirs=()) -> Records:
    """Read the records that can hold a reply after `since`; a file that cannot be read raises."""
    found: dict[str, dict] = {}
    for row in _transcript_rows(paths.claude_projects(), since):
        _add(found, row)
    for directory in day_dirs:
        for row in _day_rows(Path(directory), since):
            _add(found, row)
    prices = Prices.load()
    replies = tuple(WeighedReply(row["at"], row["session"], prices.weigh(row["model"], row)) for row in found.values())
    unpriced = frozenset(row["model"] for row in found.values() if row["model"] not in prices.models)
    return Records(replies, unpriced, prices.dearest)


def _add(found: dict, row: dict) -> None:
    old = found.get(row["request"])
    if old is None:
        found[row["request"]] = row
        return
    first, other = sorted((old, row), key=lambda each: (each["at"], each["session"]))
    found[row["request"]] = {**first, **{count: max(first[count], other[count]) for count in COUNTS}}


def _lines(path: Path, since: datetime):
    """A file's lines, skipping one whose last change came before `since`, or that has gone since it was listed."""
    try:
        if path.stat().st_mtime < since.timestamp():
            return
        with path.open(encoding="utf-8", errors="replace") as file:
            yield from file
    except FileNotFoundError:
        return


def _transcript_rows(projects: Path, since: datetime):
    for path in sorted(projects.glob("*/*.jsonl")):
        for line in _lines(path, since):
            row = _transcript_row(line, None)
            if row:
                yield row
    for path in sorted(projects.glob("*/*/subagents/*.jsonl")):
        for line in _lines(path, since):
            row = _transcript_row(line, path.parent.parent.name)
            if row:
                yield row


def _transcript_row(line: str, parent: str | None) -> dict | None:
    """One reply from a transcript's line, or None for any other line; `parent` is set for a subagent's transcript."""
    # Most lines are no reply, so skip them before parsing.
    if '"assistant"' not in line:
        return None
    try:
        entry = json.loads(line)
    except ValueError:
        return None
    if not isinstance(entry, dict) or entry.get("type") != "assistant":
        return None
    message = entry.get("message")
    if not isinstance(message, dict):
        return None
    request, session, at = entry.get("requestId"), parent or entry.get("sessionId"), _time(entry.get("timestamp"))
    if not _text(request) or not _text(session) or at is None:
        return None
    usage = message.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    write = _count(usage.get("cache_creation_input_tokens"))
    lifetimes = usage.get("cache_creation")
    if isinstance(lifetimes, dict):
        write_1h = _count(lifetimes.get("ephemeral_1h_input_tokens"))
        write_5m = _count(lifetimes.get("ephemeral_5m_input_tokens"))
    elif parent or entry.get("isSidechain"):
        write_1h, write_5m = 0, write
    else:
        write_1h, write_5m = write, 0
    return {
        "request": request,
        "at": at,
        "session": session,
        "model": message.get("model") if isinstance(message.get("model"), str) else "",
        "input": _count(usage.get("input_tokens")),
        "cache_write_1h": write_1h,
        "cache_write_5m": write_5m,
        "cache_read": _count(usage.get("cache_read_input_tokens")),
        "output": _count(usage.get("output_tokens")),
    }


def _text(value) -> bool:
    return isinstance(value, str) and bool(value)


def _day_rows(usage_dir: Path, since: datetime):
    """The replies in a team `usage/` directory's `<machine>/<day>.jsonl` files, from the day of `since` on."""
    first_day = since.astimezone(UTC).strftime("%Y-%m-%d")
    for path in sorted(usage_dir.glob("*/*.jsonl")):
        if not _DAY_FILE.fullmatch(path.name) or path.stem < first_day:
            continue
        with path.open(encoding="utf-8", errors="replace") as file:
            for line in file:
                row = _day_row(line)
                if row:
                    yield row


def _day_row(line: str) -> dict | None:
    try:
        entry = json.loads(line)
    except ValueError:
        return None
    if not isinstance(entry, dict):
        return None
    request, session, at = entry.get("request"), entry.get("session"), _time(entry.get("ts"))
    if not _text(request) or not _text(session) or at is None:
        return None
    model = entry.get("model")
    return {
        "request": request,
        "at": at,
        "session": session,
        "model": model if isinstance(model, str) else "",
        **{count: _count(entry.get(count)) for count in COUNTS},
    }
