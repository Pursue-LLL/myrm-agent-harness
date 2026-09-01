"""Data models and contracts for Agent persistent state storage governance.

[INPUT]
- Pure dataclass/TypedDict definitions for storage metrics, compaction results, and snapshots.

[OUTPUT]
- StorageCategoryBreakdown, StorageGovernanceReport, CompactionResult, StateSnapshotMetadata

[POS]
Type system for observability storage governance subsystem.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class StorageCategory(str, Enum):
    """Categories of persistent state storage."""

    SQLITE_DATABASE = "sqlite_database"
    CHECKPOINTS = "checkpoints"
    VECTOR_STORE = "vector_store"
    MEMORY_ARCHIVE = "memory_archive"
    EVENT_LOGS = "event_logs"
    SNAPSHOTS = "snapshots"
    OTHER = "other"


@dataclass(frozen=True)
class StorageCategoryBreakdown:
    """Breakdown metrics for a specific storage category."""

    category: StorageCategory
    display_name: str
    bytes: int
    item_count: int = 0
    percentage: float = 0.0
    details: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class StateSnapshotMetadata:
    """Metadata for an immutable state snapshot."""

    snapshot_id: str
    label: str
    size_bytes: int
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    checksum: str = ""
    agent_count: int = 0
    file_count: int = 0


@dataclass(frozen=True)
class CompactionResult:
    """Result of a safe storage compaction operation."""

    success: bool
    initial_bytes: int
    final_bytes: int
    freed_bytes: int
    purged_checkpoints: int = 0
    wal_truncated: bool = False
    duration_ms: float = 0.0
    message: str = ""


@dataclass(frozen=True)
class StorageGovernanceReport:
    """Comprehensive governance report for agent persistent storage."""

    total_storage_bytes: int
    disk_total_bytes: int
    disk_free_bytes: int
    disk_used_percentage: float
    categories: list[StorageCategoryBreakdown]
    snapshots: list[StateSnapshotMetadata] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    is_growth_healthy: bool = True
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
