"""
[POS] myrm_agent_harness/agent/sub_agents/todo_store/sanitizer.py
[INPUT] re, unicodedata
[OUTPUT] strip_control_characters, sanitize_todo_text

Bidirectional C0/C1 control character stripping and ANSI escape sequence sanitization.
Ensures plan declarations cannot inject terminal escape sequences or poison HUD/TUI renderers.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import re

# Regex for matching ANSI escape sequences (CSI, OSC, etc.)
_ANSI_ESCAPE_RE = re.compile(
    r"""
    \x1b\[[0-?]*[ -/]*[@-~]      # CSI sequences
    | \x1b\][^\x07\x1b]*(\x07|\x1b\\) # OSC sequences
    | \x1b[@-Z\\-_]              # 2-character Fe sequences
    """,
    re.VERBOSE,
)


def strip_control_characters(text: str) -> str:
    """
    Strip all ANSI escape sequences, C0 control characters (0x00-0x1F, 0x7F),
    and C1 control characters (0x80-0x9F) from input string.
    Replaces internal illegal control characters with empty string or space.
    """
    if not text:
        return ""

    # 1. Strip ANSI escape codes
    cleaned = _ANSI_ESCAPE_RE.sub("", text)

    # 2. Filter C0 and C1 control characters
    chars: list[str] = []
    for ch in cleaned:
        code = ord(ch)
        # C0 control characters: 0x00-0x1F, 0x7F (DEL)
        # Note: In plan titles/items, we replace control characters with a space so word boundaries are safely preserved
        if 0x00 <= code <= 0x1F or code == 0x7F:
            chars.append(" ")
            continue
        # C1 control characters: 0x80-0x9F
        if 0x80 <= code <= 0x9F:
            chars.append(" ")
            continue
        chars.append(ch)

    # 3. Collapse multiple whitespace into a clean single space
    collapsed = " ".join("".join(chars).split())
    return collapsed.strip()


def sanitize_todo_text(text: str, max_length: int) -> str:
    """Sanitize text and strictly enforce maximum length bounds."""
    cleaned = strip_control_characters(text)
    if len(cleaned) > max_length:
        return cleaned[:max_length].rstrip()
    return cleaned
