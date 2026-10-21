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
from myrm_agent_harness.core.security.shell_wrapper_peel import (
    TRANSPARENT_WRAPPERS,
    unwrap_transparent_wrapper,
)

# A pattern approved for ``npm test`` must not cover ``npm test\nrm -rf x``, ``npm test & rm x``, ``npm test > ~/.bashrc``
# or ``npm test $(rm x)``: every character below ends, redirects or rewrites the command when the shell interprets it.
_COMPOUND_CHARS = frozenset(";|&\n\r`()<>" + UNTERMINATED)
# Redirects that only merge or discard output, as separate words: ``2>&1``, ``>&2``, ``>/dev/null``, ``&>/dev/null``.
_HARMLESS_REDIRECT_RE = re.compile(r"(?<!\S)(?:[12]?>&[12]|(?:[12]|&)?>>?/dev/null|</dev/null)(?!\S)")
_ASSIGNMENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
# ``time time time npm test`` is valid shell; the bound keeps a long chain from looping without end.
_MAX_WRAPPER_DEPTH = 4


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


def _starts_with_wrapper(command: str) -> bool:
    """Whether the command as written begins with a transparent wrapper (assignments skipped)."""
    words = _split_assignments(command.split())
    return bool(words) and words[0].rsplit("/", 1)[-1] in TRANSPARENT_WRAPPERS


def _inner_command(command: str) -> str | None:
    """The command a transparent wrapper runs, so a pattern covers the command and not the wrapper it rode in on.

    ``timeout 30 pytest -q`` becomes ``pytest -q``; deriving ``timeout 30 *`` instead would auto-approve
    ``timeout 30 rm -rf /`` on the strength of a ``pytest`` approval. None means the wrapper was not peeled:
    a form that is not understood, or one that runs nothing (``timeout 5``, ``command -v git``), where the
    command as written is not a safe basis for a grant.
    """
    words = _split_assignments(command.split())
    depth = 0
    while words and depth < _MAX_WRAPPER_DEPTH:
        base = words[0].rsplit("/", 1)[-1]
        if base not in TRANSPARENT_WRAPPERS:
            break
        inner = unwrap_transparent_wrapper(base, words[1:])
        if not inner:
            return None
        words = inner
        depth += 1
    return " ".join(words) or None


def _split_assignments(words: list[str]) -> list[str]:
    """Drop the leading ``NAME=value`` words that only set variables for the command that follows."""
    index = 0
    while index < len(words) and _ASSIGNMENT_RE.match(words[index]):
        index += 1
    return words[index:]


def _pattern_base(command: str) -> str | None:
    """The text a pattern is derived from, or None when the command cannot safely carry one."""
    if not _starts_with_wrapper(command):
        return command
    return _inner_command(command)


def derive_command_pattern(command: str) -> str | None:
    """Derive a conservative glob pattern from a single-segment shell command."""
    normalized = command.strip()
    if not normalized or is_compound_shell_command(normalized):
        return None
    base = _pattern_base(normalized)
    if not base:
        return None
    try:
        tokens = shlex.split(base, posix=True)
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
    base = _pattern_base(normalized_command)
    if base is None:
        return False
    return fnmatchcase(base, trimmed_pattern)


def extract_shell_command(tool_args: dict[str, object] | None) -> str | None:
    """Extract shell command text from bash tool arguments."""
    if not tool_args:
        return None
    command = str(tool_args.get("command", "") or tool_args.get("code", "")).strip()
    return command or None
