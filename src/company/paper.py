"""The paper broker: the only module with an outside host or the key.

It speaks to two hosts, the paper account's and the market data's, on a transport it is given, and refuses one aimed anywhere else.
The key is read from its file at each call, and is sent only as the broker's two headers: an error here never holds a response's text or the key's.
`MarketData` reads bars and nothing else, so the company tools hold that; `Account` holds the one order path, which only `paper_period.py` calls.
"""

import http.client
import json
import math
import os
import re
import ssl
import stat
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Protocol
from urllib.parse import urlencode

from company import paths

PAPER_HOST = "paper-api.alpaca.markets"
DATA_HOST = "data.alpaca.markets"
HOSTS = frozenset({PAPER_HOST, DATA_HOST})
KEY_ID_HEADER = "APCA-API-KEY-ID"
SECRET_HEADER = "APCA-API-SECRET-KEY"
BARS_SOURCE = "broker:iex"
ACTIVE = "ACTIVE"
LABEL = "PAPER, no real money"

_TIMEOUT_SECONDS = 30
_MAX_RESPONSE_BYTES = 64_000_000
_MAX_KEY_BYTES = 4096
_BARS_PAGE = 10_000
_MAX_PAGES = 200
_KEY_PART = re.compile(r"[!-~]+")
_HOW = "create the free paper account at the broker, save its key id and secret on two lines in that file, and `chmod 600` it"


class PaperFailed(Exception):
    """Nothing further happened on the paper account; the text holds no key and no response from the broker."""


class KeyUnavailable(PaperFailed):
    """The key file cannot be used, so no call was made."""


class ForeignTransport(PaperFailed):
    """A transport or a host other than the paper broker's was named, so no key was read and no call made."""


class BrokerFailed(PaperFailed):
    """The broker could not be reached, or refused, or answered with something that cannot be read."""


class Transport(Protocol):
    """How a request leaves: `hosts` says where it can go, and `send` returns the status and the body."""

    hosts: frozenset[str]

    def send(self, method: str, host: str, target: str, headers: dict[str, str], body: bytes | None) -> tuple[int, bytes]: ...


class HttpsTransport:
    """The real one: it follows no redirect, uses no proxy, and checks the broker's certificate."""

    hosts = HOSTS

    def send(self, method: str, host: str, target: str, headers: dict[str, str], body: bytes | None) -> tuple[int, bytes]:
        if host not in HOSTS:
            raise ForeignTransport("that host is not the paper broker's, so nothing was sent")
        connection = http.client.HTTPSConnection(host, timeout=_TIMEOUT_SECONDS, context=ssl.create_default_context())
        try:
            connection.request(method, target, body=body, headers=headers)
            response = connection.getresponse()
            return response.status, response.read(_MAX_RESPONSE_BYTES)
        except (OSError, http.client.HTTPException) as error:
            raise BrokerFailed(f"{host} could not be reached: {type(error).__name__}") from None
        finally:
            connection.close()


def transport() -> Transport:
    """The transport every command uses, and the one seam a test replaces."""
    return HttpsTransport()


def _key_file_problem(found: os.stat_result) -> str | None:
    if not stat.S_ISREG(found.st_mode):
        return "is not a file"
    if found.st_uid != os.getuid():
        return "belongs to someone else"
    if stat.S_IMODE(found.st_mode) & 0o077:
        return "can be reached by someone other than its owner, so run `chmod 600` on it"
    return None


def _read_key(path: Path) -> tuple[str, str]:
    """The key id and secret, read now, from a file only its owner can reach."""
    try:
        # A link could point anywhere, and a pipe would never end.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        raise KeyUnavailable(f"there is no paper key at {path}: {_HOW}") from None
    except OSError as error:
        raise KeyUnavailable(f"the paper key at {path} cannot be opened: {error.strerror}") from None
    try:
        problem = _key_file_problem(os.fstat(fd))
        if problem:
            raise KeyUnavailable(f"the paper key at {path} {problem}. It was not read")
        content = os.read(fd, _MAX_KEY_BYTES)
    except OSError as error:
        raise KeyUnavailable(f"the paper key at {path} cannot be read: {error.strerror}") from None
    finally:
        os.close(fd)
    parts = content.decode("utf-8", "replace").split()
    if len(parts) != 2 or not all(_KEY_PART.fullmatch(part) for part in parts):
        raise KeyUnavailable(f"the paper key at {path} is not a key id and a secret on two lines")
    return parts[0], parts[1]


