"""The `company` command: a thin command line over the company's modules."""

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta

from company import reading, settings, times, treasurer, usage
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


def _treasurer_share(args) -> int:
    now = times.parse_stamp(args.now) if args.now is not None else times.now().replace(microsecond=0)
    if now is None:
        print("company: --now must be a time like 2026-11-05T09:30:00Z. Nothing was computed.", file=sys.stderr)
        return EXIT_USAGE
    ledger = Ledger()
    verification = ledger.verify()
    if not verification.ok:
        print(_broken_report(verification))
        return EXIT_REFUSED
    try:
        loaded = settings.load()
        monthly_price = settings.positive_number(loaded, "monthly_price")
        max_age = settings.positive_number(loaded, "reading_max_age_minutes")
        day_dirs = settings.day_dirs(loaded)
    except settings.SettingsRefused as refused:
        print(f"company: refused: {refused}. Nothing was computed.", file=sys.stderr)
        return EXIT_REFUSED
    try:
        records = usage.load(now - timedelta(days=7), day_dirs)
    except OSError as error:
        print(f"company: refused: the usage records cannot be read: {error}. Nothing was computed.", file=sys.stderr)
        return EXIT_REFUSED
    for warning in records.warnings():
        print(f"company: {warning}", file=sys.stderr)
    result = treasurer.share(ledger.read(), records, monthly_price, max_age, now)
    sys.stdout.write(treasurer.report(result))
    return EXIT_REFUSED if result.company_cost is None else EXIT_OK


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

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return args.run(args)
