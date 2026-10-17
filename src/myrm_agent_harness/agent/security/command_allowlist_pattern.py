"""Shell command pattern helpers for allow-always pattern scope.

[INPUT]
- Raw shell command strings from bash_code_execute_tool
- core.security.shell_command_lexer: which characters of the command the shell interprets

[OUTPUT]
- is_compound_shell_command(): detect anything beyond one plain command (chaining, redirects, substitution, grouping)
- `derive_command_pattern()` / `matches_command_pattern()` / `DERIVE_PATTERN_PARITY_VECTORS`（与 frontend vitest 对齐）

[POS]
Layer 4 allowlist extension (C-minimal). Pattern entries never auto-approve
compound shell commands; DENY rules in evaluate_tool_call still win first.
"""

from __future__ import annotations

import re
import shlex
from fnmatch import fnmatchcase

from myrm_agent_harness.core.security.shell_command_lexer import UNTERMINATED, iter_syntax_chars

# A pattern approved for ``npm test`` must not cover ``npm test\nrm -rf x``, ``npm test & rm x``, ``npm test > ~/.bashrc``
# or ``npm test $(rm x)``: every character below ends, redirects or rewrites the command when the shell interprets it.
_COMPOUND_CHARS = frozenset(";|&\n\r`()<>" + UNTERMINATED)
# Redirects that only merge or discard output, as separate words: ``2>&1``, ``>&2``, ``>/dev/null``, ``&>/dev/null``.
_HARMLESS_REDIRECT_RE = re.compile(r"(?<!\S)(?:[12]?>&[12]|(?:[12]|&)?>>?/dev/null|</dev/null)(?!\S)")


def is_compound_shell_command(command: str) -> bool:
    """Return True when the command is more than one plain command.

    Chaining (``;`` ``&&`` ``|`` ``&`` line break), redirects, command substitution, grouping and text that
    cannot be parsed all count; quoted text and comments do not.
    """
    text = _HARMLESS_REDIRECT_RE.sub(" ", command.strip())
    return any(
        char in _COMPOUND_CHARS or (char == "$" and text[index + 1 : index + 2] == "(")
        for index, char in iter_syntax_chars(text)
    )


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
