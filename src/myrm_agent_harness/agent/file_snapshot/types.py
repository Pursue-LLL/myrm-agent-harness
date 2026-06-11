"""File snapshot type definitions.

[POS]
Data types for file snapshot operations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from enum import StrEnum


class SnapshotTrigger(StrEnum):
    """What triggered the snapshot creation."""

    WRITE_FILE = "write_file"
    DELETE_FILE = "delete_file"
    PATCH_FILE = "patch_file"
    EXECUTE_TERMINAL = "execute_terminal"
    MANUAL = "manual"
    PRE_ROLLBACK = "pre_rollback"


SnapshotId = str


@dataclass(frozen=True, slots=True)
class FileSnapshotInfo:
    """Metadata about a file snapshot."""

    snapshot_id: SnapshotId
    working_dir: str
    trigger: SnapshotTrigger
    created_at: float
    file_count: int
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "snapshot_id": self.snapshot_id,
            "working_dir": self.working_dir,
            "trigger": self.trigger.value,
            "created_at": self.created_at,
            "file_count": self.file_count,
            "description": self.description,
        }
        if self.metadata:
            result["metadata"] = self.metadata
        return result


@dataclass(frozen=True, slots=True)
class FileChange:
    """A single file change in a diff."""

    path: str
    change_type: str  # "added", "modified", "deleted"
    old_size: int | None = None
    new_size: int | None = None
    lines_added: int | None = None
    lines_deleted: int | None = None


@dataclass(frozen=True, slots=True)
class FileDiff:
    """Diff between a snapshot and current state."""

    snapshot_id: SnapshotId
    changes: list[FileChange] = field(default_factory=list)
    total_changes: int = 0


@dataclass(frozen=True, slots=True)
class RestoreResult:
    """Result of a snapshot restore operation."""

    success: bool
    snapshot_id: SnapshotId
    files_restored: int
    pre_rollback_snapshot_id: SnapshotId | None = None
    error: str | None = None
