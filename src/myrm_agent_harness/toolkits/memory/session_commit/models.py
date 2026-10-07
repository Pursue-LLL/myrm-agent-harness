# [POS]: src/myrm_agent_harness/toolkits/memory/session_commit/models.py
# [INPUT]: None (Pure domain types for Session Commit Two-Phase Architecture)
# [OUTPUT]: CommitBoundaryKind, CommitPhase, MemoryDiffChangeKind, MemoryDiffItem, MemoryDiffStats, MemoryDiffAudit, SessionArchiveMessage, CommitTaskStatus, SessionCommitResult

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class CommitBoundaryKind(StrEnum):
    """Reliable task boundaries that gate full Phase 2 memory extraction (aligned with OpenViking session concept)."""

    TARGET_COMPLETED = "target_completed"
    FAILURE_REPAIRED = "failure_repaired"
    USER_CORRECTION = "user_correction"
    CONTEXT_COMPACTION = "context_compaction"
    MANUAL = "manual"


class CommitPhase(StrEnum):
    """Lifecycle phase of the session commit pipeline."""

    PHASE1_SYNC_ARCHIVED = "phase1_sync_archived"
    PHASE2_EXTRACTING = "phase2_extracting"
    PHASE2_COMPLETED = "phase2_completed"
    FAILED = "failed"


class MemoryDiffChangeKind(StrEnum):
    """Categorization of a specific memory modification in the audit ledger."""

    ADDED = "added"
    UPDATED = "updated"
    SUPERSEDED = "superseded"
    DELETED = "deleted"


@dataclass(frozen=True)
class MemoryDiffItem:
    """An individual memory record alteration entry for audit tracking."""

    change_kind: MemoryDiffChangeKind
    memory_type: str
    item_id: str
    before_summary: str | None = None
    after_summary: str | None = None
    timestamp: str | None = None


@dataclass(frozen=True)
class MemoryDiffStats:
    """Statistical summary of changes within memory_diff.json."""

    total_added: int = 0
    total_updated: int = 0
    total_superseded: int = 0
    total_deleted: int = 0


@dataclass(frozen=True)
class MemoryDiffAudit:
    """Full structured memory_diff.json payload recording all memory changes upon commit."""

    session_id: str
    archive_id: str
    task_id: str
    timestamp: str
    boundary_kind: CommitBoundaryKind
    changes: tuple[MemoryDiffItem, ...] = field(default_factory=tuple)
    stats: MemoryDiffStats = field(default_factory=MemoryDiffStats)


@dataclass(frozen=True)
class SessionArchiveMessage:
    """Structured interaction message recorded into Phase 1 messages.jsonl."""

    role: str
    content: str
    tool_calls: tuple[dict[str, str], ...] = field(default_factory=tuple)
    tool_results: tuple[dict[str, str], ...] = field(default_factory=tuple)
    timestamp: str | None = None
    referenced_uris: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CommitTaskStatus:
    """Live state of an asynchronous session commit pipeline task."""

    task_id: str
    session_id: str
    archive_id: str
    phase: CommitPhase
    boundary_kind: CommitBoundaryKind
    created_at: str
    completed_at: str | None = None
    error: str | None = None
    message_count: int = 0
    diff_stats: MemoryDiffStats | None = None


@dataclass(frozen=True)
class SessionCommitResult:
    """Immediate return payload upon executing Phase 1 synchronous commit."""

    task_id: str
    session_id: str
    archive_id: str
    phase1_persisted: bool
    messages_path: str
    phase2_scheduled: bool
