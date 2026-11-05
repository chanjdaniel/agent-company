"""The `company` command: a thin command line over the company's modules."""

import argparse
import contextlib
import json
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta

from company import (
    contract,
    digest,
    governor,
    killswitch,
    launcher,
    reading,
    schedule,
    settings,
    times,
    treasurer,
    usage,
)
from company.ledger import AppendRefused, Ledger, LedgerBroken

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2


def _refused_inside_a_session(ledger: Ledger, kind: str, writer: str) -> bool:
    """Refuse and log an append made in a session, whose agent must reach the ledger only through its company tools."""
    session = os.environ.get(launcher.SESSION_VARIABLE)
    if session is None:
        return False
    context = {"tool": "ledger-append", **({"session": session} if contract.UUID.fullmatch(session) else {})}
    with contextlib.suppress(LedgerBroken, OSError):
        ledger.refuse(kind, writer, "inside-a-session", context)
    print("company: refused: an agent reaches the ledger only through its company tools. Nothing was appended.", file=sys.stderr)
    return True


def _ledger_append(args) -> int:
    if _refused_inside_a_session(Ledger(), args.kind, args.writer):
        return EXIT_REFUSED
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
        loaded = settings.load(log_tamper=False)
        terms = treasurer.Terms.from_settings(loaded)
        result = _share_at(events, loaded, now)
    except settings.SettingsRefused as refused:
        print(f"company: refused: {refused}. Nothing was computed.", file=sys.stderr)
        return EXIT_REFUSED
    except OSError as error:
        result = f"the usage records cannot be read: {error}"
    sys.stdout.write(digest.page(events, result, terms, now))
    return EXIT_OK


def _settings_change(change) -> int:
    """Make a change to the settings by Daniel's command, on a ledger that verifies; `change` returns its event."""
    if _is_broken(Ledger()):
        return EXIT_REFUSED
    try:
        event = change()
    except settings.SettingsRefused as refused:
        # A bad value's fix is the same command with a good one, so only the other refusals name theirs.
        fix = "" if refused.fix == settings.SET else f" Fix: `{refused.fix}`."
        print(f"company: refused: {refused}. Nothing was changed.{fix}", file=sys.stderr)
        return EXIT_REFUSED
    except (AppendRefused, LedgerBroken) as refused:
        print(f"company: refused: {refused}. Nothing was changed.", file=sys.stderr)
        return EXIT_REFUSED
    print(f"Recorded event {event['seq']}: changed {', '.join(event['keys'])}; the new digest is {event['digest']}.")
    return EXIT_OK


def _settings_init(args) -> int:
    given = {key: settings.parse(getattr(args, key)) for key in _INIT_FLAGS if getattr(args, key) is not None}
    return _settings_change(lambda: settings.init(given, args.message))


def _settings_set(args) -> int:
    return _settings_change(lambda: settings.set_value(args.key, args.value, args.message))


def _launches(count: int) -> str:
    return f"{count} real launch" if count == 1 else f"{count} real launches"


def _go(args) -> int:
    ledger = Ledger()
    if _is_broken(ledger):
        return EXIT_REFUSED
    fields = {"scope": governor.GO_SCOPE, "message": args.message, "sessions": args.sessions}
    try:
        event = ledger.append("go-given", fields, "board")
    except (AppendRefused, LedgerBroken) as refused:
        print(f"company: refused: {refused}. No launch was granted.", file=sys.stderr)
        return EXIT_REFUSED
    print(f"Recorded event {event['seq']}: a go for {_launches(args.sessions)}, on message {args.message}.")
    return EXIT_OK


def _print_refusal(answer: governor.Refused) -> None:
    print(f"Refused at the {answer.check} check: {answer.reason}.")
    print(f"Fix: {answer.fix}.")
    if answer.seq is None:
        print("This refusal could not be logged: see `company ledger verify`.")
    else:
        print(f"Event {answer.seq} in the ledger records this refusal.")


def _session_start(args) -> int:
    answer = launcher.start(args.role, args.bet, args.prompt or "", args.workspace, args.scheduled)
    if isinstance(answer, governor.Refused):
        _print_refusal(answer)
        return EXIT_REFUSED
    how = f"stopped ({answer.stopped})" if answer.stopped else "ended"
    print(f"Session {answer.session} {how}: exit {answer.exit}, weight {answer.weight:.6f}, run {answer.run}.")
    if answer.unlogged:
        print(f"company: {answer.unlogged}.", file=sys.stderr)
    return EXIT_OK if answer.exit == 0 and not answer.stopped and not answer.unlogged else EXIT_REFUSED


