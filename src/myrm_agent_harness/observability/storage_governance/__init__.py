"""Storage governance subsystem for Agent persistent state management.

[INPUT]
- Path (POS: root data directory)
- Mapping[StorageCategory, Iterable[Path]] (POS: where the application keeps each category)

[OUTPUT]
- StorageGovernanceInspector
- StorageCategory, StorageCategoryBreakdown, StorageGovernanceReport, StateSnapshotMetadata

[POS]
Core storage governance toolkit for the agent's persistent state.
"""

from .inspector import StorageGovernanceInspector
from .types import (
    StateSnapshotMetadata,
    StorageCategory,
    StorageCategoryBreakdown,
    StorageGovernanceReport,
)

__all__ = [
    "StateSnapshotMetadata",
    "StorageCategory",
    "StorageCategoryBreakdown",
    "StorageGovernanceInspector",
    "StorageGovernanceReport",
]
