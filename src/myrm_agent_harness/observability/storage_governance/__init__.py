"""Storage governance subsystem for Agent persistent state management.

[INPUT]
- Path (POS: root data directory)

[OUTPUT]
- StorageGovernanceInspector, StateStorageCompactor, StateSnapshotManager
- StorageCategory, StorageCategoryBreakdown, StorageGovernanceReport, CompactionResult, StateSnapshotMetadata

[POS]
Core storage governance and state longevity maintenance toolkit.
"""

from .compactor import StateStorageCompactor
from .inspector import StorageGovernanceInspector
from .snapshot_manager import StateSnapshotManager
from .types import (
    CompactionResult,
    StateSnapshotMetadata,
    StorageCategory,
    StorageCategoryBreakdown,
    StorageGovernanceReport,
)

__all__ = [
    "CompactionResult",
    "StateSnapshotManager",
    "StateStorageCompactor",
    "StateSnapshotMetadata",
    "StorageCategory",
    "StorageCategoryBreakdown",
    "StorageGovernanceInspector",
    "StorageGovernanceReport",
]
