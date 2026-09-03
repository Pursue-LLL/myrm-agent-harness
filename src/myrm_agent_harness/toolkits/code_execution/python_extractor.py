"""Unified Python Code Extractor for Bash Commands.

Single-source extractor for all Python-from-bash extraction needs.
Quote-aware parsing prevents greedy-regex extraction errors.

[INPUT]
- (none)

[OUTPUT]
- extract_python_from_bash: Extract Python code from bash commands (quote-aware).
- extract_python_from_pipe_stdin: Extract Python fed via ``quoted_payload | python3`` stdin.
- extract_cat_py_paths_from_pipe_feeders: Resolve ``.py`` paths from ``cat`` pipe feeder segments.
- validate_python_syntax: Pre-check extracted Python via ast.parse.
- SKILL_IMPORT_RE: Compiled pattern for ``from skills.xxx_skill import`` detection.
- TOOLS_IMPORT_RE: Compiled pattern for ``from tools.xxx import`` detection.

[POS]
Centralised Python extraction with quote-aware parsing, heredoc support, and
ast.parse pre-validation.  Used by SkillExecutor, CodeTypeDetector,
BaseExecutor, and PTC verifier.
"""

from __future__ import annotations

import re


def extract_python_from_bash(command: str) -> str | None:
    """Extract Python code from a bash command string.

    Supports (in priority order):
    1. ``python3 -c "..."`` / ``python3 -c '...'`` — quote-aware extraction
    2. ``python3 <<EOF ... EOF`` — heredoc
    3. ``cat > path <<EOF ... EOF`` — shell heredoc file write wrappers
    4. Raw Python containing ``from skills.`` / ``from tools.`` imports (non-shell)

    Returns the extracted Python source or ``None`` if no Python is detected.
    """
    code = _extract_python_c(command)
    if code is not None:
        return code

    code = _extract_heredoc(command)
    if code is not None:
        return code

    code = _extract_cat_heredoc(command)
    if code is not None:
        return code

    if SKILL_IMPORT_RE.search(command) or TOOLS_IMPORT_RE.search(command):
        if _looks_like_shell_wrapper(command):
            return None
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


def extract_cat_py_paths_from_pipe_feeders(command: str) -> list[str]:
    """Return ``.py`` file refs from ``cat path.py | python3``-style pipe feeders.

    Only applies when the final segment is bare stdin ``python3`` / ``python``
    (no ``-c``, ``-m``, or ``.py`` path on the receiver).
    """
    segments = _split_pipe_segments(command)
    if len(segments) < 2 or not _is_bare_stdin_python_receiver(segments[-1]):
        return []
    paths: list[str] = []
    for feeder in segments[:-1]:
        match = _CAT_PY_PATH_RE.search(feeder)
        if match is not None:
            paths.append(match.group(1))
    return list(dict.fromkeys(paths))


def _wrap_top_level_async_code(code: str) -> str:
    """Wrap code with an async function while keeping file-level headers at the top."""
    import textwrap

    header_lines: list[str] = []
    body_lines: list[str] = []
    in_header = True
    for line in code.splitlines():
        stripped = line.strip()
        if in_header:
            if not stripped or stripped.startswith("#") or stripped.startswith("from __future__ import"):
                header_lines.append(line)
                continue
            in_header = False
        body_lines.append(line)

    header_part = "\n".join(header_lines)
    body_part = textwrap.indent("\n".join(body_lines), "    ")
    return f"{header_part}\nasync def __syntax_check__():\n{body_part}\n"


def validate_python_syntax(code: str) -> str | None:
    """Return ``None`` if *code* is valid Python, otherwise a human-readable error.

    Supports top-level await, async for, and async with syntax (used in interactive execution
    and Jupyter-style PTC scripts), falling back to wrapped async function check if top-level
    async constructs are detected.
    """
    try:
        compile(code, "<string>", "exec")
        return None
    except SyntaxError as exc:
        # If the syntax error is caused by top-level async constructs ('await', 'async for', 'async with' outside function),
        # re-validate wrapped in an async function to allow valid top-level async code while preserving __future__ headers.
        msg = str(exc.msg).lower()
        if ("outside" in msg or "function" in msg) and any(
            kw in msg for kw in ("'await'", "'async for'", "'async with'", "await", "async for", "async with")
        ) and "return" not in msg:
            try:
                wrapped = _wrap_top_level_async_code(code)
                compile(wrapped, "<string>", "exec")
                return None
            except SyntaxError:
                pass

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
    r"python3?\s+<<-?\s*['\"]?(\w+)['\"]?\s*\n(.+?)\n\1\b",
    re.DOTALL,
)

_CAT_HEREDOC_RE = re.compile(
    r"^\s*cat\s+>\s+\S+\s+<<-?\s*['\"]?(\w+)['\"]?\s*\n(.+?)\n\1\b",
    re.DOTALL | re.MULTILINE,
)

_SHELL_WRAPPER_PREFIXES = (
    "cat ",
    "echo ",
    "bash ",
    "sh ",
    "/bin/bash",
    "/bin/sh",
    "cd ",
    "export ",
    "pwd",
    "ls ",
    "mkdir ",
    "rm ",
    "cp ",
    "mv ",
)

_BARE_PYTHON_BIN_RE = re.compile(r"^python3?\b", re.IGNORECASE)

_CAT_PY_PATH_RE = re.compile(r"\bcat\s+([^\s|]+\.py)\b", re.IGNORECASE)


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
    match = _HEREDOC_RE.search(command)
    return match.group(2).strip() if match else None


def _extract_cat_heredoc(command: str) -> str | None:
    """Extract Python body from ``cat > path << EOF ... EOF`` shell wrappers.

    Returns the body only when it parses as valid Python.  Non-Python heredocs
    (e.g. writing YAML or shell config files) fall back to bash execution so the
    file is written verbatim instead of being rejected by Python syntax checks.
    """
    match = _CAT_HEREDOC_RE.search(command)
    if match is None:
        return None
    body = match.group(2).strip()
    if not body:
        return None
    if validate_python_syntax(body) is not None:
        return None
    return body


def _looks_like_shell_wrapper(command: str) -> bool:
    """True when the command starts with shell syntax rather than raw Python."""
    stripped = command.lstrip()
    if not stripped:
        return False
    first_line = stripped.split("\n", 1)[0].strip()
    if "<<" in first_line:
        return True
    lowered = first_line.lower()
    return any(lowered.startswith(prefix) for prefix in _SHELL_WRAPPER_PREFIXES)


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
    return not re.search(r"\s-m\b", stripped, re.IGNORECASE)


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
