"""Type definitions for Lightweight Fusen Shared State Sync (Item 63).

[INPUT]
- Multi-agent collaboration events, micro-blockers, review readiness, and cache hits.

[OUTPUT]
- FusenCategory, NoteStatus, FusenNote, FusenBlockerSummary.

[POS]
- Lightweight sub-millisecond shared sticky-note protocol eliminating heavy natural-language RPC handshakes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class FusenCategory(StrEnum):
    """Categorization of lightweight state sticky notes."""

    BLOCKER = "blocker"
    READY_FOR_REVIEW = "ready_for_review"
    CACHE_HINT = "cache_hint"
    IN_PROGRESS = "in_progress"
    CUSTOM = "custom"


class NoteStatus(StrEnum):
    """Lifecycle status of a Fusen sticky note."""

    ACTIVE = "active"
    RESOLVED = "resolved"
    EXPIRED = "expired"


@dataclass(slots=True)
class FusenNote:
    """A lightweight shared state sticky note (Fusen) posted by a collaborative agent."""

    note_id: str
    session_id: str
    author_agent_id: str
    category: FusenCategory
    tag: str
    content: str = ""
    metadata: dict[str, str] = field(default_factory=dict)
    status: NoteStatus = NoteStatus.ACTIVE
    resolution_note: str | None = None
    ttl_seconds: float | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def is_expired(self, now: float | None = None) -> bool:
        """Return True if note has a TTL and has exceeded its lifetime."""
        if self.ttl_seconds is None:
            return False
        current_time = now if now is not None else time.time()
        return current_time > (self.created_at + self.ttl_seconds)


@dataclass(slots=True)
class FusenBlockerSummary:
    """Summary of active blockers impacting a specific agent or team."""

    is_blocked: bool
    blocker_count: int
    blockers: list[FusenNote]
    active_tags: list[str]
