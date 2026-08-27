"""Output-pattern diagnostic failure hints and masked-success detection for bash tools.

[INPUT]
- command: str - command string executed
- exit_code: int - process return code
- output: str - combined execution output text

[OUTPUT]
- annotate_failure: Map (command, exit_code, output) to actionable recovery hint
- annotate_masked_success: Detect exit 0 that masks an upstream failure

[POS]
Heuristic diagnostic guidance layer for bash tool execution. Non-intrusive runtime
annotations that prevent LLMs from wasting retry turns on well-known error shapes.
"""

from __future__ import annotations

import re
from collections.abc import Callable

_SCAN_CHARS = 4000


def _hint_gh_unknown_json_field(command: str, output: str) -> str | None:
    m = re.search(r'Unknown JSON field: "?(\w+)', output)
    if not m:
        return None
    return (
        f"The installed gh does not support the JSON field '{m.group(1)}'. "
        "The valid field list is printed in the output above — retry using "
        "only fields from that list."
    )


def _hint_git_clone_issue(command: str, output: str) -> str | None:
    if "git clone" not in command:
        return None
    if (
        "RPC failed" in output
        or "early EOF" in output
        or "The remote end hung up unexpectedly" in output
        or "timed out" in output
        or "github.com" in command
    ):
        return (
            "'git clone' failed or timed out. For large repositories, consider using curl to download "
            "the tarball archive or using a shallow clone (`git clone --depth 1 ...`)."
        )
    return None


def _hint_git_no_upstream(command: str, output: str) -> str | None:
    if "has no upstream branch" in output or "set-upstream" in output:
        m = re.search(r"git push --set-upstream (\S+) (\S+)", output)
        if m:
            return f"Git branch has no upstream. Run `git push -u {m.group(1)} {m.group(2)}` to publish the branch."
        return "Git branch has no upstream. Run with `-u <remote> <branch>` to set tracking."
    return None


def _hint_port_in_use(command: str, output: str) -> str | None:
    if "EADDRINUSE" in output or "address already in use" in output or "Address already in use" in output:
        m = re.search(r"(?:port|address).*?(\d{2,5})", output, re.IGNORECASE)
        port = m.group(1) if m else "the specified port"
        return (
            f"Port {port} is already in use. Check active processes with `lsof -i :{port}` "
            f"or try starting the service on an alternative port (e.g. PORT=3001)."
        )
    return None


def _hint_command_not_found(command: str, output: str) -> str | None:
    m = re.search(r"(?:bash: line \d+: |bash: |sh: \d*:? ?|zsh: )?([\w.+-]+): command not found", output)
    if not m:
        return None
    missing = m.group(1)
    if missing == "python":
        return (
            "This environment has no bare `python` command. Please use `python3` "
            "or the virtual environment interpreter (e.g. `.venv/bin/python`)."
        )
    if missing == "pip":
        return (
            "This environment has no bare `pip` command. Please use `pip3`, "
            "`python3 -m pip`, or `.venv/bin/pip` instead."
        )
    if missing == "bun":
        return "`bun` is not installed on PATH. Check if `node`/`npm`/`pnpm` is available or install bun."
    return (
        f"`{missing}` is not installed or not on PATH. Verify with `which {missing}`; "
        "install the prerequisite or use an absolute executable path."
    )


def _hint_module_not_found(command: str, output: str) -> str | None:
    m = re.search(r"(?:ModuleNotFoundError|ImportError): No module named '?([\w.]+)", output)
    if not m:
        return None
    module_name = m.group(1)
    return (
        f"Python cannot import '{module_name}'. If using a virtual environment, activate it "
        "or execute directly via `.venv/bin/python`. If missing, install with uv / pip."
    )


def _hint_merge_conflict(command: str, output: str) -> str | None:
    if not re.search(r"^CONFLICT |Automatic merge failed|needs merge", output, re.MULTILINE):
        return None
    return (
        "Git merge conflict encountered. Inspect conflicted files with `git status`, "
        "resolve conflict markers, then stage changes with `git add` and continue."
    )


