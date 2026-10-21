"""File snapshot protocol definition.

[POS]
Protocol for file snapshot operations. Implementations provide
workspace file versioning and rollback capabilities.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .types import FileDiff, FileSnapshotInfo, RestoreResult, SnapshotId, SnapshotTrigger


@runtime_checkable
class FileSnapshotProtocol(Protocol):
    """Protocol for file snapshot operations.

    Implementations provide workspace file versioning, enabling
    rollback to any previous state after file-mutating operations.

    Example:
        >>> store: FileSnapshotProtocol = LocalFileSnapshotStore(workspace_path)
        >>> snap_id = await store.take_snapshot("/workspace", SnapshotTrigger.WRITE_FILE)
        >>> diff = await store.diff(snap_id)
        >>> result = await store.restore(snap_id)
    """

    async def take_snapshot(
        self,
        working_dir: str,
        trigger: SnapshotTrigger,
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> SnapshotId:
        """Take a snapshot of the current workspace state.

        Args:
            working_dir: Directory to snapshot
            trigger: What triggered the snapshot
            description: Optional human-readable description
            metadata: Optional key-value metadata stored in commit trailer

        Returns:
            Snapshot ID for later reference
        """
        ...

    async def restore(
        self,
        snapshot_id: SnapshotId,
        files: list[str] | None = None,
    ) -> RestoreResult:
        """Restore workspace to a snapshot state.

        Automatically takes a pre-rollback snapshot before restoring.

        Args:
            snapshot_id: Snapshot to restore
            files: Specific files to restore (None = all files)

        Returns:
            Restore result with details
        """
        ...

    async def diff(self, snapshot_id: SnapshotId) -> FileDiff:
        """Compare a snapshot with current workspace state.

        Args:
            snapshot_id: Snapshot to compare against

        Returns:
            Diff showing changes since snapshot
        """
        ...

    async def list_snapshots(
        self,
        working_dir: str,
        limit: int = 20,
    ) -> list[FileSnapshotInfo]:
        """List snapshots for a workspace.

        Args:
            working_dir: Workspace directory
            limit: Maximum number of snapshots to return

        Returns:
            List of snapshot info, newest first
        """
        ...

    async def delete_snapshot(self, snapshot_id: SnapshotId) -> bool:
        """Delete a specific snapshot.

        Args:
            snapshot_id: Snapshot to delete

        Returns:
            True if deleted, False if not found
        """
        ...

    async def cleanup(
        self,
        working_dir: str,
        max_snapshots: int = 20,
    ) -> int:
        """Cleanup old snapshots, keeping the most recent.

        Args:
            working_dir: Workspace directory
            max_snapshots: Maximum snapshots to keep

        Returns:
            Number of snapshots deleted
        """
        ...
