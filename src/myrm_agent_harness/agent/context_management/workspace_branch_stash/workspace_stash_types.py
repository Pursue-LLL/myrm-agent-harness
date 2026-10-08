"""Types and data structures for workspace shadow stash and branch artifact integrity.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- FileStashKind: Classification of file modification state during branch switch.
- ShadowStashFileRecord: Individual file capture inside branch shadow stash.
- BranchWorkspaceSnapshot: Complete snapshot of files bound to a logical exploration branch.
- WorkspaceStashConflictWarning: Warning descriptor for overlapping dirty modifications across branches.
- WorkspaceStashReceipt: Receipt certifying branch switch workspace state synchronization and file integrity.

[POS]
Types and data structures for workspace shadow stash and branch artifact integrity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class FileStashKind(str, Enum):
    """Classification of file modification state during branch switch."""

    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"


@dataclass(frozen=True)
class ShadowStashFileRecord:
    """Individual file capture inside branch shadow stash."""

    relative_path: str
    file_stash_kind: FileStashKind
    content_text: str
    sha256_hash: str
    size_bytes: int
    captured_at_iso: str


@dataclass(frozen=True)
class BranchWorkspaceSnapshot:
    """Complete snapshot of files bound to a logical exploration branch."""

    session_id: str
    branch_name: str
    stashed_files: Dict[str, ShadowStashFileRecord] = field(default_factory=dict)
    snapshot_hash: str = ""
    is_pristine: bool = False


@dataclass(frozen=True)
class WorkspaceStashConflictWarning:
    """Warning descriptor for overlapping dirty modifications across branches."""

    relative_path: str
    source_branch_hash: str
    target_branch_hash: str
    conflict_reason: str


@dataclass(frozen=True)
class WorkspaceStashReceipt:
    """Receipt certifying branch switch workspace state synchronization and file integrity."""

    receipt_id: str
    session_id: str
    source_branch: str
    target_branch: str
    stashed_files_count: int
    restored_files_count: int
    conflicts_detected_count: int
    synchronization_hash: str
