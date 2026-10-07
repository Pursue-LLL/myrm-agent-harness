"""Public entrypoint for Instant Cloud Session Snapshot Restore and Zero-Clone Warm Pool Suite.

Exports copy-on-write volume descriptors, incremental git patch bundles,
and pre-warmed container pooling engines.
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
