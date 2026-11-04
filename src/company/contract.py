"""The ledger's contract: which kinds exist, who may write each, and what fields each holds."""

import json
import re
from dataclasses import dataclass
from datetime import date
from importlib import resources

from company import times

_NAME = re.compile(r"[a-z0-9][a-z0-9_:-]{0,63}")
_BET = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_CELL_WRITER = "cell:<bet>"
_CELL_PREFIX = "cell:"
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_DISCORD_ID = re.compile(r"[0-9]{1,32}")
# From zero up: a refund written as -5.00 would add to net revenue, since refunds are subtracted.
_DECIMAL = re.compile(r"[0-9]+(\.[0-9]+)?")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _whole(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _matches(pattern: re.Pattern, value) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _is_seq(value, next_seq: int) -> bool:
    return _whole(value) and 1 <= value < next_seq


def _is_date(value) -> bool:
    if not _matches(_DATE, value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _is_number(value) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _type_holds(type_name: str, value, next_seq: int) -> bool:
    match type_name:
        case "seq":
            return _is_seq(value, next_seq)
        case "seqs":
            return isinstance(value, list) and all(_is_seq(item, next_seq) for item in value)
        case "timestamp":
            return isinstance(value, str) and times.parse_stamp(value) is not None
        case "date":
            return _is_date(value)
        case "uuid":
            return _matches(_UUID, value)
        case "bet":
            return _matches(_BET, value)
        case "discord-id":
            return _matches(_DISCORD_ID, value)
        case "decimal":
            return _matches(_DECIMAL, value)
        case "number":
            return _is_number(value)
        case "minutes":
            return _is_number(value) and value >= 0
    raise ValueError(f"the contract names an unknown field type: {type_name}")


@dataclass(frozen=True)
class Contract:
    """The contract's data, with the rule for each refusal."""

    kinds: dict
    writers: dict
    field_types: dict

    @classmethod
    def load(cls) -> "Contract":
        data = json.loads(resources.files("company").joinpath("ledger_contract.json").read_text())
        return cls(data["kinds"], data["writers"], data["field_types"])

    def refusal(self, kind, fields, writer, next_seq: int) -> str | None:
        """Why this event may not be appended, as a short reason code naming no rejected value; or None."""
        entry = self.kinds.get(kind) if isinstance(kind, str) else None
        if entry is None:
            return "unknown-kind"
        contract_writer = self._contract_writer(writer)
        if contract_writer is None:
            return "unknown-writer"
        if contract_writer not in entry["writers"]:
            return "writer-not-allowed"
        if not isinstance(fields, dict):
            return "not-an-object"
        missing = [name for name in entry["required"] if name not in fields]
        if missing:
            return "missing-fields:" + ",".join(missing)
        if set(fields) - set(entry["required"]) - set(entry["optional"]):
            return "unknown-fields"
        try:
            json.dumps(fields, allow_nan=False)
        except (TypeError, ValueError, RecursionError):
            return "not-json"
        for name, value in fields.items():
            type_name = self._field_type(name)
            if type_name is not None and not _type_holds(type_name, value, next_seq):
                return f"bad-field:{name}"
        return None

    def safe_label(self, label) -> str:
        """A kind or writer as a refusal may log it: a name, or a mark if it is no name at all."""
        return label if _matches(_NAME, label) else "<not-a-name>"

    def refusal_writer(self, writer) -> str:
        """Who logs a refusal: the code writer making the append, or the Treasurer for an agent or a person."""
        return writer if writer in self.writers["code"] else "treasurer"

    def _contract_writer(self, writer) -> str | None:
        """The name a writer goes by in the contract, or None if it is no writer."""
        if not isinstance(writer, str):
            return None
        if writer.startswith(_CELL_PREFIX):
            return _CELL_WRITER if _matches(_BET, writer.removeprefix(_CELL_PREFIX)) else None
        known = {name for group in self.writers.values() for name in group} - {_CELL_WRITER}
        return writer if writer in known else None

    def _field_type(self, name: str) -> str | None:
        if name in self.field_types["names"]:
            return self.field_types["names"][name]
        for suffix, type_name in self.field_types["suffixes"].items():
            if name.endswith(suffix):
                return type_name
        return None
