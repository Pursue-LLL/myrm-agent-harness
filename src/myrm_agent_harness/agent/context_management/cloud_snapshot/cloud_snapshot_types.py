"""Type contracts and definitions for Instant Cloud Session Snapshot and Zero-Clone Warm Pool.

Defines copy-on-write volume snapshot descriptors, incremental patch bundles,
pre-warmed sandbox pool lifecycles, and restoration telemetry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import time


class SnapshotStorageDriver(StrEnum):
    """Storage backing driver for instant workspace volume instantiation."""

    COW_OVERLAY = "cow_overlay"  # Kernel-level OverlayFS upperdir mount
    HARDLINK_REF = "hardlink_ref"  # Fast link-farm clone for local/posix environments
    ZFS_CLONE = "zfs_clone"  # Block-level snapshot clone
    MEMORY_MOCK = "memory_mock"  # In-memory virtual snapshot driver for tests


class SandboxPoolState(StrEnum):
    """Lifecycle state of a pre-warmed sandbox worker in the warm pool."""

    WARM_IDLE = "warm_idle"  # Pre-booted and ready for instantaneous acquisition
    CLAIMED_BUSY = "claimed_busy"  # Bound to an active session
    DRAINING = "draining"  # Session completed, cleaning up or recycling
    TERMINATED = "terminated"  # Disposed from the pool


@dataclass(frozen=True)
class VolumeSnapshotDescriptor:
    """Immutable metadata descriptor representing a frozen baseline workspace snapshot."""

    snapshot_id: str
    base_repo_ref: str
    dependencies_hash: str
    workspace_root: str
    storage_driver: SnapshotStorageDriver
    estimated_size_bytes: int
    metadata: dict[str, str] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class IncrementalPatchBundle:
    """Lightweight incremental git diff payload streamed to avoid full cloning."""

    patch_id: str
    source_commit: str
    target_commit: str
    diff_content: str
    affected_paths: tuple[str, ...]
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class WarmSandboxDescriptor:
    """Descriptor of a pre-warmed worker container in the reusable warm pool."""

    sandbox_id: str
    state: SandboxPoolState
    runtime_environment: str
    assigned_session_id: str | None = None
    attached_snapshot_id: str | None = None
    ready_at: float = field(default_factory=time.time)
    lease_expiry_timestamp: float | None = None


@dataclass(frozen=True)
class SnapshotRestoreResult:
    """Telemetry report emitted after instantaneous cloud session restoration."""

    session_id: str
    sandbox_id: str
    active_workspace_path: str
    duration_ms: float
    is_zero_clone: bool
    patch_applied: bool
    patch_files_count: int
    driver_used: SnapshotStorageDriver
    restored_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class CloudSnapshotConfig:
    """Configuration governing instant volume snapshot restores and warm pool caching."""

    default_driver: SnapshotStorageDriver = SnapshotStorageDriver.COW_OVERLAY
    warm_pool_size: int = 3
    max_restore_latency_ms: float = 800.0
    sandbox_lease_ttl_seconds: float = 1800.0
    auto_cleanup_orphan_snapshots: bool = True
