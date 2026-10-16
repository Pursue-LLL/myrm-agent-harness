"""Data models and contracts for Agent persistent state storage governance.

[INPUT]
- Pure dataclass/enum definitions for storage metrics and snapshots.

[OUTPUT]
- StorageCategory, StorageCategoryBreakdown, StorageGovernanceReport, StateSnapshotMetadata

[POS]
Type system for observability storage governance subsystem.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class StorageCategory(StrEnum):
    """Categories of persistent state storage; reports list them in declaration order.

    `OTHER` is not declared by the application: it is whatever the data directory holds that no other category
    claims, and it stays the last member.
    """

    SQLITE_DATABASE = "sqlite_database"
    CHECKPOINTS = "checkpoints"
    WORKSPACES = "workspaces"
    VECTOR_STORE = "vector_store"
    MEMORY_ARCHIVE = "memory_archive"
    EVENT_LOGS = "event_logs"
    SQLITE_BACKUPS = "sqlite_backups"
    SNAPSHOTS = "snapshots"
    OTHER = "other"


@dataclass(frozen=True)
class StorageCategoryBreakdown:
    """Breakdown metrics for a specific storage category.

    `bytes` adds up the apparent size of the regular files behind the category and `item_count` counts them; a
    database category holds just its database file and the journals SQLite keeps beside it.
    """

    category: StorageCategory
    bytes: int
    item_count: int = 0
    percentage: float = 0.0


@dataclass(frozen=True)
class StateSnapshotMetadata:
    """Metadata for an immutable state snapshot."""

    snapshot_id: str
    label: str
    size_bytes: int
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    checksum: str = ""
    agent_count: int = 0
    file_count: int = 0


@dataclass(frozen=True)
class StorageGovernanceReport:
    """Comprehensive governance report for agent persistent storage."""

    total_storage_bytes: int
    disk_total_bytes: int
    disk_free_bytes: int
    disk_used_percentage: float
    categories: list[StorageCategoryBreakdown]
    snapshots: list[StateSnapshotMetadata] = field(default_factory=list)
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
