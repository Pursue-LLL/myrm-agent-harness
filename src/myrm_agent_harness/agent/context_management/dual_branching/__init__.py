"""Dual-Branching Session Fork and In-Place Turn Rewind Suite.

Provides tree-structured DAG conversation tracking, "New Session From Here" deep cloning,
"Edit From Here" non-destructive version branching, and active timeline projection.
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
