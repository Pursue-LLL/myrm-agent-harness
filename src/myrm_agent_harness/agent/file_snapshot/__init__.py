"""File snapshot module — workspace file versioning and rollback.

Provides transparent file-level snapshots before file-mutating operations,
enabling rollback to any previous state.

Two implementations:
- ShadowGitSnapshotStore: isolated bare repo (preferred, requires git)
- LocalFileSnapshotStore: file-copy fallback (no external deps)

Use `create_file_snapshot_store()` factory to auto-select the best one.

[POS]
File snapshot subsystem for workspace file versioning.
"""

from .factory import create_file_snapshot_store, get_cached_store
from .local_store import LocalFileSnapshotStore
from .protocols import FileSnapshotProtocol
from .restore_inbox import drain_restore_notifications, push_restore_notification
from .shadow_git_store import ShadowGitSnapshotStore
from .types import FileDiff, FileSnapshotInfo, RestoreResult, SnapshotId

__all__ = [
    "FileDiff",
    "FileSnapshotInfo",
    "FileSnapshotProtocol",
    "LocalFileSnapshotStore",
    "RestoreResult",
    "ShadowGitSnapshotStore",
    "SnapshotId",
    "create_file_snapshot_store",
    "drain_restore_notifications",
    "get_cached_store",
    "push_restore_notification",
]
