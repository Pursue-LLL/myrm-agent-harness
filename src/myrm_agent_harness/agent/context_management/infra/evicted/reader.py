"""Streaming readers for UECD evicted files on disk.

[INPUT]
- evicted.markers::probe_storage_cap_from_tail, TAIL_PROBE_CHARS

[OUTPUT]
- count_lines_in_text, read_evicted_line_range, read_evicted_file_meta
- EvictedFileMeta, EvictedLineRange

[POS]
Pure I/O helpers for paginated GUI/API reads of `.context/.../evicted/` files.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from myrm_agent_harness.agent.context_management.infra.evicted.markers import (
    TAIL_PROBE_CHARS,
    probe_storage_cap_from_tail,
)


@dataclass(frozen=True, slots=True)
class EvictedFileMeta:
    """On-disk stats for an evicted output file."""

    stored_chars: int
    total_lines: int
    storage_truncated: bool = False
    original_chars: int | None = None


@dataclass(frozen=True, slots=True)
class EvictedLineRange:
    """A slice of evicted file lines plus file-wide totals."""

    content: str
    total_lines: int
    stored_chars: int
    offset: int
    limit: int
    storage_truncated: bool = False
    original_chars: int | None = None


def count_lines_in_text(text: str) -> int:
    """Return a line count consistent with line-oriented eviction reads."""
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _read_file_tail_text(path: Path, *, max_chars: int = TAIL_PROBE_CHARS) -> str:
    size = path.stat().st_size
    if size <= 0:
        return ""
    with path.open("rb") as handle:
        if size > max_chars:
            handle.seek(size - max_chars)
        return handle.read().decode("utf-8", errors="replace")


def read_evicted_file_meta(path: str | Path) -> EvictedFileMeta:
    """Read byte size, line count, and optional storage-cap stats for an evicted file."""
    resolved = Path(path)
    stored_chars = int(resolved.stat().st_size)
    total_lines = 0
    with resolved.open(encoding="utf-8", errors="replace") as handle:
        for _ in handle:
            total_lines += 1
    tail = _read_file_tail_text(resolved)
    storage_truncated, original_chars = probe_storage_cap_from_tail(tail)
    return EvictedFileMeta(
        stored_chars=stored_chars,
        total_lines=total_lines,
        storage_truncated=storage_truncated,
        original_chars=original_chars,
    )


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
    storage_truncated, original_chars = probe_storage_cap_from_tail(_read_file_tail_text(resolved))
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
        storage_truncated=storage_truncated,
        original_chars=original_chars,
    )
