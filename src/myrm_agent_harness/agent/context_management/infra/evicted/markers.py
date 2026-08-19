"""Disk storage cap marker SSOT — write template and tail probe.

[INPUT]
- (none)

[OUTPUT]
- STORAGE_CAP_MARKER_TEMPLATE, STORAGE_CAP_MARKER_RE, TAIL_PROBE_CHARS
- format_storage_cap_marker, probe_storage_cap_from_tail

[POS]
Single source for on-disk truncation marker text and regex parsing (writer + reader).
"""

from __future__ import annotations

import re

STORAGE_CAP_MARKER_TEMPLATE = (
    "\n\n[... stored copy truncated at {cap:,} chars of {original:,}; "
    "re-fetch or read a narrower URL for the remainder ...]"
)

STORAGE_CAP_MARKER_RE = re.compile(
    r"\[\.\.\. stored copy truncated at ([\d,]+) chars of ([\d,]+);",
)

TAIL_PROBE_CHARS = 512


def format_storage_cap_marker(*, cap: int, original: int) -> str:
    """Append the on-disk storage cap marker for truncated evicted content."""
    return STORAGE_CAP_MARKER_TEMPLATE.format(cap=cap, original=original)


def probe_storage_cap_from_tail(text: str) -> tuple[bool, int | None]:
    """Detect disk cap marker in a tail slice; returns (truncated, original_chars)."""
    match = STORAGE_CAP_MARKER_RE.search(text)
    if match is None:
        return False, None
    original_raw = match.group(2).replace(",", "")
    try:
        return True, int(original_raw)
    except ValueError:
        return True, None
