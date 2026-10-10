"""Domain models for vector index dimension guard and task-based rebuild orchestration.

[INPUT]
- Collection names, expected dimensions, task identifiers, and rebuild events.

[OUTPUT]
- DimGuardResult, RebuildPhase, FailedItem, RebuildProgressEvent, RebuildTaskStatus.

[POS]
- Core domain models for Item 151 VectorDimGuardAndRebuildTaskSuite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RebuildPhase(str, Enum):
    """Lifecycle phases of a vector rebuild task."""

    QUEUED = "queued"
    PREPARING = "preparing"
    REBUILDING = "rebuilding"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class DimGuardResult:
    """Outcome of inspecting vector index existence and dimension alignment."""

    collection: str
    exists: bool
    current_dim: int | None
    expected_dim: int
    dim_match: bool
    needs_rebuild: bool
    data_intact: bool = True
    message: str = ""


@dataclass(frozen=True)
class FailedItem:
    """Record of an item that failed during re-indexing."""

    item_id: str
    reason: str
    phase: str
    timestamp_ms: int


@dataclass(frozen=True)
class RebuildProgressEvent:
    """Progress event emitted during rebuild task execution."""

    task_id: str
    phase: RebuildPhase
    progress_pct: int
    processed_count: int
    total_count: int
    message: str
    timestamp_ms: int


@dataclass(frozen=True)
class RebuildTaskStatus:
    """Snapshot status of a vector rebuild execution."""

    task_id: str
    collection: str
    phase: RebuildPhase
    progress_pct: int
    processed_count: int
    total_count: int
    failed_items: tuple[FailedItem, ...] = ()
    started_at_ms: int = 0
    finished_at_ms: int | None = None
    error: str | None = None
