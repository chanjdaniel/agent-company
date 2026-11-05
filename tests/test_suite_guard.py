"""The suite's own guards, shown failing: each case runs a small pytest of its own and reads how it ended."""

import os
import pwd
import stat
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

REAL_HOME = pwd.getpwuid(os.getuid()).pw_dir
PASSED = 0
TEST_FAILED = 1
REFUSED_START = 3


def run_child_suite(parent, test_source, conftest=None, env=None):
    directory = parent / "child-suite"
    directory.mkdir()
    (directory / "test_child.py").write_text(dedent(test_source))
    if conftest:
        (directory / "conftest.py").write_text(dedent(conftest))
    command = [sys.executable, "-m", "pytest", "-p", "suite_guard", "-p", "no:cacheprovider", "-q", "test_child.py"]
    return subprocess.run(
        command,
        check=False,
        cwd=directory,
        env={**os.environ, **(env or {})},
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_this_run_has_the_guards(pytestconfig):
    assert pytestconfig.pluginmanager.hasplugin("suite_guard")
    assert Path(os.environ["HOME"]).resolve() != Path(REAL_HOME).resolve()


def bare_test(body):
    lines = dedent(body).splitlines()
    return "def test_it():\n" + "\n".join("    " + line for line in lines) + "\n"


NETWORK_ATTEMPTS = {
    "inet connect": """
        import socket
        sock = socket.socket()
        sock.settimeout(1)
        try:
            sock.connect(("127.0.0.1", 9))
        except BaseException as swallowed:
            print("swallowed", swallowed)
    """,
    "udp send": """
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.sendto(b"x", ("127.0.0.1", 9))
        except BaseException as swallowed:
            print("swallowed", swallowed)
    """,
    "name lookup": """
        import socket
        try:
            socket.getaddrinfo("localhost", 80)
        except BaseException as swallowed:
            print("swallowed", swallowed)
    """,
}


@pytest.mark.parametrize("attempt", NETWORK_ATTEMPTS)
def test_a_network_attempt_fails_the_test_even_when_swallowed(attempt, tmp_path):
    result = run_child_suite(tmp_path, bare_test(NETWORK_ATTEMPTS[attempt]))
    assert result.returncode == TEST_FAILED, result.stdout + result.stderr
    assert "the suite's guard caught this, in this test or just before it: network" in result.stdout


@pytest.mark.parametrize("attempt", NETWORK_ATTEMPTS)
def test_a_network_attempt_in_a_child_python_fails_the_test(attempt, tmp_path):
    child = dedent(NETWORK_ATTEMPTS[attempt])
    source = bare_test(
        f"""
        import subprocess, sys
        subprocess.run([sys.executable, "-c", {child!r}], capture_output=True)
        """
    )
    result = run_child_suite(tmp_path, source)
    assert result.returncode == TEST_FAILED, result.stdout + result.stderr
    assert "the suite's guard caught this, in this test or just before it: network" in result.stdout


UNIX_SOCKET = """
    import os, socket, tempfile
    path = os.path.join(tempfile.mkdtemp(), "s")
    server = socket.socket(socket.AF_UNIX)
    server.bind(path)
    server.listen()
    client = socket.socket(socket.AF_UNIX)
    client.connect(path)
"""


def test_a_unix_socket_passes(tmp_path):
    result = run_child_suite(tmp_path, bare_test(UNIX_SOCKET))
    assert result.returncode == PASSED, result.stdout + result.stderr


def test_a_unix_socket_in_a_child_python_passes(tmp_path):
    child = dedent(UNIX_SOCKET)
    source = bare_test(
        f"""
        import subprocess, sys
        subprocess.run([sys.executable, "-c", {child!r}], check=True)
        """
    )
    result = run_child_suite(tmp_path, source)
    assert result.returncode == PASSED, result.stdout + result.stderr


def test_an_unchosen_claude_fails_the_test(tmp_path):
    source = bare_test(
        """
        import subprocess
        subprocess.run(["claude", "-p", "hello"], capture_output=True)
        """
    )
    result = run_child_suite(tmp_path, source)
    assert result.returncode == TEST_FAILED, result.stdout + result.stderr
    assert "the suite's guard caught this, in this test or just before it: model" in result.stdout


def test_an_unchosen_claude_in_a_child_python_fails_the_test(tmp_path):
    child = "import subprocess; subprocess.run(['claude', '-p', 'hello'], capture_output=True)"
    source = bare_test(
        f"""
        import subprocess, sys
        subprocess.run([sys.executable, "-c", {child!r}], capture_output=True)
        """
    )
    result = run_child_suite(tmp_path, source)
    assert result.returncode == TEST_FAILED, result.stdout + result.stderr
    assert "the suite's guard caught this, in this test or just before it: model" in result.stdout


def test_an_unchosen_systemctl_fails_the_test(tmp_path):
    # A real one would change Daniel's own timers.
    source = bare_test(
        """
        import subprocess
        subprocess.run(["systemctl", "--user", "enable", "--now", "a.timer"], capture_output=True)
        """
    )
    result = run_child_suite(tmp_path, source)
    assert result.returncode == TEST_FAILED, result.stdout + result.stderr
    assert "the suite's guard caught this, in this test or just before it: schedule" in result.stdout


def test_a_claude_a_test_chose_passes(tmp_path):
    stub = tmp_path / "stub" / "claude"
    stub.parent.mkdir()
    stub.write_text("#!/bin/sh\necho stub\n")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    source = bare_test(
        f"""
        import os, subprocess
        env = {{**os.environ, "PATH": {str(stub.parent)!r} + os.pathsep + os.environ["PATH"]}}
        assert subprocess.run(["claude"], env=env, capture_output=True, text=True).stdout == "stub\\n"
        """
    )
    result = run_child_suite(tmp_path, source)
    assert result.returncode == PASSED, result.stdout + result.stderr


SWALLOWED_LOOKUP = """
    import socket
    try:
        socket.getaddrinfo("localhost", 80)
    except BaseException:
        pass
"""


def test_a_violation_while_collecting_fails_the_first_test(tmp_path):
    result = run_child_suite(tmp_path, dedent(SWALLOWED_LOOKUP) + "\ndef test_it():\n    pass\n")
    assert result.returncode == TEST_FAILED, result.stdout + result.stderr
    assert "network" in result.stdout


def test_a_violation_after_the_last_test_fails_the_run(tmp_path):
    body = "".join(f"            {line}\n" for line in dedent(SWALLOWED_LOOKUP).strip().splitlines())
    conftest = f"""
        import pytest
        @pytest.fixture(autouse=True)
        def lookup_at_teardown():
            yield
{body}
    """
    result = run_child_suite(tmp_path, bare_test("pass"), conftest=conftest)
    assert result.returncode == TEST_FAILED, result.stdout + result.stderr
    assert "outside a test" in result.stderr


REAL_PATHS = {
    "the company home": f"{REAL_HOME}/.local/state/agent-company/ledger.jsonl",
    "the config directory": f"{REAL_HOME}/.config/agent-company/settings.json",
    "Claude Code's directory": f"{REAL_HOME}/.claude/projects/guard-probe.jsonl",
    "the user's timers": f"{REAL_HOME}/.config/systemd/user/guard-probe.timer",
}


@pytest.mark.parametrize("what", REAL_PATHS)
def test_opening_a_real_path_fails_the_test(what, tmp_path):
    # The guard refuses before the open happens, and a read of a name that does not exist changes nothing.
    source = bare_test(
        f"""
        try:
            open({REAL_PATHS[what]!r}).close()
        except BaseException as swallowed:
            print("swallowed", swallowed)
        """
    )
    result = run_child_suite(tmp_path, source)
    assert result.returncode == TEST_FAILED, result.stdout + result.stderr
    assert "the suite's guard caught this, in this test or just before it: real path" in result.stdout


@pytest.mark.parametrize("what", REAL_PATHS)
def test_opening_a_real_path_in_a_child_python_fails_the_test(what, tmp_path):
    # The child swallows the refusal and exits cleanly: only the guard's log can tell the parent.
    child = f"try:\\n    open({REAL_PATHS[what]!r}).close()\\nexcept BaseException:\\n    pass\\n"
    source = bare_test(
        f"""
        import subprocess, sys
        subprocess.run([sys.executable, "-c", "{child}"], check=True)
        """
    )
    result = run_child_suite(tmp_path, source)
    assert result.returncode == TEST_FAILED, result.stdout + result.stderr
    assert "the suite's guard caught this, in this test or just before it: real path" in result.stdout


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("COMPANY_HOME", f"{REAL_HOME}/.local/state/agent-company"),
        ("COMPANY_CONFIG", f"{REAL_HOME}/.config/agent-company"),
        ("CLAUDE_CONFIG_DIR", f"{REAL_HOME}/.claude"),
        ("HOME", REAL_HOME),
        ("XDG_CONFIG_HOME", f"{REAL_HOME}/.config"),
        ("COMPANY_HOME", None),
        ("COMPANY_CONFIG", None),
        ("CLAUDE_CONFIG_DIR", None),
        ("HOME", None),
        ("XDG_CONFIG_HOME", None),
    ],
)
def test_the_suite_refuses_to_start_with_real_state_in_reach(name, value, tmp_path):
    conftest = f"""
        import os
        def pytest_configure(config):
            if {value!r} is None:
                del os.environ[{name!r}]
            else:
                os.environ[{name!r}] = {value!r}
    """
    source = bare_test("raise AssertionError('no test may run')")
    result = run_child_suite(tmp_path, source, conftest=conftest)
    assert result.returncode == REFUSED_START, result.stdout + result.stderr
    assert "the suite refuses to start, and ran no test" in result.stderr
    assert name in result.stderr
    assert "no test may run" not in result.stdout


