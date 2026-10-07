"""Package facade for dual-track session entry operation and dynamic branch projection.

[INPUT]
- agent.context_management.branch_projection.branch_projection_engine::DualTrackBranchProjectionEngine (POS:
  Manages dual-track storage, zero-copy forking, LCA summarization, and projection.)
- agent.context_management.branch_projection.branch_projection_types::BranchSummary, EntryKind,
  OperationStatus, ProjectedContext, SessionEntry, SessionOperation, TokenUsage (POS: Types and data contracts
  for dual-track session tree and dynamic branch projection.)
- agent.context_management.branch_projection.lca_branch_summarizer::collect_departed_entries, find_lca,
  synthesize_branch_delta_summary (POS: LCA branch discovery and delta summarization for lossless cross-branch
  transitions.)

[OUTPUT]
- Re-exports: BranchSummary, DualTrackBranchProjectionEngine, EntryKind, OperationStatus, ProjectedContext,
  SessionEntry, SessionOperation, TokenUsage, collect_departed_entries, find_lca, synthesize_branch_delta_summary

[POS]
Dual-track session entry and operation branch projection package facade.
"""

from __future__ import annotations

from .branch_projection_engine import DualTrackBranchProjectionEngine
from .branch_projection_types import (
    BranchSummary,
    EntryKind,
    OperationStatus,
    ProjectedContext,
    SessionEntry,
    SessionOperation,
    TokenUsage,
)
from .lca_branch_summarizer import (
    collect_departed_entries,
    find_lca,
    synthesize_branch_delta_summary,
)

__all__ = [
    "BranchSummary",
    "DualTrackBranchProjectionEngine",
    "EntryKind",
    "OperationStatus",
    "ProjectedContext",
    "SessionEntry",
    "SessionOperation",
    "TokenUsage",
    "collect_departed_entries",
    "find_lca",
    "synthesize_branch_delta_summary",
]
