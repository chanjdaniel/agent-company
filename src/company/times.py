"""The ledger's one form of a time: UTC, to the second, like `2026-11-05T09:30:00Z`."""

from datetime import UTC, datetime

STAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def stamp(when: datetime) -> str:
    return when.astimezone(UTC).strftime(STAMP_FORMAT)


def parse_stamp(text) -> datetime | None:
    """The time a stamp holds, or None if it is not one."""
    try:
        return datetime.strptime(text, STAMP_FORMAT).replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def now() -> datetime:
    return datetime.now(UTC)
