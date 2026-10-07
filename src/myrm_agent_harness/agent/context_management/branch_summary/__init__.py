"""Branch Summarization and Selective Merge-Back Suite (Item 202).

Provides tracking for read/modified files across branch iterations,
produces concise BranchSummaryResult contracts, and coordinates zero-loss
selective merges back into parent sessions.
"""

from __future__ import annotations

from myrm_agent_harness.agent.context_management.branch_summary.branch_summary_engine import (
    BranchFileOperationsTracker,
    BranchSelectiveMergeEngine,
)
from myrm_agent_harness.agent.context_management.branch_summary.branch_summary_types import (
    BranchFileOperations,
    BranchMergeConflictWarning,
    BranchSummaryResult,
    FileActionKind,
    SelectiveMergePolicy,
    TrackedFileOperation,
)

__all__ = [
    "BranchFileOperations",
    "BranchFileOperationsTracker",
    "BranchMergeConflictWarning",
    "BranchSelectiveMergeEngine",
    "BranchSummaryResult",
    "FileActionKind",
    "SelectiveMergePolicy",
    "TrackedFileOperation",
]
