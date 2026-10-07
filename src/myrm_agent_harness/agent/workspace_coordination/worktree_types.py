"""Types and models for worktree.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- MergeStrategy: Supported branch merge strategies for subagent workspaces.
- WorktreeIsolationConfig: Configuration governing subagent worktree provisioning and pruning.
- SubagentWorktreeMeta: Strongly-typed metadata tracking an allocated subagent git worktree.
- WorktreeFileChange: Detailed file-level mutation metadata within an isolated worktree.
- SubagentReviewSummary: Structured inspection report of subagent mutations ready for review.
- MergePrecheckResult: Result of dry-run pre-flight merge validation.
- WorktreeMergeResult: Execution outcome of a worktree branch review and merge gate.

[POS]
Types and models for worktree.
"""

# ============================================================================
# Git Worktree Multi-Subagent Isolation & Review-Merge Types (Item 151)
# Strict typed contracts for zero-collision workspace isolation, structured
# commit review, pre-flight conflict detection, and atomic branch merge gates.
# ============================================================================

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class MergeStrategy(StrEnum):
    """Supported branch merge strategies for subagent workspaces."""

    SQUASH = "squash"
    MERGE_COMMIT = "merge_commit"
    FAST_FORWARD_ONLY = "ff_only"


@dataclass(slots=True)
class WorktreeIsolationConfig:
    """Configuration governing subagent worktree provisioning and pruning."""

    worktrees_dirname: str = ".worktrees"
    branch_namespace: str = "myrm-subagent"
    auto_prune_clean: bool = True
    git_timeout_seconds: int = 30


@dataclass(slots=True)
class SubagentWorktreeMeta:
    """Strongly-typed metadata tracking an allocated subagent git worktree."""

    subagent_id: str
    worktree_path: str
    branch_name: str
    repo_root: str
    base_commit: str
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, str | float]:
        """Serializes worktree metadata to dictionary."""
        return {
            "subagent_id": self.subagent_id,
            "worktree_path": self.worktree_path,
            "branch_name": self.branch_name,
            "repo_root": self.repo_root,
            "base_commit": self.base_commit,
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class WorktreeFileChange:
    """Detailed file-level mutation metadata within an isolated worktree."""

    file_path: str
    status: str  # "M" (modified), "A" (added), "D" (deleted), "R" (renamed)
    insertions: int = 0
    deletions: int = 0

    def to_dict(self) -> dict[str, str | int]:
        """Serializes file change entry to dictionary."""
        return {
            "file_path": self.file_path,
            "status": self.status,
            "insertions": self.insertions,
            "deletions": self.deletions,
        }


@dataclass(slots=True)
class SubagentReviewSummary:
    """Structured inspection report of subagent mutations ready for review."""

    subagent_id: str
    branch_name: str
    worktree_path: str
    base_commit: str
    head_commit: str
    commits_ahead: int
    commit_messages: list[str] = field(default_factory=list)
    is_dirty: bool = False
    changed_files: list[str] = field(default_factory=list)
    file_changes: list[WorktreeFileChange] = field(default_factory=list)
    total_insertions: int = 0
    total_deletions: int = 0
    diff_stat: str = ""

    def to_dict(self) -> dict[str, str | int | bool | list[str] | list[dict[str, str | int]]]:
        """Serializes review summary to dictionary."""
        return {
            "subagent_id": self.subagent_id,
            "branch_name": self.branch_name,
            "worktree_path": self.worktree_path,
            "base_commit": self.base_commit,
            "head_commit": self.head_commit,
            "commits_ahead": self.commits_ahead,
            "commit_messages": list(self.commit_messages),
            "is_dirty": self.is_dirty,
            "changed_files": list(self.changed_files),
            "file_changes": [f.to_dict() for f in self.file_changes],
            "total_insertions": self.total_insertions,
            "total_deletions": self.total_deletions,
            "diff_stat": self.diff_stat,
        }


@dataclass(slots=True)
class MergePrecheckResult:
    """Result of dry-run pre-flight merge validation."""

    can_merge: bool
    has_conflicts: bool
    conflicting_files: list[str] = field(default_factory=list)
    precheck_message: str = ""

    def to_dict(self) -> dict[str, bool | str | list[str]]:
        """Serializes precheck result to dictionary."""
        return {
            "can_merge": self.can_merge,
            "has_conflicts": self.has_conflicts,
            "conflicting_files": list(self.conflicting_files),
            "precheck_message": self.precheck_message,
        }


@dataclass(slots=True)
class WorktreeMergeResult:
    """Execution outcome of a worktree branch review and merge gate."""

    success: bool
    strategy: MergeStrategy
    target_branch: str
    merged_commit: str = ""
    conflicts: list[str] = field(default_factory=list)
    error_message: str = ""
    worktree_pruned: bool = False
    branch_deleted: bool = False

    def to_dict(self) -> dict[str, bool | str | list[str]]:
        """Serializes merge result to dictionary."""
        return {
            "success": self.success,
            "strategy": str(self.strategy),
            "target_branch": self.target_branch,
            "merged_commit": self.merged_commit,
            "conflicts": list(self.conflicts),
            "error_message": self.error_message,
            "worktree_pruned": self.worktree_pruned,
            "branch_deleted": self.branch_deleted,
        }
