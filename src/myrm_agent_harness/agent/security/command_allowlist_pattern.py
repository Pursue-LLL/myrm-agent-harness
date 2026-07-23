"""Shell command pattern helpers for allow-always pattern scope.

[INPUT]
- Raw shell command strings from bash_code_execute_tool

[OUTPUT]
- is_compound_shell_command(): detect chained shell operators
- `derive_command_pattern()` / `matches_command_pattern()` / `DERIVE_PATTERN_PARITY_VECTORS`（与 frontend vitest 对齐）

[POS]
Layer 4 allowlist extension (C-minimal). Pattern entries never auto-approve
compound shell commands; DENY rules in evaluate_tool_call still win first.
"""

from __future__ import annotations

import re
import shlex
from fnmatch import fnmatchcase

_COMPOUND_OPERATOR_RE = re.compile(
    r"""
    (?:
        && |
        \|\| |
        \|\s |
        \|\s*$ |
        ;(?!\s*$)
    )
    """,
    re.VERBOSE,
)


def is_compound_shell_command(command: str) -> bool:
    """Return True when the command chains multiple shell segments."""
    stripped = command.strip()
    if not stripped:
        return False
    return bool(_COMPOUND_OPERATOR_RE.search(stripped))


def derive_command_pattern(command: str) -> str | None:
    """Derive a conservative glob pattern from a single-segment shell command."""
    normalized = command.strip()
    if not normalized or is_compound_shell_command(normalized):
        return None
    try:
        tokens = shlex.split(normalized, posix=True)
    except ValueError:
        return None
    if not tokens:
        return None
    if len(tokens) >= 2:
        return f"{tokens[0]} {tokens[1]} *"
    return f"{tokens[0]} *"


def matches_command_pattern(pattern: str, command: str) -> bool:
    """Match a stored glob pattern against a shell command."""
    trimmed_pattern = pattern.strip()
    normalized_command = command.strip()
    if not trimmed_pattern or not normalized_command:
        return False
    if is_compound_shell_command(normalized_command):
        return False
    return fnmatchcase(normalized_command, trimmed_pattern)


def extract_shell_command(tool_args: dict[str, object] | None) -> str | None:
    """Extract shell command text from bash tool arguments."""
    if not tool_args:
        return None
    command = str(tool_args.get("command", "") or tool_args.get("code", "")).strip()
    return command or None
