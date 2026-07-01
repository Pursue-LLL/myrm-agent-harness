"""Exit-code semantic interpretation for bash tool output.

[INPUT]
- None (pure regex + lookup tables)

[OUTPUT]
- interpret_exit_code: Map (command, exit_code) to human-readable note

[POS]
Prevents the LLM from wasting turns on non-erroneous exit codes (grep=1, etc.).
"""

from __future__ import annotations

import re

_RE_SHELL_SPLIT = re.compile(r"\s*(?:\|\||&&|[|;])\s*")

_EXIT_CODE_SEMANTICS: dict[str, dict[int, str]] = {
    "grep": {1: "No matches found (not an error)"},
    "egrep": {1: "No matches found (not an error)"},
    "fgrep": {1: "No matches found (not an error)"},
    "rg": {1: "No matches found (not an error)"},
    "ag": {1: "No matches found (not an error)"},
    "ack": {1: "No matches found (not an error)"},
    "diff": {1: "Files differ (expected, not an error)"},
    "colordiff": {1: "Files differ (expected, not an error)"},
    "find": {1: "Some directories were inaccessible (partial results may still be valid)"},
    "test": {1: "Condition evaluated to false (expected, not an error)"},
    "[": {1: "Condition evaluated to false (expected, not an error)"},
    "curl": {
        6: "Could not resolve host",
        7: "Failed to connect to host",
        22: "HTTP response code indicated error (e.g. 404, 500)",
        28: "Operation timed out",
    },
    "pytest": {
        1: "Some tests failed",
        2: "Test execution was interrupted",
        5: "No tests were collected",
    },
    "python": {1: "Script exited with error"},
    "ssh": {255: "Connection failed"},
    "scp": {255: "Connection failed"},
    "which": {1: "Command not found (not an error)"},
    "command": {1: "Command not found (not an error)"},
    "cmp": {1: "Files differ (expected, not an error)"},
}

_SIGNAL_NAMES: dict[int, str] = {
    2: "SIGINT",
    6: "SIGABRT",
    9: "SIGKILL",
    11: "SIGSEGV",
    13: "SIGPIPE",
    15: "SIGTERM",
}

_GIT_EXIT_CODE_SEMANTICS: dict[str, dict[int, str]] = {
    "diff": {1: "Files have differences (not an error)"},
    "grep": {1: "No matches found (not an error)"},
    "log": {1: "No commits matched (not an error)"},
    "stash": {1: "Nothing to stash (not an error)"},
    "branch": {1: "Branch not found or already exists"},
}


def interpret_exit_code(command: str, exit_code: int) -> str | None:
    """Return a human-readable note when a non-zero exit code is non-erroneous."""
    if exit_code == 0:
        return None

    segments = _RE_SHELL_SPLIT.split(command)
    last_segment = (segments[-1] if segments else command).strip()

    words = last_segment.split()
    base_cmd = ""
    for w in words:
        if "=" in w and not w.startswith("-"):
            continue
        base_cmd = w.rsplit("/", 1)[-1]
        break

    if not base_cmd:
        return None

    if base_cmd == "git":
        subcmd = ""
        found_git = False
        for w in words:
            if "=" in w and not w.startswith("-"):
                continue
            if not found_git:
                if w.rsplit("/", 1)[-1] == "git":
                    found_git = True
                continue
            if not w.startswith("-"):
                subcmd = w
                break
        sub_semantics = _GIT_EXIT_CODE_SEMANTICS.get(subcmd)
        if sub_semantics and exit_code in sub_semantics:
            return sub_semantics[exit_code]
        return None

    cmd_semantics = _EXIT_CODE_SEMANTICS.get(base_cmd)
    if cmd_semantics and exit_code in cmd_semantics:
        return cmd_semantics[exit_code]

    if exit_code > 128:
        signal_num = exit_code - 128
        signal_name = _SIGNAL_NAMES.get(signal_num)
        if signal_name:
            return f"Process terminated by {signal_name} (signal {signal_num})"

    return None
