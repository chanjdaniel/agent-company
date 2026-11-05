"""Daniel's settings file: only `company settings init` and `set` change it, and no share or floor is compiled in.

Each change records the file's digest in the ledger, and `load()` refuses a file that no longer matches, so an edit
made any other way refuses every reader until Daniel writes a whole new file with `init`.
"""

import contextlib
import fcntl
import hashlib
import json
import math
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TypeGuard

from company import paths
from company.ledger import AppendRefused, Ledger, LedgerBroken

INIT = "company settings init"
SET = "company settings set"
MOVE_KEY = "move-key"
_OWN_FILES = ("settings.json", "settings.lock")
_NO_FILE = "none"


class SettingsRefused(Exception):
    """A setting a caller needs is not usable; `code` names the kind of refusal, and `fix` the command that fixes it."""

    code = "unusable"
    fix = SET


class SettingsMissing(SettingsRefused):
    """No settings file exists, and none ever did."""

    code = "missing"
    fix = INIT


class SettingsTampered(SettingsRefused):
    """The file is not the one the ledger's last digest describes."""

    code = "tampered"
    fix = INIT


def digest_of(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _path() -> Path:
    return paths.config() / "settings.json"


@contextlib.contextmanager
def _locked(mode: int) -> Iterator[None]:
    """Keep a change whole for a reader: its digest goes in the ledger just before its file moves into place.

    A shared hold needs no lock file, since with none no command has written anything to wait for.
    """
    lock = paths.config() / "settings.lock"
    try:
        if mode == fcntl.LOCK_EX:
            paths.config().mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
        else:
            fd = os.open(lock, os.O_RDONLY)
    except FileNotFoundError:
        yield
        return
    except OSError as error:
        raise SettingsRefused(f"the settings at {_path()} cannot be read: {error}") from None
    try:
        fcntl.flock(fd, mode)
        yield
    finally:
        os.close(fd)


def _state() -> tuple[bytes | None, str | None]:
    """The file's content, or None with no file; and the ledger's last digest, or None with no change recorded."""
    try:
        content = _path().read_bytes()
    except FileNotFoundError:
        content = None
    except OSError as error:
        raise SettingsRefused(f"the settings at {_path()} cannot be read: {error}") from None
    changes = (event["digest"] for event in reversed(Ledger().read()) if event["kind"] == "settings-changed")
    return content, next(changes, None)


def _log_tamper(recorded: str | None, found: str | None) -> None:
    """Log what was found; a ledger that cannot take it changes nothing, since the caller refuses either way."""
    fields = {"expected_digest": recorded or _NO_FILE, "found_digest": found or _NO_FILE}
    with contextlib.suppress(AppendRefused, LedgerBroken, OSError):
        Ledger().append("settings-tamper", fields, "governor")


def _checked(content: bytes | None, recorded: str | None, log_tamper: bool) -> dict:
    found = None if content is None else digest_of(content)
    if found is None and recorded is None:
        raise SettingsMissing(f"there are no settings at {_path()}")
    if found != recorded:
        if log_tamper:
            _log_tamper(recorded, found)
        raise SettingsTampered(f"the settings at {_path()} are not the file `{INIT}` or `{SET}` last wrote")
    try:
        loaded = json.loads(content or b"")
    except ValueError:
        raise SettingsRefused(f"the settings at {_path()} are not JSON") from None
    if not isinstance(loaded, dict):
        raise SettingsRefused(f"the settings at {_path()} are not a JSON object")
    return loaded


def load(log_tamper: bool = True) -> dict:
    """The file, if it is the one the ledger describes; a mismatch logs `settings-tamper` and refuses.

    `log_tamper=False` is for a report that promises to write nothing: it refuses the same, and logs nothing.
    A ledger that cannot be read raises `LedgerBroken`.
    """
    with _locked(fcntl.LOCK_SH):
        content, recorded = _state()
    return _checked(content, recorded, log_tamper)


def parse(text: str):
    """A setting as typed on a command line: a JSON value, or else plain text."""
    try:
        value = json.loads(text, parse_constant=_no_constant)
        json.dumps(value, allow_nan=False)
    except (ValueError, RecursionError):
        return text
    return value


def _no_constant(name: str):
    raise ValueError(name)


def init(given: dict, message: str | None = None) -> dict:
    """Write a whole new file from `given` and the design's numbers, and log it; a good file stands, and `set` changes it.

    This is the way back from tamper too, since it blesses nothing of the file it replaces.
    """
    values = {**_DESIGN_VALUES, **given}
    for key, check in KEYS.items():
        if key in values or key not in _OPTIONAL:
            check(values, key)
    with _locked(fcntl.LOCK_EX):
        content, recorded = _state()
        found = None if content is None else digest_of(content)
        if found is not None and found == recorded:
            raise SettingsRefused(f"the settings at {_path()} are already written, so `{SET}` changes them")
        if found != recorded:
            _log_tamper(recorded, found)
        return _commit(values, sorted(values), message)


def set_value(key: str, text: str, message: str | None = None) -> dict:
    """Change one setting and log it; a file that no longer matches is refused, since this would bless the change."""
    check = KEYS.get(key)
    if check is None:
        raise SettingsRefused(f"there is no setting {key}")
    with _locked(fcntl.LOCK_EX):
        content, recorded = _state()
        values = _checked(content, recorded, log_tamper=True)
        values[key] = parse(text)
        check(values, key)
        return _commit(values, [key], message)


def _commit(values: dict, keys: list[str], message: str | None) -> dict:
    """The digest goes in the ledger first, so a refused append changes nothing; a crash before the move reads as tamper."""
    content = (json.dumps(values, indent=2, sort_keys=True) + "\n").encode()
    fields = {"digest": digest_of(content), "keys": keys}
    if message is not None:
        fields["message"] = message
    temporary = _path().with_name("settings.json.new")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as file:
        os.fchmod(file.fileno(), 0o600)
        file.write(content)
    try:
        event = Ledger().append("settings-changed", fields, "board")
        temporary.replace(_path())
    finally:
        temporary.unlink(missing_ok=True)
    return event


def _is_amount(value) -> TypeGuard[int | float]:
    return not isinstance(value, bool) and isinstance(value, int | float) and math.isfinite(value) and value >= 0


def positive_number(settings: dict, key: str) -> int | float:
    value = settings.get(key)
    if not _is_amount(value) or not value > 0:
        raise SettingsRefused(f"the setting {key} is missing or is not a positive number")
    return value


def fraction(settings: dict, key: str) -> int | float:
    """A share of a budget, as a fraction, so that 25 written for 25% is refused and not taken a hundred times too large."""
    value = settings.get(key)
    if not _is_amount(value) or not 0 < value <= 1:
        raise SettingsRefused(f"the setting {key} is missing or is not a fraction above 0 and up to 1, like 0.25 for 25%")
    return value


def percent(settings: dict, key: str) -> int | float:
    """A percent of a window, from 0 to 100."""
    value = settings.get(key)
    if not _is_amount(value) or value > 100:
        raise SettingsRefused(f"the setting {key} is missing or is not a percent from 0 to 100, like 60 for 60%")
    return value


def text(settings: dict, key: str) -> str:
    value = settings.get(key)
    if not isinstance(value, str) or not value:
        raise SettingsRefused(f"the setting {key} is missing or is not a text")
    return value


def _whole_number(settings: dict, key: str) -> int:
    value = settings.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SettingsRefused(f"the setting {key} is not a whole number from zero up")
    return value


def portfolio_number(settings: dict, key: str) -> int | float:
    """One of the `portfolio` setting's numbers, which may be zero, as a new bet's dollars are."""
    value = _portfolio_value(settings, key)
    if not _is_amount(value):
        raise SettingsRefused(f"the setting portfolio.{key} is missing or is not a number from zero up")
    return value


def portfolio_fraction(settings: dict, key: str) -> int | float:
    """One of the `portfolio` setting's shares, as a fraction, which may be zero."""
    value = _portfolio_value(settings, key)
    if not _is_amount(value) or value > 1:
        raise SettingsRefused(f"the setting portfolio.{key} is missing or is not a fraction from 0 to 1, like 0.1 for 10%")
    return value


def _portfolio_value(settings: dict, key: str):
    portfolio = settings.get("portfolio")
    return portfolio.get(key) if isinstance(portfolio, dict) else None


def _portfolio(settings: dict, key: str) -> None:
    for name in ("exploration_floor", "holdout_share", "new_bet_token_share"):
        portfolio_fraction(settings, name)
    for name in ("new_bet_minutes", "new_bet_dollars", "new_bet_weeks", "closure_kills", "margin_lookback_weeks"):
        portfolio_number(settings, name)


def _complaint_threshold(settings: dict, key: str) -> None:
    value = settings.get(key)
    if (
        not isinstance(value, dict)
        or not _is_amount(value.get("count"))
        or not _is_amount(value.get("days"))
        or not _is_amount(value.get("outside_action_fraction"))
        or value["outside_action_fraction"] > 1
    ):
        raise SettingsRefused(f"the setting {key} is not a count, a number of days and a fraction of outside actions")


def minutes_table(settings: dict) -> dict[str, int | float]:
    """What each action charges in Daniel-minutes."""
    table = settings.get("minutes_table")
    if not isinstance(table, dict) or not all(_is_amount(value) for value in table.values()):
        raise SettingsRefused("the setting minutes_table is missing or is not a table of numbers from zero up")
    return table


def day_dirs(settings: dict) -> list[str]:
    """The team's `usage/` directories to read, which are optional."""
    value = settings.get("usage_day_dirs", [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise SettingsRefused("the setting usage_day_dirs is not a list of directories")
    return value


def key_path(account: dict) -> Path:
    """Where an outside account's key file is: always in the config directory."""
    return paths.config() / account["key_file"]


def account_problem(account) -> str | None:
    """What is wrong with one entry of `outside_accounts`, whose rotation step the kill switch runs; or None."""
    if not isinstance(account, dict) or set(account) != {"name", "rotation", "key_file"}:
        return "an outside account holds exactly a name, a rotation and a key_file"
    if not isinstance(account["name"], str) or not account["name"]:
        return "an outside account's name is a text"
    if account["rotation"] != MOVE_KEY:
        return f"an outside account's rotation is {MOVE_KEY}, the only step the code has"
    key_file = account["key_file"]
    if not isinstance(key_file, str) or not key_file or Path(key_file).is_absolute() or ".." in Path(key_file).parts:
        return "an outside account's key_file is a path inside the config directory"
    # `Path` drops each `.`, so that "." has no parts at all, and is the directory itself.
    if not Path(key_file).parts or Path(key_file).parts[0] in _OWN_FILES:
        return "an outside account's key_file names a key, and not the config directory or the settings' own files"
    return None


def _outside_accounts(settings: dict, key: str) -> None:
    value = settings.get(key)
    if not isinstance(value, list):
        raise SettingsRefused(f"the setting {key} is not a list of accounts")
    for account in value:
        problem = account_problem(account)
        if problem:
            raise SettingsRefused(f"the setting {key}: {problem}")


def accounts_for_kill() -> tuple[list, str | None]:
    """The accounts for the kill switch to rotate, as the file stands, and why there are none if it cannot be read.

    This takes no lock and asks no ledger, since a pull must not wait on either, nor be stopped by the very tamper it may
    be answering. So each entry is checked by `account_problem`, and can name only files in this directory.
    """
    try:
        value = json.loads(_path().read_bytes()).get("outside_accounts", [])
    except FileNotFoundError:
        return [], None
    except (OSError, ValueError, AttributeError) as error:
        return [], f"the settings cannot be read, so no account was rotated: {error}"
    return (value, None) if isinstance(value, list) else ([], "the settings hold no list of outside accounts, so none was rotated")


# Every setting the file may hold, with what `init` and `set` check it by.
KEYS: dict[str, Callable[[dict, str], object]] = {
    "company_share": fraction,
    "team_floor": percent,
    "monthly_price": positive_number,
    "plan_name": text,
    "cell_model": text,
    "auditor_model": text,
    "reading_max_age_minutes": positive_number,
    "session_max_minutes": positive_number,
    "session_max_weight": positive_number,
    "daily_minutes": positive_number,
    "weekly_send_cap": _whole_number,
    "minutes_table": lambda settings, key: minutes_table(settings),
    "complaint_threshold": _complaint_threshold,
    "portfolio": _portfolio,
    "outside_accounts": _outside_accounts,
    "usage_day_dirs": lambda settings, key: day_dirs(settings),
}
# With no send cap set, the batch holds every send.
_OPTIONAL = {"weekly_send_cap"}
# The numbers `docs/design.md` records, which `init` writes so that `set` can change each. The share, the floor, the
# plan and its price, the reading's age and a session's limits are not here: only Daniel's command gives those.
_DESIGN_VALUES = {
    "cell_model": "claude-opus-5-5",
    "auditor_model": "claude-sonnet-5-5",
    "daily_minutes": 15,
    "minutes_table": {"templated-approval": 0.5, "message-review": 2, "message-send": 0.5, "new-public-artifact": 5},
    "complaint_threshold": {"count": 2, "days": 30, "outside_action_fraction": 0.02},
    "portfolio": {
        "exploration_floor": 0.1,
        "holdout_share": 0.1,
        "new_bet_token_share": 0.1,
        "new_bet_minutes": 15,
        "new_bet_dollars": 0,
        "new_bet_weeks": 4,
        "closure_kills": 2,
        "margin_lookback_weeks": 4,
    },
    "outside_accounts": [],
    "usage_day_dirs": [],
}
