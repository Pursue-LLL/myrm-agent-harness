"""Line-level regex filter for bash_process_tool output polling.

[INPUT]
- None (stdlib only)

[OUTPUT]
- filter_output_lines: Apply optional regex per line

[POS]
Pure helper for bash_process_tool output action — optional per-line regex filter on poll snapshots.
"""

from __future__ import annotations

import re

_MAX_FILTER_PATTERN_LEN = 256


def compile_output_filter(pattern: str) -> re.Pattern[str]:
    """Compile user-supplied filter regex or raise ValueError."""
    if len(pattern) > _MAX_FILTER_PATTERN_LEN:
        raise ValueError(f"filter pattern exceeds {_MAX_FILTER_PATTERN_LEN} characters")
    return re.compile(pattern)


def filter_output_lines(lines: list[str], pattern: re.Pattern[str]) -> list[str]:
    """Return only lines matching pattern."""
    if not lines:
        return []
    return [line for line in lines if pattern.search(line)]


__all__ = ["compile_output_filter", "filter_output_lines"]
