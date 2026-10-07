# [POS]: src/myrm_agent_harness/toolkits/memory/markdown_curator/models.py
# [INPUT]: None (Domain models for Markdown bidi-sync and Curator Studio)
# [OUTPUT]: CuratedMemoryCategory, CuratedMemoryStatus, CuratedMemoryEntry, MarkdownSyncDelta, CuratorStudioSummary

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class CuratedMemoryCategory(StrEnum):
    """Categorical dimensions for curated memory items."""

    PREFERENCE = "preference"
    FACT = "fact"
    PROCEDURE = "procedure"
    EXPERIENCE = "experience"


class CuratedMemoryStatus(StrEnum):
    """Lifecycle status for curated memory entries with human gating."""

    CONFIRMED = "confirmed"
    PENDING_CONFIRMATION = "pending_confirmation"
    REJECTED = "rejected"
    ARCHIVED = "archived"


@dataclass
class CuratedMemoryEntry:
    """Core domain model representing a transparent, human-editable memory unit."""

    entry_id: str
    category: CuratedMemoryCategory
    title: str
    content: str
    confidence: float = 1.0
    status: CuratedMemoryStatus = CuratedMemoryStatus.CONFIRMED
    tags: list[str] = field(default_factory=list)
    source_session_id: str | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


@dataclass
class MarkdownSyncDelta:
    """Differences computed between in-memory state and workspace Markdown mirror."""

    added_entries: list[CuratedMemoryEntry] = field(default_factory=list)
    updated_entries: list[CuratedMemoryEntry] = field(default_factory=list)
    deleted_entry_ids: list[str] = field(default_factory=list)
    sync_direction: str = "bidirectional"


@dataclass
class CuratorStudioSummary:
    """Aggregated metrics and categories distribution for the Curator Studio."""

    total_entries: int
    confirmed_count: int
    pending_count: int
    rejected_count: int
    archived_count: int
    categories_breakdown: dict[str, int] = field(default_factory=dict)
