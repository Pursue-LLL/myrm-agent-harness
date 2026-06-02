"""File snapshot module — workspace file versioning and rollback.

Provides transparent file-level snapshots before file-mutating operations,
enabling rollback to any previous state.

[POS]
File snapshot subsystem for workspace file versioning.
"""

from .protocols import FileSnapshotProtocol
from .types import FileDiff, FileSnapshotInfo, RestoreResult, SnapshotId

__all__ = [
    "FileDiff",
    "FileSnapshotInfo",
    "FileSnapshotProtocol",
    "RestoreResult",
    "SnapshotId",
]
