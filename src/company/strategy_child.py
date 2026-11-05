"""What runs inside the sandbox: a cell's strategy, given one bar at a time, answering with its target positions.

This file is bound alone into the `bwrap` that `quant.py` starts, and runs on the standard library with no site packages.
It says it is ready before it touches the cell's code, so the runner can tell a sandbox that never started from a strategy that failed.
"""

import json
import resource
import sys

_MEMORY_BYTES = 4 * 1024**3


def _say(message: dict) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def main() -> int:
    resource.setrlimit(resource.RLIMIT_AS, (_MEMORY_BYTES, _MEMORY_BYTES))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    # No second process or thread, so that the memory limit is the whole strategy's.
    resource.setrlimit(resource.RLIMIT_NPROC, (1, 1))
    _say({"ready": True})
    configuration = json.loads(sys.stdin.readline())
    try:
        strategy: dict = {"__name__": "strategy"}
        exec(compile(configuration["code"], "strategy", "exec"), strategy)  # noqa: S102 - running the cell's code is this sandbox's whole purpose.
        decide = strategy["decide"]
        while line := sys.stdin.readline():
            _say({"positions": decide(json.loads(line), configuration["parameters"])})
    except BaseException as error:  # noqa: BLE001 - whatever the cell's code raises is its failure to report, SystemExit too.
        _say({"error": f"{type(error).__name__}: {error}"})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