class _Client:
    """One host's calls: the key is read at each, and only a 2xx answer counts."""

    def __init__(self, sender: Transport, host: str, key_file: Path | None = None):
        reach = getattr(sender, "hosts", None)
        if host not in HOSTS or not isinstance(reach, frozenset) or not reach <= HOSTS:
            raise ForeignTransport("that transport is aimed at a host other than the paper broker's, so no key was read and nothing was sent")
        self.sender, self.host = sender, host
        self.key_file = paths.paper_key() if key_file is None else key_file

    def call(self, method: str, path: str, query: dict | None = None, body: dict | None = None):
        key_id, secret = _read_key(self.key_file)
        target = f"{path}?{urlencode(query)}" if query else path
        headers = {KEY_ID_HEADER: key_id, SECRET_HEADER: secret, "Accept": "application/json"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        status, content = self.sender.send(method, self.host, target, headers, data)
        if not 200 <= status < 300:
            raise BrokerFailed(f"the broker answered {status} to {method} {path}")
        if not content:
            return None
        try:
            return json.loads(content)
        except (ValueError, RecursionError):
            raise BrokerFailed(f"the broker's answer to {method} {path} is not JSON") from None


def _decimal(value, what: str) -> Decimal:
    try:
        number = Decimal(value) if isinstance(value, str) else None
    except InvalidOperation:
        number = None
    if number is None or not number.is_finite():
        raise BrokerFailed(f"the broker's {what} is not a number")
    return number


@dataclass(frozen=True)
class AccountState:
    status: str
    equity: Decimal


@dataclass(frozen=True)
class Position:
    """What the account holds of one symbol, with a short position's quantity below zero."""

    symbol: str
    quantity: Decimal


@dataclass(frozen=True)
class PlacedOrder:
    broker_order_id: str
    status: str


class Account:
    """The paper account, on the paper host alone."""

    def __init__(self, sender: Transport, key_file: Path | None = None):
        self._client = _Client(sender, PAPER_HOST, key_file)

    def read(self) -> AccountState:
        answer = self._client.call("GET", "/v2/account")
        if not isinstance(answer, dict) or not isinstance(answer.get("status"), str):
            raise BrokerFailed("the broker's account has no status")
        return AccountState(answer["status"], _decimal(answer.get("equity"), "equity"))

    def positions(self) -> list[Position]:
        answer = self._client.call("GET", "/v2/positions")
        if not isinstance(answer, list) or not all(isinstance(item, dict) and isinstance(item.get("symbol"), str) for item in answer):
            raise BrokerFailed("the broker's positions are not a list of positions")
        held = []
        for item in answer:
            quantity = abs(_decimal(item.get("qty"), "quantity held"))
            held.append(Position(item["symbol"], -quantity if item.get("side") == "short" else quantity))
        return held

    def cancel_orders(self) -> None:
        self._client.call("DELETE", "/v2/orders")

    def place_order(self, symbol: str, side: str, quantity: Decimal) -> PlacedOrder:
        """A market order for the day. `paper_period.py` alone calls this."""
        body = {"symbol": symbol, "qty": format(quantity, "f"), "side": side, "type": "market", "time_in_force": "day"}
        answer = self._client.call("POST", "/v2/orders", body=body)
        if not isinstance(answer, dict) or not isinstance(answer.get("id"), str) or not isinstance(answer.get("status"), str):
            raise BrokerFailed("the broker's answer to an order has no id and status")
        return PlacedOrder(answer["id"], answer["status"])


def _bar_fields(raw) -> dict:
    """One symbol's bar in the form a fixture holds it."""
    if not isinstance(raw, dict):
        raise BrokerFailed("the broker's bars cannot be read")
    fields = {"open": raw.get("o"), "high": raw.get("h"), "low": raw.get("l"), "close": raw.get("c"), "volume": raw.get("v")}
    for value in fields.values():
        if not isinstance(value, int | float) or isinstance(value, bool) or not math.isfinite(value):
            raise BrokerFailed("the broker's bars cannot be read")
    if raw["c"] <= 0:
        raise BrokerFailed("the broker's bars cannot be read")
    return fields


class MarketData:
    """Daily bars from the broker's free feed, in the form a fixture's bars take: all a session's tools can reach here."""

    def __init__(self, sender: Transport, key_file: Path | None = None):
        self._client = _Client(sender, DATA_HOST, key_file)

    def bars(self, universe: list[str], start: str, end: str) -> list[dict]:
        """Each day's `{date, symbols}`, oldest first, from `start` to `end`, split-adjusted, as the paper account does not model dividends."""
        days: dict[str, dict] = {}
        query = {"symbols": ",".join(universe), "timeframe": "1Day", "start": start, "end": end, "limit": _BARS_PAGE, "adjustment": "split", "feed": "iex", "sort": "asc"}
        for _ in range(_MAX_PAGES):
            answer = self._client.call("GET", "/v2/stocks/bars", query)
            token = self._add_page(days, answer)
            if not token:
                return [{"date": day, "symbols": days[day]} for day in sorted(days)]
            query = {**query, "page_token": token}
        raise BrokerFailed(f"the broker's bars ran past {_MAX_PAGES} pages")

    @staticmethod
    def _add_page(days: dict[str, dict], answer) -> str | None:
        if not isinstance(answer, dict) or not isinstance(answer.get("bars") or {}, dict):
            raise BrokerFailed("the broker's bars cannot be read")
        for symbol, bars in (answer.get("bars") or {}).items():
            if not isinstance(bars, list):
                raise BrokerFailed("the broker's bars cannot be read")
            for raw in bars:
                stamp = raw.get("t") if isinstance(raw, dict) else None
                if not isinstance(stamp, str) or len(stamp) < 10:
                    raise BrokerFailed("the broker's bars cannot be read")
                days.setdefault(stamp[:10], {})[symbol] = _bar_fields(raw)
        token = answer.get("next_page_token")
        return token if isinstance(token, str) and token else None
