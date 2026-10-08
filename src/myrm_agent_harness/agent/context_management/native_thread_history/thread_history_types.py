# [INPUT]: None
# [OUTPUT]: ThreadEntry, SortKeyKind, FallbackStatus, ThreadPageRequest, ThreadHistoryPage
# [POS]: agent/context_management/native_thread_history/thread_history_types.py

"""Strongly typed contracts for large native thread history and sort key fallback.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- SortKeyKind: Supported sort key definitions for native thread items.
- FallbackStatus: Resolution status of sort key evaluation.
- ThreadEntry: A single atomic entry within a large native thread history.
- ThreadPageRequest: Request query parameters for thread history pagination.
- ThreadHistoryPage: Safely resolved page of native thread history with fallback metadata.

[POS]
Strongly typed contracts for large native thread history and sort key fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SortKeyKind(str, Enum):
    """Supported sort key definitions for native thread items."""

    SECTION_POSITION = "section_position"
    SEQUENCE = "sequence"
    CREATED_AT = "created_at"


class FallbackStatus(str, Enum):
    """Resolution status of sort key evaluation."""

    NORMAL = "normal"
    FALLBACK_EMPTY_PAGE = "fallback_empty_page"
    FALLBACK_NATURAL_KEY = "fallback_natural_key"


@dataclass(frozen=True)
class ThreadEntry:
    """A single atomic entry within a large native thread history."""

    entry_id: str
    thread_id: str
    section_position: int | None
    sequence: int
    content: str
    byte_size: int
    created_at_epoch_ms: int
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ThreadPageRequest:
    """Request query parameters for thread history pagination."""

    thread_id: str
    sort_key: str = SortKeyKind.SECTION_POSITION.value
    page_size: int = 50
    cursor: str | None = None
    allow_natural_fallback: bool = False
    max_retained_bytes: int = 10_000_000


@dataclass(frozen=True)
class ThreadHistoryPage:
    """Safely resolved page of native thread history with fallback metadata."""

    thread_id: str
    entries: list[ThreadEntry]
    total_entries: int
    has_more: bool
    next_cursor: str | None
    fallback_applied: bool
    fallback_status: FallbackStatus
    fallback_reason: str | None
    retained_byte_size: int
