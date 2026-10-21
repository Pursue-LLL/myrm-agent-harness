"""Cron delivery guard — exact-token silent output detection.

[INPUT]
- (stdlib) re

[OUTPUT]
- is_silent_output: Returns True when agent output is token-only [SILENT] with no substantive content.
- SILENT_MARKER: Canonical silent token string.

[POS]
Cron delivery guard. Filters notification delivery for exact-token silent agent replies.
"""

from __future__ import annotations

import re

SILENT_MARKER = "[SILENT]"

_FENCE_RE = re.compile(r"^```(?:\w+)?\s*\n?(.*?)\n?```\s*$", re.DOTALL)


def _strip_markdown_fence(text: str) -> str:
    match = _FENCE_RE.match(text)
    if match:
        return match.group(1).strip()
    return text


def is_silent_output(text: str | None, marker: str = SILENT_MARKER) -> bool:
    """Return True when output is token-only silent (no substantive content).

    Matches:
    - Exact ``[SILENT]`` (optional surrounding whitespace)
    - Multiple lines each exactly ``[SILENT]``
    - Same patterns wrapped in a markdown code fence

    Does NOT match substantive replies such as ``[SILENT] nothing to report``.
    """
    if text is None:
        return False
    stripped = text.strip()
    if not stripped:
        return False

    normalized = _strip_markdown_fence(stripped)
    if normalized == marker:
        return True

    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    if not lines:
        return False
    return all(line == marker for line in lines)
