"""Shared shell command parsing primitives.

Both security guards reason about the same shell surface: the `myrm_tools`
import guard and the path protection guard each need to see *inside* an inline
``sh -c`` / ``bash -c`` script. Keeping the extraction in one place stops the two
guards from drifting apart on quoting rules — a gap one of them would treat as a
literal string and the other as executable code.

[INPUT]
- (none — pure parsing module)

[OUTPUT]
- SHELL_C_CMD_RE: re.Pattern[str] — matches the `bash|sh … -c` prefix
- extract_shell_c_payload(command) -> str | None — quote-aware inner script, or None

[POS]
Shared shell parsing. No security policy.
"""

from __future__ import annotations

import re

__all__ = ("SHELL_C_CMD_RE", "extract_shell_c_payload")

SHELL_C_CMD_RE = re.compile(
    r"(?:^|[\s;&|])(?:bash|sh|/bin/bash|/bin/sh)\s+(?:-[^\s]+\s+)*-c\s+",
    re.MULTILINE,
)


def extract_shell_c_payload(command: str) -> str | None:
    """Return the inner script of a ``bash -c`` / ``sh -c`` invocation.

    Quote-aware: the payload ends at the closing quote of the same character that
    opened it, honouring backslash escapes, so a payload containing the other quote
    style is not truncated. Returns None when the command has no ``-c`` script or
    the script is not quoted (the shell would word-split it, so there is no single
    payload to inspect).
    """
    match = SHELL_C_CMD_RE.search(command)
    if match is None:
        return None

    rest = command[match.end() :]
    if not rest:
        return None

    quote = rest[0]
    if quote not in ('"', "'"):
        return None

    escaped = False
    for index, char in enumerate(rest[1:], start=1):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == quote:
            return rest[1:index]
    return None
