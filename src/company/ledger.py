"""The company's one append-only ledger: a JSON Lines file, hash-chained and checked against the contract.

Each line holds `seq`, `ts`, `kind`, `writer`, the kind's fields and `prev`, the hash of the line before.
A hash chain alone cannot see lines removed from its end, so a head record beside the ledger holds the
last line's `seq` and hash; it may lag the ledger by one line, after a crash between the two writes.
The chain and the head find an edit made by hand; they cannot find someone rewriting the whole ledger and
the head together, which the session rules keep agents from doing.
"""

import contextlib
import fcntl
import hashlib
import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from company import paths, times
from company.contract import Contract


class AppendRefused(Exception):
    """An append failed the contract. Nothing was appended, and event `refusal_seq` records why."""

    def __init__(self, kind: str, writer: str, reason: str, refusal_seq: int):
        self.kind = kind
        self.writer = writer
        self.reason = reason
        self.refusal_seq = refusal_seq
        super().__init__(
            f"append of kind {kind} as writer {writer} ({reason}). "
            f"Nothing was appended; event {refusal_seq} in the ledger records the refusal."
        )


class LedgerBroken(Exception):
    """The ledger's end or a line in it is not what the ledger wrote, so nothing more can chain from it."""


@dataclass(frozen=True)
class Verification:
    """What `verify` found: `problems` names each line, and never a line's values."""

    events: int
    problems: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.problems


@dataclass(frozen=True)
class _Tail:
    seq: int
    hash: str | None


def _hash(line: bytes) -> str:
    return hashlib.sha256(line).hexdigest()


