"""The `company` command: a thin command line over the company's modules."""

import argparse
import json
import sys

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

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return args.run(args)
