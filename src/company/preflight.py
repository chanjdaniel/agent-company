"""The preflight: each of Daniel's steps from S3 to S7, passed or open, with what closes it.

It reads and writes nothing it need not: it never opens the paper key, and a mismatch in the settings is reported and not logged.
A launch still asks the governor, which logs its refusals.
"""

import json
import os
import shlex
import shutil
from dataclasses import dataclass

from company import banned, governor, kill_state, launcher, paper, paths, settings

ACCOUNT_CHECKED = "company account checked"
_OUTSIDE_ACCOUNTS = json.dumps(settings.PAPER_ACCOUNTS)
_SANDBOX_TOOLS = {"bwrap": "bubblewrap", "socat": "socat"}


@dataclass(frozen=True)
class Problem:
    """One thing that keeps a step open, and what closes it."""

    reason: str
    fix: str


@dataclass(frozen=True)
class Step:
    """One of Daniel's steps; it has passed when nothing keeps it open."""

    name: str
    title: str
    problems: tuple[Problem, ...]

    @property
    def passed(self) -> bool:
        return not self.problems


def _key_fix() -> str:
    path = paths.paper_key()
    quoted = shlex.quote(str(path))
    if not os.path.lexists(path):
        return f"install -m 600 /dev/null {quoted}, then save the key id and the secret on its two lines in your editor"
    if path.is_symlink() or not path.is_file() or path.lstat().st_uid != os.getuid():
        return f"put a plain file of your own at {quoted} in its place, holding the key id and the secret on two lines"
    if path.lstat().st_size == 0:
        return f"save the key id and the secret on the two lines of {quoted} in your editor"
    return f"chmod 600 {quoted}"


def _rotates_the_key() -> bool:
    """Whether a pull would move the key, as the kill switch reads the list."""
    accounts, problem = settings.accounts_for_kill()
    return problem is None and any(isinstance(account, dict) and account.get("key_file") == paths.PAPER_KEY for account in accounts)


def _s3() -> tuple[Problem, ...]:
    unfit = paper.key_file_unfit()
    problems = [Problem(unfit, _key_fix())] if unfit else []
    # Only over settings that stand, since S4 says what is wrong with any others.
    if governor.settings_blocked() is None and not _rotates_the_key():
        problems.append(Problem("`outside_accounts` has no entry for the paper key, so a pull of the kill switch would leave it in place", f"{settings.SET} outside_accounts {shlex.quote(_OUTSIDE_ACCOUNTS)}"))
    return tuple(problems)


def _s4() -> tuple[Problem, ...]:
    problems = []
    blocked = governor.settings_blocked()
    if blocked:
        problems.append(Problem(blocked.reason, blocked.fix))
    wrong_form = launcher.form_problem("probe")
    if wrong_form:
        problems.append(Problem(wrong_form, "install Claude Code, or update it to a version whose help lists every flag a launch passes"))
    for tool, package in _SANDBOX_TOOLS.items():
        if shutil.which(tool, path=launcher.CHILD_PATH) is None:
            problems.append(Problem(f"`{tool}` is not on a session's path, {launcher.CHILD_PATH}, and a session's sandbox needs it", f"install the `{package}` package with your system's package manager"))
    for name in sorted(filter(banned.is_banned, os.environ)):
        problems.append(Problem(f"`{name}` is set here, and no company session may hold it; the launcher strips it, and it should not be in this shell at all", f"unset {name}"))
    return tuple(problems)


def account_check_stands(events: list[dict]) -> bool:
    """Whether Daniel has checked the account for the word in force, or for the next if none is: each go needs a check since the go before it."""
    checks = [event["seq"] for event in events if event["kind"] == "account-checked"]
    words = governor.go_words(events)
    if not words:
        return bool(checks)
    if governor.open_word(events) is None:
        since = words[-1]["seq"]
    else:
        since = words[-2]["seq"] if len(words) > 1 else 0
    return any(seq > since for seq in checks)


def _s5(events: list[dict]) -> tuple[Problem, ...]:
    if account_check_stands(events):
        return ()
    reason = 'no code can see these, and you have not said you checked them since the last go: that extra usage is off on the account page, and that the dependencies in docs/design.md, "Dependencies to re-check", still say what it cites'
    return (Problem(reason, f"check both, then {ACCOUNT_CHECKED}"),)


def _s6(events: list[dict]) -> tuple[Problem, ...]:
    blocked = governor.room_blocked(events)
    return (Problem(blocked.reason, blocked.fix),) if blocked else ()


def _s7(events: list[dict]) -> tuple[Problem, ...]:
    held = kill_state.refusal(events)
    if held:
        return (Problem(held, governor.FIX_KILL),)
    if governor.open_word(events) is None:
        return (Problem("no go-given word with launches left is on record", governor.FIX_GO),)
    return ()


def steps(events: list[dict]) -> list[Step]:
    """Each step as it stands, on a ledger that the caller has seen verify."""
    return [
        Step("S3", "the paper account's key, which was not read", _s3()),
        Step("S4", "the installed command, Daniel's settings, Claude Code, the sandbox's tools and this shell", _s4()),
        Step("S5", "your check of the account page and the dependencies", _s5(events)),
        Step("S6", "a usable reading of the account, under the floor and the company's share", _s6(events)),
        Step("S7", "your go", _s7(events)),
    ]


def report(found: list[Step]) -> list[str]:
    """What the command prints, one line at a time."""
    lines = []
    for step in found:
        lines.append(f"{step.name} {'passed' if step.passed else 'OPEN'}: {step.title}.")
        for problem in step.problems:
            lines += [f"  {problem.reason.rstrip('.')}.", f"  To close it: {problem.fix}"]
    still_open = [step.name for step in found if not step.passed]
    lines.append(f"Preflight is open: {', '.join(still_open)}. Nothing was started." if still_open else "Preflight passes: every step from S3 to S7 is done.")
    return lines