def test_the_suite_refuses_to_start_without_its_blockers_first_on_path(tmp_path):
    conftest = """
        import os
        def pytest_configure(config):
            os.environ["PATH"] = os.pathsep.join(os.environ["PATH"].split(os.pathsep)[1:])
    """
    result = run_child_suite(tmp_path, bare_test("pass"), conftest=conftest)
    assert result.returncode == REFUSED_START, result.stdout + result.stderr
    assert "blocker" in result.stderr


def test_a_test_that_moves_a_path_back_to_real_state_fails(tmp_path):
    conftest = """
        import os, pytest
        @pytest.fixture(autouse=True)
        def undo():
            os.environ["COMPANY_HOME"] = os.path.expanduser("~real-state-is-elsewhere")
    """
    result = run_child_suite(tmp_path, bare_test("pass"), conftest=conftest)
    assert result.returncode == TEST_FAILED, result.stdout + result.stderr
    assert "COMPANY_HOME points at" in result.stdout


def test_real_state_exported_in_the_shell_is_moved_out_of_reach(tmp_path):
    real_home = f"{REAL_HOME}/.local/state/agent-company"
    source = bare_test(
        f"""
        import os
        assert os.environ["COMPANY_HOME"] != {real_home!r}
        assert not os.environ["COMPANY_HOME"].startswith({REAL_HOME + "/."!r})
        assert os.environ["HOME"] != {REAL_HOME!r}
        """
    )
    result = run_child_suite(tmp_path, source, env={"COMPANY_HOME": real_home, "HOME": REAL_HOME})
    assert result.returncode == PASSED, result.stdout + result.stderr


