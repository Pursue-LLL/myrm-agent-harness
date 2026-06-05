"""Unified Python Code Extractor for Bash Commands.

Single-source extractor for all Python-from-bash extraction needs.
Quote-aware parsing prevents greedy-regex extraction errors.

[INPUT]
- (none)

[OUTPUT]
- extract_python_from_bash: Extract Python code from bash commands (quote-aware).
- validate_python_syntax: Pre-check extracted Python via ast.parse.
- SKILL_IMPORT_RE: Compiled pattern for ``from skills.xxx_skill import`` detection.
- TOOLS_IMPORT_RE: Compiled pattern for ``from tools.xxx import`` detection.

[POS]
Centralised Python extraction with quote-aware parsing, heredoc support, and
ast.parse pre-validation.  Used by SkillExecutor, CodeTypeDetector,
BaseExecutor, and PTC verifier.
"""

from __future__ import annotations

import ast
import re


def extract_python_from_bash(command: str) -> str | None:
    """Extract Python code from a bash command string.

    Supports (in priority order):
    1. ``python3 -c "..."`` / ``python3 -c '...'`` — quote-aware extraction
    2. ``python3 <<EOF ... EOF`` — heredoc
    3. Raw Python containing ``from skills.`` / ``from tools.`` imports

    Returns the extracted Python source or ``None`` if no Python is detected.
    """
    code = _extract_python_c(command)
    if code is not None:
        return code

    code = _extract_heredoc(command)
    if code is not None:
        return code

    if SKILL_IMPORT_RE.search(command) or TOOLS_IMPORT_RE.search(command):
        return command

    return None


def validate_python_syntax(code: str) -> str | None:
    """Return ``None`` if *code* is valid Python, otherwise a human-readable error."""
    try:
        ast.parse(code)
        return None
    except SyntaxError as exc:
        parts = [f"SyntaxError: {exc.msg}"]
        if exc.lineno:
            parts.append(f"line {exc.lineno}")
        return ", ".join(parts)


SKILL_IMPORT_RE = re.compile(r"from\s+(?:skills\.)?([\w]+_skill)(?:\.\w+)?\s+import")
TOOLS_IMPORT_RE = re.compile(r"(?:from\s+tools\.\w+\s+import|import\s+tools\.)")

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_PYTHON_CMD_RE = re.compile(r"python3?\s+-c\s+")

_HEREDOC_RE = re.compile(
    r"python3?\s+<<\s*['\"]?EOF['\"]?\s*\n(.+?)\nEOF",
    re.DOTALL,
)


def _extract_python_c(command: str) -> str | None:
    """Quote-aware extraction from ``python -c`` commands."""
    m = _PYTHON_CMD_RE.search(command)
    if m is None:
        return None

    rest = command[m.end() :]
    if not rest:
        return None

    quote = rest[0]
    if quote not in ('"', "'"):
        return None

    return _scan_quoted(rest[1:], quote)


def _scan_quoted(text: str, quote: str) -> str | None:
    """Walk *text* respecting backslash escapes and return content up to the
    unescaped closing *quote*.  Returns ``None`` if no valid close is found."""
    buf: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            buf.append(text[i + 1])
            i += 2
            continue
        if ch == quote:
            return "".join(buf)
        buf.append(ch)
        i += 1
    return "".join(buf) if buf else None


def _extract_heredoc(command: str) -> str | None:
    m = _HEREDOC_RE.search(command)
    return m.group(1) if m else None
