"""Workspace shadow stash and branch switch artifact integrity package facade.

[INPUT]
- None (package facade re-exporting stash engine, types, and orchestration suite)

[OUTPUT]
- FileStashKind
- ShadowStashFileRecord
- BranchWorkspaceSnapshot
- WorkspaceStashConflictWarning
- WorkspaceStashReceipt
- ShadowStashEngine
- BranchSwitchWorkspaceStashAndArtifactIntegritySuite

[POS]
Workspace shadow stash and branch switch artifact integrity package facade.
"""

from __future__ import annotations

from .shadow_stash_engine import ShadowStashEngine
from .workspace_branch_stash_suite import BranchSwitchWorkspaceStashAndArtifactIntegritySuite
from .workspace_stash_types import (
    BranchWorkspaceSnapshot,
    FileStashKind,
    ShadowStashFileRecord,
    WorkspaceStashConflictWarning,
    WorkspaceStashReceipt,
)

__all__ = [
    "FileStashKind",
    "ShadowStashFileRecord",
    "BranchWorkspaceSnapshot",
    "WorkspaceStashConflictWarning",
    "WorkspaceStashReceipt",
    "ShadowStashEngine",
    "BranchSwitchWorkspaceStashAndArtifactIntegritySuite",
]
