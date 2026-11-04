"""The `company` command: a thin command line over the company's modules."""

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime, timedelta

from company import digest, reading, settings, times, treasurer, usage
from company.ledger import AppendRefused, Ledger, LedgerBroken

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2


def _ledger_append(args) -> int:
    try:
        fields = json.loads(args.fields)
    except ValueError:
        print("company: --fields is not JSON. Nothing was appended.", file=sys.stderr)
        return EXIT_USAGE
    try:
        event = Ledger().append(args.kind, fields, args.writer)
    except AppendRefused as refused:
        print(f"company: refused: {refused}", file=sys.stderr)
        return EXIT_REFUSED
    except LedgerBroken as broken:
        print(f"company: refused: {broken}. Nothing was appended; see `company ledger verify`.", file=sys.stderr)
        return EXIT_REFUSED
    print(json.dumps(event, separators=(",", ":")))
    return EXIT_OK


def _broken_report(verification) -> str:
    return "\n".join(["LEDGER BROKEN:", *verification.problems])


def _ledger_show(args) -> int:
    ledger = Ledger()
    verification = ledger.verify()
    if ledger.path.exists():
        sys.stdout.write(ledger.path.read_text(errors="replace"))
    if not verification.ok:
        print(_broken_report(verification), file=sys.stderr)
        return EXIT_REFUSED
    return EXIT_OK


def _ledger_verify(args) -> int:
    verification = Ledger().verify()
    if not verification.ok:
        print(_broken_report(verification))
        return EXIT_REFUSED
    print(f"The ledger is whole: {verification.events} events.")
    return EXIT_OK


def _reading_record(args) -> int:
    resets_at = _aware_time(args.resets_at)
    if resets_at is None:
        print(
            "company: --resets-at must be a time with its zone, like 2026-11-05T09:30:00Z. Nothing was recorded.",
            file=sys.stderr,
        )
        return EXIT_USAGE
    try:
        event = reading.record(args.window, args.used_percent, resets_at)
    except ValueError as wrong:
        print(f"company: this reading cannot be true: {wrong}. Nothing was recorded.", file=sys.stderr)
        return EXIT_USAGE
    except (AppendRefused, LedgerBroken) as refused:
        print(f"company: refused: {refused}. Nothing was recorded; see `company ledger verify`.", file=sys.stderr)
        return EXIT_REFUSED
    print(f"Recorded event {event['seq']}: {args.window} {args.used_percent}% used, resets {event['resets_at']}.")
    return EXIT_OK


def _aware_time(text: str) -> datetime | None:
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    return when.astimezone(UTC) if when.tzinfo is not None else None


def _reading_statusline(args) -> int:
    print(reading.keep_statusline(sys.stdin.buffer.read().decode("utf-8", "replace")))
    return EXIT_OK


def _report_time(text: str | None) -> datetime | None:
    """The time a report is as of: `--now`, or the real time; None if `--now` is not a time."""
    return times.parse_stamp(text) if text is not None else times.now().replace(microsecond=0)


def _bad_now() -> int:
    print("company: --now must be a time like 2026-11-05T09:30:00Z. Nothing was computed.", file=sys.stderr)
    return EXIT_USAGE


def _is_broken(ledger: Ledger) -> bool:
    """Whether the chain is broken, having said so."""
    verification = ledger.verify()
    if not verification.ok:
        print(_broken_report(verification))
    return not verification.ok


def _share_at(events: list[dict], loaded: dict, now: datetime) -> treasurer.Share:
    """The share as these events and the usage records stand; raises `SettingsRefused`, or `OSError` on unreadable records."""
    monthly_price = settings.positive_number(loaded, "monthly_price")
    max_age = settings.positive_number(loaded, "reading_max_age_minutes")
    records = usage.load(now - timedelta(days=7), settings.day_dirs(loaded))
    for warning in records.warnings():
        print(f"company: {warning}", file=sys.stderr)
    return treasurer.share(events, records, monthly_price, max_age, now)


def _treasurer_share(args) -> int:
    now = _report_time(args.now)
    if now is None:
        return _bad_now()
    ledger = Ledger()
    if _is_broken(ledger):
        return EXIT_REFUSED
    try:
        result = _share_at(ledger.read(), settings.load(), now)
    except settings.SettingsRefused as refused:
        print(f"company: refused: {refused}. Nothing was computed.", file=sys.stderr)
        return EXIT_REFUSED
    except OSError as error:
        print(f"company: refused: the usage records cannot be read: {error}. Nothing was computed.", file=sys.stderr)
        return EXIT_REFUSED
    sys.stdout.write(treasurer.report(result))
    return EXIT_REFUSED if result.company_cost is None else EXIT_OK