def _hint_already_exists(command: str, output: str) -> str | None:
    m = re.search(r"(?:fatal|error):.*?'([^']+)' already exists", output)
    if not m:
        return None
    return (
        f"Target '{m.group(1)}' already exists. Reuse the existing resource, "
        "choose a different identifier, or remove the stale entry first."
    )


def _hint_permission_denied(command: str, output: str) -> str | None:
    if "Permission denied" not in output and "EACCES" not in output:
        return None
    return (
        "Permission denied (EACCES). Verify file ownership/permissions (`ls -la`), "
        "ensure target directory is writable, or adjust executable permissions with `chmod +x`."
    )


_OUTPUT_HINTS: list[Callable[[str, str], str | None]] = [
    _hint_gh_unknown_json_field,
    _hint_git_clone_issue,
    _hint_git_no_upstream,
    _hint_port_in_use,
    _hint_merge_conflict,
    _hint_command_not_found,
    _hint_module_not_found,
    _hint_already_exists,
    _hint_permission_denied,
]

_EXIT_CODE_HINTS: dict[int, str] = {
    124: "Command timed out. Increase timeout parameter or run as a background task (`run_in_background=True`).",
    126: "Exit 126: File is not executable. Grant execution permissions with `chmod +x <file>` or invoke via interpreter.",
    137: "Exit 137: Process terminated by SIGKILL (commonly Out-of-Memory or external termination).",
}

_PASSTHROUGH_CONSUMERS = r"(?:tail|head|cat|tee|less|more|wc|sort|uniq)"
_MASKING_PIPE_RE = re.compile(r"(?<!\|)\|(?!\|)\s*" + _PASSTHROUGH_CONSUMERS + r"\b[^|]*$")
_MASKING_OR_RE = re.compile(r"\|\|\s*(?:echo\b|printf\b|true\b|:\s|:$)")

_READONLY_HEADS = frozenset(
    {
        "grep", "rg", "ag", "find", "ls", "cat", "head", "tail", "jq", "awk",
        "sed", "strings", "zcat", "journalctl", "dmesg", "echo", "printf",
    }
)

_FAILURE_SHAPES = re.compile(
    r"(?:"
    r"error\[E\d+\]"
    r"|error: could not compile"
    r"|error: aborting due to"
    r"|Traceback \(most recent call last\)"
    r"|(?m:^(?:=+ )?\d+ failed)"
    r"|(?m:^FAILED (?:\S+::|\S+\.py))"
    r"|compilation terminated\."
    r"|npm ERR!"
    r"|BUILD FAILED|Build FAILED"
    r"|FAILED: "
    r"|(?m:^make(?:\[\d+\])?: \*\*\*)"
    r")"
)


def _first_token(command: str) -> str:
    for tok in (command or "").strip().split():
        if "=" in tok and not tok.startswith(("=", "./", "/")):
            continue
        return tok.rsplit("/", 1)[-1]
    return ""


def annotate_masked_success(command: str, output: str) -> str | None:
    """Return a warning note when an exit-0 result likely masks an upstream failure."""
    cmd = command or ""
    window = (output or "")[:_SCAN_CHARS]
    if not cmd or not window:
        return None
    if _first_token(cmd) in _READONLY_HEADS:
        return None
    if not _FAILURE_SHAPES.search(window):
        return None
    if _MASKING_PIPE_RE.search(cmd):
        return (
            "[Masked Failure Warning] exit_code is 0 from the terminal pipeline consumer (tail/head/...), "
            "but the output contains error markers. Re-run without piping to observe the real exit code."
        )
    if _MASKING_OR_RE.search(cmd):
        return (
            "[Masked Failure Warning] exit_code is 0 from the fallback handler (|| echo/true), "
            "but the output contains error markers. Re-run bare to inspect actual status."
        )
    return None


def annotate_failure(command: str, exit_code: int, output: str) -> str | None:
    """Return an actionable diagnostic recovery hint for a failed command."""
    if exit_code == 0:
        return None
    window = (output or "")[:_SCAN_CHARS]
    if window:
        for fn in _OUTPUT_HINTS:
            try:
                hint = fn(command or "", window)
            except Exception:
                continue
            if hint:
                return hint
    return _EXIT_CODE_HINTS.get(exit_code)
