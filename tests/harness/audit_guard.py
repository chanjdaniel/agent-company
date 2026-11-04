"""The suite's guard inside every Python process: an audit hook on sockets and on real paths.

The hook refuses the action and also writes it to the suite's guard log.
A test could swallow the exception, in a child process especially; it cannot unwrite the log, and
`suite_guard` fails the test that was running when a line arrived.
Standard library only: `sitecustomize` loads this in each child before anything else is imported.
"""

import json
import os
import socket
import sys

ENV = "COMPANY_TEST_GUARD"

NETWORK_NAME_EVENTS = {"socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr"}
NETWORK_SEND_EVENTS = {"socket.connect", "socket.sendto", "socket.sendmsg"}
PATH_EVENTS = {
    "open": 1,
    "os.chmod": 1,
    "os.link": 2,
    "os.listdir": 1,
    "os.mkdir": 1,
    "os.remove": 1,
    "os.rename": 2,
    "os.rmdir": 1,
    "os.scandir": 1,
    "os.symlink": 2,
    "os.truncate": 1,
}


class GuardViolation(RuntimeError):
    """The suite tried something it must never do."""


_settings = None
_installed = False


def configure(log, allowed, forbidden):
    """Set where violations go, and which paths are out of reach unless they are under one of `allowed`."""
    global _settings
    _settings = (str(log), tuple(str(path) for path in allowed), tuple(str(path) for path in forbidden))


def install():
    """Add the hook once; an audit hook can never be removed, so `configure` may change what it reads."""
    global _installed
    if not _installed:
        sys.addaudithook(_hook)
        _installed = True


def env_value():
    """The current settings, for a child process's environment."""
    log, allowed, forbidden = _settings
    return json.dumps({"log": log, "allowed": allowed, "forbidden": forbidden})


def install_from_env():
    """A child process's entry: guard it as the parent is guarded, if the parent is the suite."""
    value = os.environ.get(ENV)
    if value:
        settings = json.loads(value)
        configure(settings["log"], settings["allowed"], settings["forbidden"])
        install()


def _inside(path, parent):
    return path == parent or path.startswith(parent + os.sep)


def _forbidden_path(raw):
    """The forbidden root that `raw` falls in, or None; a file descriptor or other non-path has none."""
    if not isinstance(raw, str | bytes | os.PathLike):
        return None
    path = os.path.abspath(os.fsdecode(raw))
    _, allowed, forbidden = _settings
    if any(_inside(path, root) for root in allowed):
        return None
    return next((root for root in forbidden if _inside(path, root)), None)


def _violation(event, args):
    """What is wrong with this audit event, or None."""
    if event in NETWORK_NAME_EVENTS:
        return f"network: {event}"
    if event in NETWORK_SEND_EVENTS:
        if args[0].family != socket.AF_UNIX:
            return f"network: {event} to {args[1]!r}"
        return None
    count = PATH_EVENTS.get(event)
    if count is not None:
        for raw in args[:count]:
            root = _forbidden_path(raw)
            if root is not None:
                return f"real path: {event} on {os.fsdecode(raw)}"
    return None


def _hook(event, args):
    if _settings is None:
        return
    if event not in NETWORK_NAME_EVENTS and event not in NETWORK_SEND_EVENTS and event not in PATH_EVENTS:
        return
    try:
        problem = _violation(event, args)
    except (AttributeError, OSError, TypeError, ValueError):
        # An odd argument, or an interpreter shutting down: nothing to judge.
        return
    if problem is None:
        return
    # This `open` is audited too, and passes: the log is never under a forbidden path.
    fd = os.open(_settings[0], os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, f"{problem}\n".encode())
    finally:
        os.close(fd)
    raise GuardViolation(f"the suite's guard refused it: {problem}")