def _treasurer_charge(args) -> int:
    now = times.now().replace(microsecond=0)
    ledger = Ledger()
    if _is_broken(ledger):
        return EXIT_REFUSED
    events = ledger.read()
    try:
        loaded = settings.load()
        due = treasurer.minutes_due(events, settings.minutes_table(loaded))
        result = _share_at(events, loaded, now)
    except settings.SettingsRefused as refused:
        print(f"company: refused: {refused}. Nothing was charged.", file=sys.stderr)
        return EXIT_REFUSED
    except OSError as error:
        print(f"company: refused: the usage records cannot be read: {error}. Nothing was charged.", file=sys.stderr)
        return EXIT_REFUSED
    lines = treasurer.week_charges_due(result, events)
    try:
        for fields in due.charges:
            ledger.append("minutes-charged", fields, "treasurer")
        # Lines go in one at a time, so each says which charge it is part of, and only a whole charge is read.
        charge_id = str(uuid.uuid4())
        for fields in lines:
            ledger.append("resource-charged", {**fields, "charge_id": charge_id, "charge_lines": len(lines)}, "treasurer")
    except (AppendRefused, LedgerBroken) as refused:
        print(
            f"company: refused: {refused}. The charge stopped there: the minutes it wrote stand, and part of a week's charge counts for nothing; "
            "run it again once `company ledger verify` is clean, since it charges only what is still owed.",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    print(f"Charged: decisions in Daniel-minutes, {len(due.charges)}; lines of the week's share, {len(lines)}.")
    for problem in due.problems:
        print(f"company: {problem}.", file=sys.stderr)
    week = result.seven_day
    if isinstance(week, reading.Unreadable):
        print(
            f"company: the week was not charged: {week.reason}: {week.detail}. Fix: `{reading.FIX}`.",
            file=sys.stderr,
        )
    return EXIT_REFUSED if due.problems or isinstance(week, reading.Unreadable) else EXIT_OK


def _minutes_correct(args) -> int:
    ledger = Ledger()
    if _is_broken(ledger):
        return EXIT_REFUSED
    charges = {event["seq"] for event in ledger.read() if event["kind"] == "minutes-charged"}
    if args.charge not in charges:
        refusal = {"attempted_kind": "minutes-corrected", "attempted_writer": "board", "reason": "not-a-charge"}
        logged = ledger.append("append-refused", refusal, "treasurer")
        print(
            f"company: event {args.charge} is not a minutes charge. Nothing was recorded; "
            f"event {logged['seq']} in the ledger records the refusal.",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    fields = {"charge_seq": args.charge, "minutes": args.minutes}
    if args.reason is not None:
        fields["reason"] = args.reason
    try:
        event = ledger.append("minutes-corrected", fields, "board")
    except AppendRefused as refused:
        print(f"company: refused: {refused}", file=sys.stderr)
        return EXIT_REFUSED
    except LedgerBroken as broken:
        print(f"company: refused: {broken}. Nothing was recorded; see `company ledger verify`.", file=sys.stderr)
        return EXIT_REFUSED
    print(f"Recorded event {event['seq']}: charge {args.charge} is now {digest.minutes_phrase(args.minutes)}.")
    return EXIT_OK


def _digest(args) -> int:
    now = _report_time(args.now)
    if now is None:
        return _bad_now()
    ledger = Ledger()
    if not ledger.verify().ok:
        sys.stdout.write(digest.broken())
        return EXIT_REFUSED
    events = ledger.read()
    if not events:
        sys.stdout.write(digest.empty(now))
        return EXIT_OK
    result: treasurer.Share | str
    try:
        loaded = settings.load()
        terms = treasurer.Terms.from_settings(loaded)
        result = _share_at(events, loaded, now)
    except settings.SettingsRefused as refused:
        print(f"company: refused: {refused}. Nothing was computed.", file=sys.stderr)
        return EXIT_REFUSED
    except OSError as error:
        result = f"the usage records cannot be read: {error}"
    sys.stdout.write(digest.page(events, result, terms, now))
    return EXIT_OK


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="company", description="Run the company.")
    commands = parser.add_subparsers(dest="command", required=True)

    ledger = commands.add_parser("ledger", help="Read and append to the append-only ledger.")
    actions = ledger.add_subparsers(dest="action", required=True)

    append = actions.add_parser("append", help="Append one event, checked against the contract.")
    append.add_argument("kind")
    append.add_argument("--writer", required=True)
    append.add_argument("--fields", default="{}", help="The event's fields, as a JSON object.")
    append.set_defaults(run=_ledger_append)

    show = actions.add_parser("show", help="Print every event, and report a broken chain.")
    show.set_defaults(run=_ledger_show)

    verify = actions.add_parser("verify", help="Check the hash chain; exit 1 and name the lines if it is broken.")
    verify.set_defaults(run=_ledger_verify)

    readings = commands.add_parser("reading", help="Keep a reading of the account's window use.")
    actions = readings.add_subparsers(dest="action", required=True)

    record = actions.add_parser("record", help="Keep a reading from the usage page, as Daniel's.")
    record.add_argument("--window", required=True, choices=sorted(reading.WINDOWS))
    record.add_argument("--used-percent", required=True, type=float)
    record.add_argument("--resets-at", required=True, help="When the window resets, with its zone.")
    record.set_defaults(run=_reading_record)

    statusline = actions.add_parser(
        "statusline", help="As Claude Code's status line command: keep the readings in its input, and print a short text."
    )
    statusline.set_defaults(run=_reading_statusline)

    treasury = commands.add_parser("treasurer", help="The Treasurer's numbers.")
    actions = treasury.add_subparsers(dest="action", required=True)

    share = actions.add_parser("share", help="The company's share of each window, the week's cost and each bet's cost.")
    share.add_argument("--now", help="Report as if it were this UTC time, to check a report's arithmetic.")
    share.set_defaults(run=_treasurer_share)

    charge = actions.add_parser(
        "charge", help="Charge what is owed: each decision's Daniel-minutes, and the open window's share, line by line."
    )
    charge.set_defaults(run=_treasurer_charge)

    minutes = commands.add_parser("minutes", help="Daniel's own word on the minutes charged.")
    actions = minutes.add_subparsers(dest="action", required=True)

    correct = actions.add_parser("correct", help="Replace a charge's minutes in every total.")
    correct.add_argument("--charge", required=True, type=int, help="The seq of the `minutes-charged` event.")
    correct.add_argument("--minutes", required=True, type=float)
    correct.add_argument("--reason")
    correct.set_defaults(run=_minutes_correct)

    report = commands.add_parser("digest", help="The one page Daniel reads each week. It writes nothing.")
    report.add_argument("--now", help="Report as if it were this UTC time, to check a report's arithmetic.")
    report.set_defaults(run=_digest)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return args.run(args)
