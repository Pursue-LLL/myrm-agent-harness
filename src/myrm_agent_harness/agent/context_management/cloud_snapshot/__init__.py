"""Public entrypoint for Instant Cloud Session Snapshot Restore and Zero-Clone Warm Pool Suite.

Exports copy-on-write volume descriptors, incremental git patch bundles,
and pre-warmed container pooling engines.

[INPUT]
- agent.context_management.cloud_snapshot.cloud_snapshot_engine::InstantCloudSnapshotRestoreEngine (POS:
  Engine implementation for Instant Cloud Session Snapshot Restore and Zero-Clone Warm Pool.)
- agent.context_management.cloud_snapshot.cloud_snapshot_types::CloudSnapshotConfig, IncrementalPatchBundle,
  SandboxPoolState, SnapshotRestoreResult, SnapshotStorageDriver, VolumeSnapshotDescriptor,
  WarmSandboxDescriptor (POS: Type contracts and definitions for Instant Cloud Session Snapshot and Zero-Clone
  Warm Pool.)

[OUTPUT]
- Re-exports: CloudSnapshotConfig, IncrementalPatchBundle, InstantCloudSnapshotRestoreEngine,
  SandboxPoolState, SnapshotRestoreResult, SnapshotStorageDriver, VolumeSnapshotDescriptor,
  WarmSandboxDescriptor

[POS]
Public entrypoint for Instant Cloud Session Snapshot Restore and Zero-Clone Warm Pool Suite.
"""

from myrm_agent_harness.agent.context_management.cloud_snapshot.cloud_snapshot_engine import (
    InstantCloudSnapshotRestoreEngine,
)
from myrm_agent_harness.agent.context_management.cloud_snapshot.cloud_snapshot_types import (
    CloudSnapshotConfig,
    IncrementalPatchBundle,
    SandboxPoolState,
    SnapshotRestoreResult,
    SnapshotStorageDriver,
    VolumeSnapshotDescriptor,
    WarmSandboxDescriptor,
)

__all__ = [
    "CloudSnapshotConfig",
    "IncrementalPatchBundle",
    "InstantCloudSnapshotRestoreEngine",
    "SandboxPoolState",
    "SnapshotRestoreResult",
    "SnapshotStorageDriver",
    "VolumeSnapshotDescriptor",
    "WarmSandboxDescriptor",
]