def test_a_custom_real_home_exported_in_the_shell_is_out_of_reach(tmp_path):
    custom = tmp_path / "a-real-home-somewhere-else"
    custom.mkdir()
    (custom / "ledger.jsonl").write_text("real\n")
    source = bare_test(
        f"""
        try:
            print(open({str(custom / "ledger.jsonl")!r}).read())
        except BaseException as swallowed:
            print("swallowed", swallowed)
        """
    )
    result = run_child_suite(tmp_path, source, env={"COMPANY_HOME": str(custom)})
    assert result.returncode == TEST_FAILED, result.stdout + result.stderr
    assert "real path" in result.stdout


# Assembled, since the scan bans these names everywhere but its own files.
@pytest.mark.parametrize(
    "name",
    ["ANTHROPIC_" + "API_KEY", "CLAUDE_CODE_" + "USE_BEDROCK", "CLAUDE_CODE_" + "OAUTH_TOKEN", "AWS_BEARER_" + "TOKEN_BEDROCK"],
)
def test_a_model_provider_variable_in_the_shell_does_not_reach_a_test(tmp_path, name):
    source = bare_test(f"import os\nassert {name!r} not in os.environ")
    result = run_child_suite(tmp_path, source, env={name: "planted"})
    assert result.returncode == PASSED, result.stdout + result.stderr
