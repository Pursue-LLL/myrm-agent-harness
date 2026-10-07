"""Package facade for mobility.

[INPUT]
- agent.context_management.mobility.mobility_types::FileChangeKind, MergeConflictItem, OffloadTargetKind,
  OffloadTransferReceipt, SyncMergeReport, WorkspaceCapsule, WorkspaceFileEntry (POS: Types and models for
  mobility.)
- agent.context_management.mobility.workspace_capsule_engine::BidirectionalMergeGuard,
  CloudWorkerOffloadGateway, WorkspaceCapsulePacker (POS: Serializes, packs, and validates portable workspace
  state capsules.)

[OUTPUT]
- Re-exports: BidirectionalMergeGuard, CloudWorkerOffloadGateway, FileChangeKind, MergeConflictItem,
  OffloadTargetKind, OffloadTransferReceipt, SyncMergeReport, WorkspaceCapsule, WorkspaceCapsulePacker,
  WorkspaceFileEntry

[POS]
Package facade for mobility.
"""

# ============================================================================
# Session Workspace Mobility & Cloud Offload Package (Item 163)
# ============================================================================

from .mobility_types import (
    FileChangeKind,
    MergeConflictItem,
    OffloadTargetKind,
    OffloadTransferReceipt,
    SyncMergeReport,
    WorkspaceCapsule,
    WorkspaceFileEntry,
)
from .workspace_capsule_engine import (
    BidirectionalMergeGuard,
    CloudWorkerOffloadGateway,
    WorkspaceCapsulePacker,
)

__all__ = [
    "BidirectionalMergeGuard",
    "CloudWorkerOffloadGateway",
    "FileChangeKind",
    "MergeConflictItem",
    "OffloadTargetKind",
    "OffloadTransferReceipt",
    "SyncMergeReport",
    "WorkspaceCapsule",
    "WorkspaceCapsulePacker",
    "WorkspaceFileEntry",
]
