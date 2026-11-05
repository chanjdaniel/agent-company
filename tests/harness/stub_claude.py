"""A stub `claude`: it takes the launcher's real arguments and plays a test's script through the real company tools.

`stub_session.Stub` writes the shell wrapper that starts this file, which is where the suite's guard comes back:
the launcher strips it from the child's environment, as it must, and the wrapper sets it again.
"""

import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

DIRECTORY = Path(os.environ["STUB_DIRECTORY"])
# Each flag the launcher's form needs, as `claude --help` lists them in the version the builder read.
HELP_FLAGS = (
    "-p, --print",
    "--allowedTools",
    "--disable-slash-commands",
    "--mcp-config",
    "--model",
    "--output-format",
    "--permission-mode",
    "--restricted",
    "--session-id",
    "--settings",
    "--strict-mcp-config",
    "--tools",
    "--verbose",
)


def _flag(name):
    arguments = sys.argv[1:]
    return arguments[arguments.index(name) + 1] if name in arguments else None


def _record(name, entry):
    with (DIRECTORY / name).open("a") as file:
        file.write(json.dumps(entry) + "\n")


class Tools:
    """An MCP client over stdio, starting the one server `--mcp-config` names, as Claude Code does."""

    def __init__(self):
        config = json.loads(Path(_flag("--mcp-config")).read_text())
        server = config["mcpServers"]["company"]
        self.process = subprocess.Popen(
            [server["command"], *server.get("args", [])],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            env={**os.environ, **server.get("env", {})},
            text=True,
        )
        self.next_id = 1
        self.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "stub", "version": "0"}})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _send(self, message):
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def request(self, method, params):
        identifier = self.next_id
        self.next_id += 1
        self._send({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params})
        return json.loads(self.process.stdout.readline())

    def close(self):
        self.process.stdin.close()
        self.process.wait(timeout=10)


def _transcript_path(session):
    project = re.sub(r"[^a-zA-Z0-9]", "-", os.getcwd())
    path = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "projects" / project / f"{session}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _usage(step):
    return {"input_tokens": 0, "output_tokens": step["output"], "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}


def _reply(session, step):
    """One model reply, in the transcript, in the live output, or in both, as `where` says."""
    model = step.get("model", "claude-opus-5-5")
    message = {"id": f"msg-{step['request']}", "model": model, "usage": _usage(step), "content": step.get("content", [{"type": "text", "text": step.get("text", "words")}])}
    where = step.get("where", "both")
    if where in ("both", "transcript"):
        line = {
            "type": "assistant",
            "sessionId": session,
            "requestId": step["request"],
            "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "message": message,
        }
        with _transcript_path(session).open("a") as file:
            file.write(json.dumps(line) + "\n")
    if where in ("both", "output"):
        print(json.dumps({"type": "assistant", "session_id": session, "message": message}), flush=True)


def _play(step, session, tools):
    match step["do"]:
        case "tool":
            tools = tools or Tools()
            answer = tools.request("tools/call", {"name": step["name"], "arguments": step.get("arguments", {})})
            _record("tool_results.jsonl", answer)
        case "list-tools":
            tools = tools or Tools()
            _record("tool_lists.jsonl", tools.request("tools/list", {}))
        case "reply":
            _reply(session, step)
        case "print":
            print(step["text"], flush=True)
        case "hang":
            _record("progress.jsonl", {"hanging": os.getpid()})
            time.sleep(step.get("seconds", 600))
        case "children":
            pids = [subprocess.Popen(["/bin/sleep", "600"]).pid for _ in range(step["count"])]
            _record("progress.jsonl", {"children": pids})
        case "ignore-term":
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        case "network":
            import socket

            connection = socket.socket()
            connection.settimeout(1)
            try:
                connection.connect(("127.0.0.1", 9))
            except BaseException as swallowed:  # noqa: BLE001 - swallowed on purpose: the guard must catch it anyway.
                _record("progress.jsonl", {"network": str(swallowed)})
        case "run":
            done = subprocess.run(step["command"], env={**os.environ, **step.get("env", {})}, capture_output=True, text=True, check=False)
            _record("runs.jsonl", {"command": step["command"], "exit": done.returncode, "stdout": done.stdout, "stderr": done.stderr})
        case "exit":
            sys.stdout.flush()
            os._exit(step["code"])
        case other:
            raise ValueError(f"the stub has no step {other}")
    return tools


def main():
    script = json.loads((DIRECTORY / "script.json").read_text())
    _record("calls.jsonl", {"argv": sys.argv[1:], "cwd": os.getcwd(), "stdin": None if "--help" in sys.argv else sys.stdin.read()})
    if "--help" in sys.argv:
        print("\n".join(flag for flag in HELP_FLAGS if flag not in script.get("help_lacks", [])))
        return script.get("help_exit", 0)
    session = _flag("--session-id")
    tools = None
    for step in script.get("steps", []):
        tools = _play(step, session, tools)
    if tools:
        tools.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
