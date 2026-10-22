import pytest

from app.security.sandbox import CommandSandbox
from app.security.workspace import WorkspacePolicy


def sandbox(tmp_path):
    return CommandSandbox(WorkspacePolicy(str(tmp_path)))


def test_allowlisted_command_is_accepted(tmp_path):
    assert sandbox(tmp_path).inspect("python --version")["status"] == "ok"


def test_unlisted_command_is_refused(tmp_path):
    result = sandbox(tmp_path).inspect("curl http://example.com")
    assert result["status"] == "not_allowlisted"
    assert result["program"] == "curl"


def test_blocklist_era_command_is_refused_by_default(tmp_path):
    # Phase 2 relied on a blocklist; an allowlist refuses these without naming them.
    for command in ("format C:", "shutdown /s", "diskpart", r"reg add HKLM\Software /v y"):
        assert sandbox(tmp_path).inspect(command)["status"] == "not_allowlisted"


@pytest.mark.parametrize(
    "command",
    [
        "python --version | findstr 3",
        "python --version && whoami",
        "python -c pass; whoami",
        "python -c $(whoami)",
        "echo hi > out.txt",
    ],
)
def test_shell_syntax_is_refused(tmp_path, command):
    assert sandbox(tmp_path).inspect(command)["status"] == "shell_syntax_refused"


def test_path_traversal_in_program_name_is_refused(tmp_path):
    # Basename matching must not let an absolute path smuggle in a binary.
    result = sandbox(tmp_path).inspect(r"C:\Windows\System32\curl.exe --help")
    assert result["status"] == "not_allowlisted"


def test_empty_command_is_refused(tmp_path):
    assert sandbox(tmp_path).inspect("   ")["status"] == "missing_command"


def test_run_executes_and_captures_output(tmp_path):
    result = sandbox(tmp_path).run("python -c \"print('sandbox-ok')\"")
    assert result["status"] == "completed"
    assert result["exit_code"] == 0
    assert "sandbox-ok" in result["stdout"]


def test_run_reports_nonzero_exit(tmp_path):
    result = sandbox(tmp_path).run("python -c \"raise SystemExit(3)\"")
    assert result["status"] == "completed"
    assert result["exit_code"] == 3


def test_run_enforces_timeout(tmp_path):
    result = sandbox(tmp_path).run("python -c \"import time; time.sleep(30)\"", timeout=2)
    assert result["status"] == "timeout"


def test_run_uses_workspace_as_cwd(tmp_path):
    result = sandbox(tmp_path).run("python -c \"import os; print(os.getcwd())\"")
    assert str(tmp_path.resolve()).lower() in result["stdout"].strip().lower()


def test_run_does_not_inherit_host_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_TEST_SECRET", "leaked")
    result = sandbox(tmp_path).run(
        "python -c \"import os; print(os.environ.get('AGENT_TEST_SECRET', 'absent'))\""
    )
    assert "absent" in result["stdout"]
