"""Types and models for mobility.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- FileChangeKind: File status transition kind within workspace delta.
- OffloadTargetKind: Target destination platform for session worker offloading.
- WorkspaceFileEntry: Single file artifact or source modification encapsulated in workspace.
- WorkspaceCapsule: Portable, self-contained workspace capsule package for session mobility.
- OffloadTransferReceipt: Acknowledgement receipt for session offload dispatched to remote worker.
- MergeConflictItem: Detected conflict item during bidirectional workspace synchronization.
- SyncMergeReport: Outcome report of applying remote changes back to local workspace.

[POS]
Types and models for mobility.
"""

# ============================================================================
# Session Workspace Mobility & Cloud Worker Offload Data Contracts (Item 163)
# Strong typing contracts for workspace capsule serialization, cloud worker
# offloading, and bidirectional sync merge guard conflict detection.
# ============================================================================

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class FileChangeKind(str, Enum):
    """File status transition kind within workspace delta."""

    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"


class OffloadTargetKind(str, Enum):
    """Target destination platform for session worker offloading."""

    CLOUD_SANDBOX_WORKER = "cloud_sandbox_worker"
    PAIRED_LAPTOP_DEVICE = "paired_laptop_device"
    LOCAL_DAEMON = "local_daemon"


@dataclass(frozen=True, slots=True)
class WorkspaceFileEntry:
    """Single file artifact or source modification encapsulated in workspace."""

    path: str
    kind: FileChangeKind
    content: str  # UTF-8 text or base64 encoded binary payload
    content_hash: str
    byte_size: int


@dataclass(frozen=True, slots=True)
class WorkspaceCapsule:
    """Portable, self-contained workspace capsule package for session mobility."""

    capsule_id: str
    session_id: str
    created_at_iso: str
    base_checkpoint_hash: str
    files: tuple[WorkspaceFileEntry, ...]
    execution_progress_note: str
    capsule_digest: str


@dataclass(frozen=True, slots=True)
class OffloadTransferReceipt:
    """Acknowledgement receipt for session offload dispatched to remote worker."""

    transfer_id: str
    capsule_id: str
    session_id: str
    target_kind: OffloadTargetKind
    target_endpoint: str
    status: str
    acknowledged_at_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(frozen=True, slots=True)
class MergeConflictItem:
    """Detected conflict item during bidirectional workspace synchronization."""

    file_path: str
    local_hash: str
    remote_hash: str
    conflict_reason: str


@dataclass(frozen=True, slots=True)
class SyncMergeReport:
    """Outcome report of applying remote changes back to local workspace."""

    is_clean_merge: bool
    applied_files_count: int
    conflicts: tuple[MergeConflictItem, ...]
    summary_note: str