def _governor_check(args) -> int:
    answer = governor.admit(args.role, args.bet, args.scheduled)
    if isinstance(answer, governor.Refused):
        _print_refusal(answer)
        return EXIT_REFUSED
    if answer.launches_left is None:
        print(f"Admitted: {args.role}, on the schedule, which uses no word.")
    else:
        print(f"Admitted: {args.role}, on {answer.gate}, with {_launches(answer.launches_left)} left on that word.")
    shown = {window.reading.window: window for window in answer.windows}
    for name in reading.WINDOWS:
        window = shown.get(name)
        if window is None:
            print(f"{name}: no reading")
            continue
        print(
            f"{name}: account used {float(window.reading.used_percent):.2f}%, "
            f"company used {float(window.company_used):.2f}%, from event {window.reading.seq}"
        )
    return EXIT_OK


def _kill_self_test() -> int:
    checks = killswitch.self_test()
    for check in checks:
        print(f"{'passed' if check.passed else 'FAILED'}: {check.name}" + (f": {check.detail}" if check.detail and not check.passed else ""))
    return EXIT_OK if all(check.passed for check in checks) else EXIT_REFUSED


def _kill(args) -> int:
    if args.self_test:
        return _kill_self_test()
    try:
        pulled = killswitch.pull("daniel", args.reason)
    except killswitch.PullRefused as refused:
        print(f"company: refused: {refused}.", file=sys.stderr)
        return EXIT_REFUSED
    print(f"The kill switch is pulled: {args.reason}.")
    for step in pulled.steps:
        print(f"{step.step} {step.target}: {step.result}" + (f" ({step.detail})" if step.detail else ""))
    if pulled.unlogged:
        print(f"company: {pulled.unlogged}.", file=sys.stderr)
    if pulled.unkept:
        print(f"company: {pulled.unkept}.", file=sys.stderr)
    elif pulled.unlogged:
        print("`kill.state` in the company home holds the record, and `company resume` writes it.", file=sys.stderr)
    print("Every launch is refused until `company resume`.")
    return EXIT_OK if pulled.clean else EXIT_REFUSED


def _resume(args) -> int:
    if _refused_inside_a_session(Ledger(), "resumed", "board"):
        return EXIT_REFUSED
    try:
        resumed = killswitch.resume(args.message)
    except killswitch.AnotherPullLanded as landed:
        print(f"company: {landed}.", file=sys.stderr)
        return EXIT_REFUSED
    except (killswitch.ResumeRefused, AppendRefused, LedgerBroken, OSError) as refused:
        print(f"company: refused: {refused}. Nothing was resumed.", file=sys.stderr)
        return EXIT_REFUSED
    print(f"Resumed: pulls closed, {len(resumed)}; launches may start again.")
    print(f"The schedule stays off until `{schedule.ENABLE}`, and a key moved aside stays moved until you regenerate it.")
    return EXIT_OK


def _schedule_install(args) -> int:
    if _refused_inside_a_session(Ledger(), "schedule-install", "board"):
        return EXIT_REFUSED
    try:
        schedule.install()
    except schedule.ScheduleFailed as failed:
        print(f"company: {failed}. Nothing was turned on.", file=sys.stderr)
        return EXIT_REFUSED
    print(f"Installed {len(schedule.JOBS)} jobs, every one off. Only `{schedule.ENABLE}` turns them on.")
    return EXIT_OK


def _schedule_enable(args) -> int:
    ledger = Ledger()
    if _refused_inside_a_session(ledger, "schedule-enabled", "board") or _is_broken(ledger):
        return EXIT_REFUSED
    try:
        event = schedule.enable(args.message)
    except schedule.ScheduleFailed as failed:
        print(f"company: {failed}. The ledger says the schedule is off, so no timer runs a job.", file=sys.stderr)
        return EXIT_REFUSED
    except (schedule.ScheduleRefused, AppendRefused, LedgerBroken) as refused:
        print(f"company: refused: {refused}. Nothing was turned on.", file=sys.stderr)
        return EXIT_REFUSED
    print(f"Recorded event {event['seq']}: the schedule is on, on message {args.message}: {', '.join(event['jobs'])}.")
    return EXIT_OK


def _schedule_disable(args) -> int:
    if _refused_inside_a_session(Ledger(), "schedule-disabled", "board"):
        return EXIT_REFUSED
    try:
        event = schedule.disable(args.reason)
    except schedule.ScheduleFailed as failed:
        print(f"company: {failed}. The timers may still be on.", file=sys.stderr)
        return EXIT_REFUSED
    except (AppendRefused, LedgerBroken, OSError) as refused:
        print(f"company: the timers are off, but the ledger could not take it: {refused}.", file=sys.stderr)
        return EXIT_REFUSED
    print(f"Recorded event {event['seq']}: the schedule is off.")
    return EXIT_OK


def _schedule_list(args) -> int:
    ledger = Ledger()
    if _is_broken(ledger):
        return EXIT_REFUSED
    print(f"The schedule is {'on' if schedule.enabled(ledger.read()) else 'off'}.")
    for job in schedule.JOBS:
        print(f"{job.name}: `company {' '.join(job.command)}`, on {job.calendar}")
    return EXIT_OK


