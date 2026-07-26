"""Streaming readers for UECD evicted files on disk.

[INPUT]
- (none)

[OUTPUT]
- count_lines_in_text, read_evicted_line_range, read_evicted_file_meta

[POS]
Pure I/O helpers for paginated GUI/API reads of `.context/.../evicted/` files.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class EvictedFileMeta:
    """On-disk stats for an evicted output file."""

    stored_chars: int
    total_lines: int


@dataclass(frozen=True, slots=True)
class EvictedLineRange:
    """A slice of evicted file lines plus file-wide totals."""

    content: str
    total_lines: int
    stored_chars: int
    offset: int
    limit: int


def count_lines_in_text(text: str) -> int:
    """Return a line count consistent with line-oriented eviction reads."""
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def read_evicted_file_meta(path: str | Path) -> EvictedFileMeta:
    """Read byte size and line count for an evicted file."""
    resolved = Path(path)
    stored_chars = int(resolved.stat().st_size)
    total_lines = 0
    with resolved.open(encoding="utf-8", errors="replace") as handle:
        for _ in handle:
            total_lines += 1
    return EvictedFileMeta(stored_chars=stored_chars, total_lines=total_lines)


def read_evicted_line_range(
    path: str | Path,
    *,
    offset: int,
    limit: int,
) -> EvictedLineRange:
    """Read a 0-based line window without loading the full file into memory."""
    if offset < 0:
        raise ValueError("offset must be >= 0")
    if limit < 1:
        raise ValueError("limit must be >= 1")

    resolved = Path(path)
    stored_chars = int(resolved.stat().st_size)
    collected: list[str] = []
    total_lines = 0
    with resolved.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if total_lines >= offset and len(collected) < limit:
                collected.append(line)
            total_lines += 1

    return EvictedLineRange(
        content="".join(collected),
        total_lines=total_lines,
        stored_chars=stored_chars,
        offset=offset,
        limit=limit,
    )
