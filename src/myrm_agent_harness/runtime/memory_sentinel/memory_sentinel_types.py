"""Data types and schemas for Deterministic Lifetime and Bounded Cache Memory Sentinel Suite.

Provides structured models for three-dimensional bounded cache management (TTL, LRU, Byte-Cap),
spill-to-volume dehydrated handles, and idle session freeze snapshots.

[INPUT]
- __future__
- time
- dataclasses
- enum
- pathlib

[OUTPUT]
- CacheEvictionPolicy
- BoundedCacheStats
- SpillHandle
- SessionFreezeState
- SessionSnapshotRecord

[POS]
Data types and schemas for Deterministic Lifetime and Bounded Cache Memory Sentinel Suite.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class CacheEvictionPolicy(StrEnum):
    """Reason triggering cache eviction."""

    TTL_EXPIRED = "ttl_expired"  # Entry exceeded maximum time-to-live
    LRU_CAPACITY = "lru_capacity"  # Item count exceeded max allowed entries
    BYTE_LIMIT_EXCEEDED = "byte_limit_exceeded"  # Total heap byte consumption exceeded cap


@dataclass(frozen=True)
class BoundedCacheStats:
    """Operational health telemetry for a bounded cache instance."""

    item_count: int
    current_bytes: int
    max_bytes: int
    max_items: int
    hit_count: int
    miss_count: int
    eviction_count: int


@dataclass(frozen=True)
class SpillHandle:
    """Lightweight metadata handle representing a dehydrated large object spilled to disk.

    Only the handle remains resident in heap memory, preventing memory bloat.
    """

    spill_id: str
    disk_path: Path
    raw_size_bytes: int
    compressed_size_bytes: int
    preview_snippet: str
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, str | int | float]:
        """Convert handle to JSON-safe dictionary for message metadata embedding."""
        return {
            "__spill_ref__": self.spill_id,
            "disk_path": str(self.disk_path),
            "raw_size_bytes": self.raw_size_bytes,
            "compressed_size_bytes": self.compressed_size_bytes,
            "preview_snippet": self.preview_snippet,
            "created_at": self.created_at,
        }


class SessionFreezeState(StrEnum):
    """Lifecycle residency state of an agent session."""

    ACTIVE = "active"  # Resident in memory
    FROZEN_TO_DISK = "frozen_to_disk"  # Serialized to disk, heap memory unloaded
    EVICTED = "evicted"  # Completely purged


@dataclass(frozen=True)
class SessionSnapshotRecord:
    """Record of an idle session frozen to volume storage."""

    session_id: str
    message_count: int
    storage_file: Path
    frozen_at: float = field(default_factory=time.time)