def _schedule_run(args) -> int:
    """What a timer's service runs: the ledger decides again, so a timer left on still runs nothing."""
    ledger = Ledger()
    if _is_broken(ledger):
        return EXIT_REFUSED
    events = ledger.read()
    refusal = schedule.run_refusal(events)
    if refusal:
        print(f"company: refused: {refusal}. The job {args.job} did not run.", file=sys.stderr)
        return EXIT_REFUSED
    job = schedule.job(args.job)
    if not job.is_due(events, times.now()):
        print(f"The job {args.job} is not due.")
        return EXIT_OK
    return main(list(job.command))


# `settings init`'s flags: every one is the setting of the same name, and those with no value in the design are required.
_INIT_FLAGS = {
    "company_share": True,
    "team_floor": True,
    "monthly_price": True,
    "plan_name": True,
    "reading_max_age_minutes": True,
    "session_max_minutes": True,
    "session_max_weight": True,
    "cell_model": False,
    "auditor_model": False,
}


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

    configuration = commands.add_parser("settings", help="Daniel's settings, which only these commands change.")
    actions = configuration.add_subparsers(dest="action", required=True)

    init = actions.add_parser("init", help="Write the whole file, and log its digest; also the way back from tamper.")
    for key, required in _INIT_FLAGS.items():
        init.add_argument("--" + key.replace("_", "-"), dest=key, required=required)
    init.add_argument("--message", help="The Discord id of Daniel's word, if there is one.")
    init.set_defaults(run=_settings_init)

    change = actions.add_parser("set", help="Change one setting, and log its name and the file's new digest.")
    change.add_argument("key")
    change.add_argument("value", help="A JSON value, or else plain text.")
    change.add_argument("--message", help="The Discord id of Daniel's word, if there is one.")
    change.set_defaults(run=_settings_set)

    words = commands.add_parser("go", help="Daniel's go for real sessions.")
    actions = words.add_subparsers(dest="action", required=True)

    real = actions.add_parser(governor.GO_SCOPE, help="Grant exactly this many real launches; nothing else grants any.")
    real.add_argument("--message", required=True, help="The Discord id of Daniel's word.")
    real.add_argument("--sessions", required=True, type=int, help="How many launches the word grants.")
    real.set_defaults(run=_go)

    governs = commands.add_parser("governor", help="Whether a session may start.")
    actions = governs.add_subparsers(dest="action", required=True)

    check = actions.add_parser("check", help="Answer admitted or refused now; a refusal is logged, and an admission writes nothing.")
    check.add_argument("role", choices=governor.ROLES)
    check.add_argument("--bet", help="The bet's id, which a cell must name.")
    check.add_argument("--scheduled", action="store_true", help="Check as a scheduled session, which needs the schedule on and no word.")
    check.set_defaults(run=_governor_check)

    sessions = commands.add_parser("session", help="Run a company session.")
    actions = sessions.add_subparsers(dest="action", required=True)

    begin = actions.add_parser("start", help="Run one session to its end, if the governor admits it; a refusal starts nothing.")
    begin.add_argument("role", choices=governor.ROLES)
    begin.add_argument("--bet", help="The bet's id, which a cell must name.")
    begin.add_argument("--prompt", help="The task, added after the role's goal text.")
    begin.add_argument("--workspace", help="A workspace under the company's; with none, a fresh one.")
    begin.add_argument("--scheduled", action="store_true", help="Start as a scheduled session, which needs the schedule on and no word.")
    begin.set_defaults(run=_session_start)

    stop = commands.add_parser("kill", help="Stop every session, turn off the schedule, rotate each outside account, and hold every launch.")
    stop.add_argument("--reason", default="pulled by hand", help="Why, for the ledger.")
    stop.add_argument("--self-test", action="store_true", help="Run a whole pull in a temporary home of its own, on stubs, and touch nothing here.")
    stop.set_defaults(run=_kill)

    again = commands.add_parser("resume", help="Daniel's word that launches may start again after the kill switch.")
    again.add_argument("--message", help="The Discord id of Daniel's word, if there is one.")
    again.set_defaults(run=_resume)

    timers = commands.add_parser("schedule", help="The company's timers, which only Daniel's command turns on.")
    actions = timers.add_subparsers(dest="action", required=True)

    install = actions.add_parser("install", help="Write each job's timer, with every one off.")
    install.set_defaults(run=_schedule_install)

    enable = actions.add_parser("enable", help="Turn the timers on, on Daniel's word. Nothing else does.")
    enable.add_argument("--message", required=True, help="The Discord id of Daniel's word.")
    enable.set_defaults(run=_schedule_enable)

    disable = actions.add_parser("disable", help="Turn the timers off.")
    disable.add_argument("--reason", default="by hand", help="Why, for the ledger.")
    disable.set_defaults(run=_schedule_disable)

    listed = actions.add_parser("list", help="Say whether the schedule is on, and list its jobs.")
    listed.set_defaults(run=_schedule_list)

    firing = actions.add_parser("run", help="What a timer runs: one job, if the schedule is on and it is due.")
    firing.add_argument("job", choices=[job.name for job in schedule.JOBS])
    firing.set_defaults(run=_schedule_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return args.run(args)
