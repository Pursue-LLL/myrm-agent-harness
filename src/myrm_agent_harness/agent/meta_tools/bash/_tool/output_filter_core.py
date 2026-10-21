"""Line-level regex filter for bash_process_tool output polling.

[INPUT]
- None (stdlib only)

[OUTPUT]
- compile_output_filter: Compile stripped regex with re.IGNORECASE
- filter_output_lines: Apply optional regex per line

[POS]
Pure helper for bash_process_tool output action — optional per-line regex filter on poll snapshots.
"""

from __future__ import annotations

import re

_MAX_FILTER_PATTERN_LEN = 256


def compile_output_filter(pattern: str) -> re.Pattern[str]:
    """Compile user-supplied filter regex (case-insensitive) or raise ValueError."""
    cleaned = pattern.strip()
    if not cleaned:
        raise ValueError("filter pattern cannot be empty")
    if len(cleaned) > _MAX_FILTER_PATTERN_LEN:
        raise ValueError(f"filter pattern exceeds {_MAX_FILTER_PATTERN_LEN} characters")
    return re.compile(cleaned, re.IGNORECASE)


def filter_output_lines(lines: list[str], pattern: re.Pattern[str]) -> list[str]:
    """Return only lines matching pattern."""
    if not lines:
        return []
    return [line for line in lines if pattern.search(line)]


__all__ = ["compile_output_filter", "filter_output_lines"]
