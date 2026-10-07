"""Dual-Branching Session Fork and In-Place Turn Rewind Suite.

Provides tree-structured DAG conversation tracking, "New Session From Here" deep cloning,
"Edit From Here" non-destructive version branching, and active timeline projection.

[INPUT]
- agent.context_management.dual_branching.dual_branching_session_engine::DualBranchingSessionEngine (POS: Core
  implementation of Dual-Branching Session Fork and In-Place Turn Rewind Engine.)
- agent.context_management.dual_branching.dual_branching_types::BranchDescriptor, BranchingPosture,
  ForkCloneResult, TreeNodeMessage, VersionNavigationInfo (POS: Type definitions for Dual-Branching Session
  Fork and In-Place Turn Rewind Suite.)

[OUTPUT]
- Re-exports: BranchDescriptor, BranchingPosture, DualBranchingSessionEngine, ForkCloneResult,
  TreeNodeMessage, VersionNavigationInfo

[POS]
Dual-Branching Session Fork and In-Place Turn Rewind Suite.
"""

from .dual_branching_session_engine import (
    DualBranchingSessionEngine,
)
from .dual_branching_types import (
    BranchDescriptor,
    BranchingPosture,
    ForkCloneResult,
    TreeNodeMessage,
    VersionNavigationInfo,
)

__all__ = [
    "BranchDescriptor",
    "BranchingPosture",
    "DualBranchingSessionEngine",
    "ForkCloneResult",
    "TreeNodeMessage",
    "VersionNavigationInfo",
]
