"""Builders for a ledger with a past: events whose `ts` is the fixture's time, and not the clock's."""

import subprocess
import sys
import uuid

from usage_records import at

from company.ledger import Ledger

# The fixtures' calendar. The newest seven-day reading resets on 18 October, so the window open at NOW opened on
# 11 October, and the four most recent complete windows open on 13, 20 and 27 September and 4 October.
NOW = "2026-10-15T12:00:00Z"
RESETS = "2026-10-18T00:00:00Z"
TAKEN = "2026-10-15T11:00:00Z"
WEEK_1 = "2026-09-13T00:00:00Z"
WEEK_2 = "2026-09-20T00:00:00Z"
WEEK_3 = "2026-09-27T00:00:00Z"
WEEK_4 = "2026-10-04T00:00:00Z"
THIS_WEEK = "2026-10-11T00:00:00Z"
MONTH_DAY = "2026-09-25T09:00:00Z"
LAST_FEW_DAYS = "2026-10-12T09:00:00Z"

# 130 x 12 / 52 is exactly 30 a week, which keeps the hand-worked sums whole.
DIGEST_SETTINGS = {
    "monthly_price": 130,
    "company_share": 0.25,
    "daily_minutes": 15,
    "minutes_table": {"templated-approval": 0.5, "message-review": 2, "message-send": 0.5, "new-public-artifact": 5},
    "portfolio": {"new_bet_token_share": 0.1, "new_bet_dollars": 0},
}


def charge_at(when: str) -> subprocess.CompletedProcess:
    """`company treasurer charge` with the report's clock at `when`: the command has no flag for it, since it writes for good."""
    code = (
        "import sys\n"
        "from company import cli, times\n"
        f"times.now = lambda: times.parse_stamp({when!r})\n"
        "sys.exit(cli.main(['treasurer', 'charge']))\n"
    )
    return subprocess.run([sys.executable, "-c", code], check=False, capture_output=True, text=True)


def ledger_at(when: str) -> Ledger:
    return Ledger(clock=lambda: at(when))


def seven_day_reading(when: str = TAKEN, used_percent=60, resets_at: str = RESETS) -> int:
    fields = {"window": "seven_day", "used_percent": used_percent, "resets_at": resets_at, "taken_at": when, "source": "hand"}
    return ledger_at(when).append("usage-reading", fields, "board")["seq"]


def money(kind: str, amount: str, when: str = MONTH_DAY, bet: str | None = None, currency: str = "USD") -> int:
    fields = {"amount": amount, "currency": currency, "source": "fixture", "record": "record-1"}
    if bet:
        fields["bet"] = bet
    return ledger_at(when).append(kind, fields, "treasurer")["seq"]


def week_charge(week_start: str, cost: str, reading_seq: int, line: str = "overhead", when: str | None = None) -> int:
    fields = {
        "week_start": week_start,
        "line": line,
        "weight": 1.0,
        "fraction": 0.1,
        "company_used": 1.0,
        "cost": cost,
        "reading_seq": reading_seq,
        "charge_id": str(uuid.uuid4()),
        "charge_lines": 1,
    }
    return ledger_at(when or week_start).append("resource-charged", fields, "treasurer")["seq"]


def event(kind: str, fields: dict, writer: str, when: str = LAST_FEW_DAYS) -> int:
    return ledger_at(when).append(kind, fields, writer)["seq"]


def ask(subject_seq: int, action: str = "templated-approval", minutes=0.5, when: str = LAST_FEW_DAYS, bet: str | None = None) -> int:
    fields = {"subject_seq": subject_seq, "action": action, "minutes": minutes, "expected_margin": "3.00"}
    if bet:
        fields["bet"] = bet
    return event("approval-asked", fields, "scheduler", when)


def decide(ask_seq: int, when: str = LAST_FEW_DAYS, decision: str = "approved") -> int:
    return event("approval-decided", {"ask_seq": ask_seq, "decision": decision}, "board", when)


def section(text: str, name: str) -> str:
    """The lines under a heading of the digest, joined; failing if the heading is not there."""
    parts = text.split(f"## {name}\n", 1)
    assert len(parts) == 2, f"no section {name} in:\n{text}"
    return parts[1].split("\n## ", 1)[0].strip()
