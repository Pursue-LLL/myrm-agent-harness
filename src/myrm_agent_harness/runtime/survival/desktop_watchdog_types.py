"""Domain types for desktop long-session eviction and memory watchdog suite.

Provides strong-typed abstractions for offscreen turn dehydration, skeletal
placeholders, desktop RSS memory alerts, idle compaction receipts, and
rolling multi-volume long-session archives.

[OUTPUT]
- DehydrationState: State of rich media in a conversation turn.
- MemoryAlertLevel: Classification of process memory pressure.
- SessionTurn: Structured representation of a conversational turn.
- DehydratedSessionTurn: Memory-compact turn with dehydrated heavy content.
- MemoryCompactionReceipt: Outcome of an idle memory compaction run.
- ArchiveVolume: Sealed historical volume of a long-running session.

[INPUT]
- __future__
- time
- dataclasses
- typing

[OUTPUT]
- DehydrationState
- MemoryAlertLevel
- VALID_DEHYDRATION_STATES
- VALID_MEMORY_ALERT_LEVELS
- SessionTurn
- DehydratedSessionTurn
- MemoryCompactionReceipt
- ArchiveVolume

[POS]
Domain types for desktop long-session eviction and memory watchdog suite.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

DehydrationState = Literal[
    "HYDRATED",
    "DEHYDRATED",
    "SKELETON_ONLY",
]

MemoryAlertLevel = Literal[
    "NORMAL",
    "WARNING",
    "CRITICAL",
    "EMERGENCY",
]

VALID_DEHYDRATION_STATES: tuple[DehydrationState, ...] = (
    "HYDRATED",
    "DEHYDRATED",
    "SKELETON_ONLY",
)

VALID_MEMORY_ALERT_LEVELS: tuple[MemoryAlertLevel, ...] = (
    "NORMAL",
    "WARNING",
    "CRITICAL",
    "EMERGENCY",
)


@dataclass(frozen=True, slots=True)
class SessionTurn:
    """Full-fidelity representation of a conversation turn with rich media."""

    turn_id: str
    session_id: str
    turn_index: int
    user_query: str
    agent_response: str
    rich_media: dict[str, object] = field(default_factory=dict)
    raw_tokens_count: int = 0
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class DehydratedSessionTurn:
    """Memory-compacted turn with stripped heavy DOM artifacts and bitmap skeleton."""

    turn_id: str
    session_id: str
    turn_index: int
    state: DehydrationState
    user_query: str
    response_summary: str
    rich_media_count: int
    original_estimated_bytes: int
    dehydrated_estimated_bytes: int
    raw_content_ref: str | None = None
    dehydrated_at: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class MemoryCompactionReceipt:
    """Consolidated receipt summarizing memory trimming and dehydration."""

    level: MemoryAlertLevel
    pre_rss_bytes: int
    post_rss_bytes: int
    freed_bytes: int
    dehydrated_turns_count: int
    triggered_at: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class ArchiveVolume:
    """Sealed archival slice of an extended long-horizon conversation."""

    volume_id: str
    session_id: str
    volume_index: int
    start_turn_index: int
    end_turn_index: int
    milestone_summary: str
    retained_turns_count: int
    archived_at: float = field(default_factory=time.time)
