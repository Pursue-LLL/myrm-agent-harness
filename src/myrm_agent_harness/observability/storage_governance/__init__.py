"""Storage governance subsystem for Agent persistent state management.

[INPUT]
- Path (POS: root data directory)
- Mapping[StorageCategory, Iterable[Path]] (POS: where the application keeps each category)

[OUTPUT]
- StorageGovernanceInspector, StateSnapshotManager
- StorageCategory, StorageCategoryBreakdown, StorageGovernanceReport, StateSnapshotMetadata

[POS]
Core storage governance toolkit for the agent's persistent state.
"""

from .inspector import StorageGovernanceInspector
from .snapshot_manager import StateSnapshotManager
from .types import (
    StateSnapshotMetadata,
    StorageCategory,
    StorageCategoryBreakdown,
    StorageGovernanceReport,
)

__all__ = [
    "StateSnapshotManager",
    "StateSnapshotMetadata",
    "StorageCategory",
    "StorageCategoryBreakdown",
    "StorageGovernanceInspector",
    "StorageGovernanceReport",
]
