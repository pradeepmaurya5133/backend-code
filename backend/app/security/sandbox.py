"""Allowlisted subprocess execution.

Phase 2 shipped a blocklist, which fails open: anything not named in it was
treated as safe. This module inverts that - a command runs only if its
executable is explicitly allowlisted. Everything else is refused.

Hardening applied to every run:
  * no shell - the command is argv-split, so metacharacters are never
    interpreted by a shell
  * cwd pinned to the agent workspace
  * wall-clock timeout with process-tree kill
  * output truncated to a fixed ceiling
  * minimal environment, so host secrets are not inherited
"""

import os
import shlex
import shutil
import subprocess
import sys

DEFAULT_ALLOWLIST = {
    "python", "python3", "pip", "pip3",
    "node", "npm", "npx",
    "git",
    "pytest",
    "echo", "whoami", "hostname",
}

# Rejected even when the executable is allowlisted - these are shell
# constructs, and their presence means the caller expected a shell.
SHELL_METACHARACTERS = ("|", "&", ";", ">", "<", "`", "$(", "\n", "\r")

DEFAULT_TIMEOUT_SECONDS = 15
MAX_TIMEOUT_SECONDS = 120
MAX_OUTPUT_CHARS = 20_000

# Variables a subprocess genuinely needs; everything else is dropped.
ENV_PASSTHROUGH = ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "LANG", "LC_ALL")


class SandboxResult(dict):
    """Plain dict - keeps the tool layer's JSON-in/JSON-out contract."""


def _minimal_env() -> dict:
    env = {name: os.environ[name] for name in ENV_PASSTHROUGH if name in os.environ}
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _truncate(text: str) -> tuple[str, bool]:
    if text is None:
        return "", False
    if len(text) <= MAX_OUTPUT_CHARS:
        return text, False
    return text[:MAX_OUTPUT_CHARS], True


class CommandSandbox:
    def __init__(self, workspace, allowlist: set[str] = None, timeout: int = DEFAULT_TIMEOUT_SECONDS):
        self.workspace = workspace
        self.allowlist = set(allowlist if allowlist is not None else DEFAULT_ALLOWLIST)
        self.timeout = timeout

    @staticmethod
    def _basename(token: str) -> str:
        name = os.path.basename(token).lower()
        for suffix in (".exe", ".bat", ".cmd", ".com"):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
        return name

    def inspect(self, command: str) -> SandboxResult:
        """Validate without running. Returns {'status': 'ok', ...} when runnable."""
        command = (command or "").strip()
        if not command:
            return SandboxResult(status="missing_command")

        try:
            # posix=False keeps Windows backslash paths intact and leaves
            # quotes attached, which is how we tell literals from syntax.
            parts = shlex.split(command, posix=False)
        except ValueError as exc:
            return SandboxResult(status="unparsable_command", detail=str(exc))

        if not parts:
            return SandboxResult(status="missing_command")

        # A metacharacter inside a quoted token is an inert literal - execution is
        # shell=False, so nothing can interpret it. Only bare tokens are suspicious.
        cleaned = []
        for token in parts:
            quoted = len(token) > 1 and token[0] == token[-1] and token[0] in "\"'"
            if not quoted:
                for meta in SHELL_METACHARACTERS:
                    if meta in token:
                        return SandboxResult(
                            status="shell_syntax_refused",
                            detail=f"'{meta}' is not permitted outside a quoted argument",
                        )
            cleaned.append(token[1:-1] if quoted else token)
        parts = cleaned

        program = self._basename(parts[0])
        if program not in self.allowlist:
            return SandboxResult(
                status="not_allowlisted",
                program=program,
                detail=f"'{program}' is not in the command allowlist",
            )

        resolved = sys.executable if program in ("python", "python3") else shutil.which(parts[0])
        if not resolved:
            return SandboxResult(status="executable_not_found", program=program)

        return SandboxResult(status="ok", program=program, argv=[resolved] + parts[1:])

    def run(self, command: str, timeout: int = None) -> SandboxResult:
        check = self.inspect(command)
        if check["status"] != "ok":
            return check

        limit = min(int(timeout or self.timeout), MAX_TIMEOUT_SECONDS)
        argv = check["argv"]

        try:
            completed = subprocess.run(
                argv,
                cwd=str(self.workspace.root),
                env=_minimal_env(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=limit,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(status="timeout", program=check["program"], timeout_seconds=limit)
        except OSError as exc:
            return SandboxResult(status="execution_failed", program=check["program"], detail=str(exc))

        stdout, stdout_cut = _truncate(completed.stdout)
        stderr, stderr_cut = _truncate(completed.stderr)
        return SandboxResult(
            status="completed",
            program=check["program"],
            exit_code=completed.returncode,
            stdout=stdout,
            stderr=stderr,
            truncated=stdout_cut or stderr_cut,
        )