class Ledger:
    """The ledger in a company home; `home` defaults to the current one."""

    def __init__(self, home: Path | None = None, contract: Contract | None = None):
        self.home = home or paths.home()
        self.path = self.home / "ledger.jsonl"
        self._head_path = self.home / "ledger.head"
        self._lock_path = self.home / "ledger.lock"
        self.contract = contract or Contract.load()

    def append(self, kind: str, fields: dict, writer: str) -> dict:
        """Add one event and return it; raise `AppendRefused`, after logging it, if the contract says no."""
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self._locked(fcntl.LOCK_EX):
            tail = self._tail()
            reason = self.contract.refusal(kind, fields, writer, tail.seq + 1)
            if reason is None:
                return self._write(kind, fields, writer, tail)
            refusal = self._write(
                "append-refused",
                {
                    "attempted_kind": self.contract.safe_label(kind),
                    "attempted_writer": self.contract.safe_label(writer),
                    "reason": reason,
                },
                self.contract.refusal_writer(writer),
                tail,
            )
            raise AppendRefused(
                self.contract.safe_label(kind), self.contract.safe_label(writer), reason, refusal["seq"]
            )

    def read(self) -> list[dict]:
        """Every event, oldest first, with no check of the chain; raise `LedgerBroken` on a line that is no event."""
        with self._locked(fcntl.LOCK_SH):
            lines = self._lines()
        events = []
        for number, line in enumerate(lines, start=1):
            event = _parse(line)
            if event is None:
                raise LedgerBroken(f"line {number} is not an event")
            events.append(event)
        return events

    def verify(self) -> Verification:
        """Walk the whole chain and the head record, and name everything wrong with them."""
        with self._locked(fcntl.LOCK_SH):
            lines = self._lines()
            problems = _chain_problems(lines) + self._head_problems(lines)
            if self._torn():
                problems.append(f"line {len(lines)} is cut short: it has no end of line")
        return Verification(len(lines), tuple(problems))

    @contextlib.contextmanager
    def _locked(self, mode: int) -> Iterator[None]:
        """Hold the ledger's lock; a home that does not exist yet has nothing to lock or read."""
        if not self.home.exists():
            yield
            return
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, mode)
            yield
        finally:
            os.close(fd)

    def _lines(self) -> list[bytes]:
        try:
            return self.path.read_bytes().splitlines()
        except FileNotFoundError:
            return []

    def _torn(self) -> bool:
        try:
            with self.path.open("rb") as file:
                file.seek(-1, os.SEEK_END)
                return file.read(1) != b"\n"
        except (FileNotFoundError, OSError):
            return False

    def _read_head(self) -> _Tail | None:
        """The head record, or None if there is none; a record that makes no sense raises `LedgerBroken`."""
        try:
            head = json.loads(self._head_path.read_bytes())
            return _Tail(int(head["seq"]), head["hash"])
        except FileNotFoundError:
            return None
        except (ValueError, KeyError, TypeError) as error:
            raise LedgerBroken("the head record beside the ledger is not readable") from error

    def _head_problems(self, lines: list[bytes]) -> list[str]:
        try:
            head = self._read_head()
        except LedgerBroken as error:
            return [str(error)]
        if head is None:
            return ["the head record beside the ledger is missing"] if lines else []
        if head.seq == len(lines):
            matches = head.seq == 0 or _hash(lines[-1]) == head.hash
        elif head.seq == len(lines) - 1:
            # A crash between writing a line and writing the head leaves the head one line behind.
            matches = head.seq == 0 or _hash(lines[head.seq - 1]) == head.hash
        else:
            matches = False
        if matches:
            return []
        return ["the head record does not match the ledger's end: its last line was edited, or lines were removed"]

    def _tail(self) -> _Tail:
        """The end of the ledger to chain from, checked against the head so that a cut end is not papered over."""
        head = self._read_head()
        last = self._last_line()
        if last is None:
            if head is not None and head.seq != 0:
                raise LedgerBroken("the ledger has lost its lines: the head record says it held some")
            return _Tail(0, None)
        event = _parse(last)
        if event is None or not last.endswith(b"\n"):
            raise LedgerBroken("the ledger's last line is not a whole event")
        line = last.rstrip(b"\n")
        seq = event.get("seq")
        tail = _Tail(seq, _hash(line)) if isinstance(seq, int) else None
        if tail is None or head is None or not (tail == head or tail.seq == head.seq + 1):
            raise LedgerBroken("the ledger's end does not match its head record")
        return tail

    def _last_line(self) -> bytes | None:
        """The last line with its end of line, read from the end so that an append stays cheap."""
        try:
            file = self.path.open("rb")
        except FileNotFoundError:
            return None
        with file:
            file.seek(0, os.SEEK_END)
            position = file.tell()
            data = b""
            while position > 0 and data.count(b"\n", 0, max(len(data) - 1, 0)) == 0:
                step = min(65536, position)
                position -= step
                file.seek(position)
                data = file.read(step) + data
        if not data:
            return None
        return data.rsplit(b"\n", 2)[-2] + b"\n" if data.endswith(b"\n") else data.rsplit(b"\n", 1)[-1]

    def _write(self, kind: str, fields: dict, writer: str, tail: _Tail) -> dict:
        event = {"seq": tail.seq + 1, "ts": times.stamp(times.now()), "kind": kind, "writer": writer, **fields, "prev": tail.hash}
        line = json.dumps(event, separators=(",", ":"), allow_nan=False).encode()
        if not self._head_path.exists():
            self._write_head(_Tail(0, None))
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            remaining = memoryview(line + b"\n")
            while remaining:
                remaining = remaining[os.write(fd, remaining) :]
            os.fsync(fd)
        finally:
            os.close(fd)
        self._write_head(_Tail(event["seq"], _hash(line)))
        return event

    def _write_head(self, head: _Tail) -> None:
        temporary = self._head_path.with_suffix(".head.tmp")
        temporary.write_text(json.dumps({"seq": head.seq, "hash": head.hash}))
        temporary.replace(self._head_path)


def _parse(line: bytes) -> dict | None:
    """The event on a line, or None if the line is not a JSON object."""
    try:
        event = json.loads(line)
    except ValueError:
        return None
    return event if isinstance(event, dict) else None


def _chain_problems(lines: list[bytes]) -> list[str]:
    problems = []
    previous = None
    for number, line in enumerate(lines, start=1):
        event = _parse(line)
        if event is None:
            problems.append(f"line {number} is not an event: it was edited or cut short")
        else:
            if event.get("seq") != number:
                problems.append(f"line {number} has the wrong seq: a line was removed, added or moved")
            if event.get("prev") != previous:
                if number == 1:
                    problems.append("line 1 does not start the chain: a line before it was removed")
                else:
                    problems.append(
                        f"line {number} does not chain from line {number - 1}: "
                        f"line {number - 1} was edited, or a line was removed, added or moved"
                    )
        previous = _hash(line)
    return problems
