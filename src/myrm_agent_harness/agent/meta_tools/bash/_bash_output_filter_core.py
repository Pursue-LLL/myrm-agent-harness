"""Line-level regex filter for bash_process_tool output polling.

[INPUT]
- None (stdlib only)

[OUTPUT]
- filter_output_lines: Apply optional regex per line

[POS]
Pure helper for bash_process_tool output action — mirrors fastclaw bash_output filter semantics.
"""

from __future__ import annotations

import re


def compile_output_filter(pattern: str) -> re.Pattern[str]:
    """Compile user-supplied filter regex or raise ValueError."""
    return re.compile(pattern)


def filter_output_lines(lines: list[str], pattern: re.Pattern[str]) -> list[str]:
    """Return only lines matching pattern."""
    if not lines:
        return []
    return [line for line in lines if pattern.search(line)]


__all__ = ["compile_output_filter", "filter_output_lines"]
