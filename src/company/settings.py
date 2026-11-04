"""Daniel's settings file: only what has a reader so far, and no value compiled in for any of it.

Nothing here checks the file against a recorded digest yet.
"""

import json

from company import paths


class SettingsRefused(Exception):
    """The settings file is missing, or a setting a caller needs is not usable."""


def load() -> dict:
    path = paths.config() / "settings.json"
    try:
        loaded = json.loads(path.read_text())
    except FileNotFoundError:
        raise SettingsRefused(f"there are no settings at {path}") from None
    except ValueError:
        raise SettingsRefused(f"the settings at {path} are not JSON") from None
    if not isinstance(loaded, dict):
        raise SettingsRefused(f"the settings at {path} are not a JSON object")
    return loaded


def positive_number(settings: dict, key: str) -> int | float:
    value = settings.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float) or not value > 0:
        raise SettingsRefused(f"the setting {key} is missing or is not a positive number")
    return value


def portfolio_number(settings: dict, key: str) -> int | float:
    """One of the `portfolio` setting's numbers, which may be zero, as a new bet's dollars are."""
    portfolio = settings.get("portfolio")
    value = portfolio.get(key) if isinstance(portfolio, dict) else None
    if value is None or not _is_amount(value):
        raise SettingsRefused(f"the setting portfolio.{key} is missing or is not a number from zero up")
    return value


def minutes_table(settings: dict) -> dict[str, int | float]:
    """What each action charges in Daniel-minutes."""
    table = settings.get("minutes_table")
    if not isinstance(table, dict) or not all(_is_amount(value) for value in table.values()):
        raise SettingsRefused("the setting minutes_table is missing or is not a table of numbers from zero up")
    return table


def _is_amount(value) -> bool:
    return not isinstance(value, bool) and isinstance(value, int | float) and value >= 0


def day_dirs(settings: dict) -> list[str]:
    """The team's `usage/` directories to read, which are optional."""
    value = settings.get("usage_day_dirs", [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise SettingsRefused("the setting usage_day_dirs is not a list of directories")
    return value
