"""Unified Python Code Extractor for Bash Commands.

Single-source extractor for all Python-from-bash extraction needs.
Quote-aware parsing prevents greedy-regex extraction errors.

[INPUT]
- (none)

[OUTPUT]
- extract_python_from_bash: Extract Python code from bash commands (quote-aware).
- extract_python_from_pipe_stdin: Extract Python fed via ``quoted_payload | python3`` stdin.
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


def extract_python_from_pipe_stdin(command: str) -> str | None:
    """Extract Python source piped to bare ``python3`` / ``python`` on stdin.

    Matches patterns like ``printf 'import x' | python3`` where the left segment
    holds a quoted script payload and the right segment is stdin-only python
    (no ``-c``, no ``.py`` path). Returns ``None`` when no such surface exists.
    """
    segments = _split_pipe_segments(command)
    if len(segments) < 2:
        return None
    if not _is_bare_stdin_python_receiver(segments[-1]):
        return None
    for feeder in reversed(segments[:-1]):
        payload = _extract_feeder_quoted_payload(feeder)
        if payload is not None:
            return payload
        payload = _extract_feeder_unquoted_payload(feeder)
        if payload is not None:
            return payload
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

_BARE_PYTHON_BIN_RE = re.compile(r"^python3?\b", re.IGNORECASE)


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


def _split_pipe_segments(command: str) -> list[str]:
    """Split on unquoted ``|`` pipeline operators."""
    segments: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    index = 0
    length = len(command)

    while index < length:
        char = command[index]
        if char == "'" and not in_double:
            in_single = not in_single
            current.append(char)
            index += 1
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            current.append(char)
            index += 1
            continue
        if char == "\\" and in_double and index + 1 < length:
            current.append(char)
            current.append(command[index + 1])
            index += 2
            continue
        if char == "|" and not in_single and not in_double:
            segments.append("".join(current))
            current = []
            index += 1
            continue
        current.append(char)
        index += 1

    segments.append("".join(current))
    return segments


def _is_bare_stdin_python_receiver(segment: str) -> bool:
    """True when *segment* is ``python3`` / ``python`` reading stdin (no ``-c``/``.py``)."""
    stripped = segment.strip()
    if not stripped or not _BARE_PYTHON_BIN_RE.match(stripped):
        return False
    if re.search(r"\s-c\b", stripped, re.IGNORECASE):
        return False
    if re.search(r"\.py\b", stripped, re.IGNORECASE):
        return False
    if re.search(r"\s-m\b", stripped, re.IGNORECASE):
        return False
    return True


def _extract_feeder_quoted_payload(segment: str) -> str | None:
    """Return the first quote-delimited payload in a pipe feeder segment."""
    for quote in ('"', "'"):
        start = segment.find(quote)
        if start < 0:
            continue
        payload = _scan_quoted(segment[start + 1 :], quote)
        if payload is not None:
            return payload
    return None


def _extract_feeder_unquoted_payload(segment: str) -> str | None:
    """Return unquoted ``echo``/``printf`` body used as stdin script payload."""
    stripped = segment.strip()
    for command in ("echo", "printf"):
        prefix = f"{command} "
        if not stripped.startswith(prefix):
            continue
        rest = stripped[len(prefix) :].strip()
        while rest.startswith("-") and " " in rest:
            _, rest = rest.split(" ", 1)
            rest = rest.strip()
        if not rest or rest[0] in ('"', "'"):
            return None
        return rest
    return None
