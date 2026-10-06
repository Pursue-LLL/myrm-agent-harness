"""Type definitions for session-scoped tool output spill store and bounded preview locator.

Defines spill policies, spill audit records, processed tool output wrappers,
and on-demand range slice request/result contracts.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SpillPolicy:
    """Configurable thresholds and preview limits governing tool output spill."""

    max_inline_bytes: int = 30_000
    max_inline_tokens: int = 4_000
    preview_head_lines: int = 15
    preview_tail_lines: int = 15
    base_storage_dir: str = ".myrm/spills"


@dataclass(frozen=True)
class SpillRecord:
    """Audit metadata tracking a spilled tool output artifact."""

    spill_id: str
    session_id: str
    tool_name: str
    file_path: str
    total_bytes: int
    total_lines: int
    locator_uri: str
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class SpillProcessResult:
    """Outcome of processing tool output against spill policy."""

    is_spilled: bool
    content: str
    record: SpillRecord | None = None
    bytes_saved: int = 0


@dataclass(frozen=True)
class SpillSliceRequest:
    """Request contract for retrieving an on-demand line range slice from a spilled artifact."""

    locator_uri: str
    start_line: int  # 1-indexed inclusive
    end_line: int    # 1-indexed inclusive


@dataclass(frozen=True)
class SpillSliceResult:
    """Retrieved slice of spilled content with navigation metadata."""

    locator_uri: str
    total_lines: int
    requested_start: int
    requested_end: int
    lines_returned: int
    content: str
