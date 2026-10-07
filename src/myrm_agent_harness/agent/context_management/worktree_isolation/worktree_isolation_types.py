"""Type definitions for Git Worktree Multi-Branch Parallel Session Isolation and State Matrix.

Provides immutable data contracts for worktree inventory, branch-to-session bindings,
working tree hygiene inspection, and safe removal policies.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- WorktreeHygieneStatus: Hygiene status of a git worktree directory.
- WorktreeRemovalPolicy: Policy governing worktree deletion safety.
- WorktreeDescriptor: Represents an isolated git worktree branch working directory.
- WorktreeHygieneReport: Hygiene inspection outcome reporting uncommitted or untracked changes.
- SessionWorktreeBinding: Immutable binding locking an agent session to a specific worktree directory.
- WorktreeRemovalResult: Result emitted after evaluating or executing worktree teardown.

[POS]
Type definitions for Git Worktree Multi-Branch Parallel Session Isolation and State Matrix.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import time


class WorktreeHygieneStatus(StrEnum):
    """Hygiene status of a git worktree directory."""

    CLEAN = "clean"
    DIRTY_UNCOMMITTED = "dirty_uncommitted"
    DIRTY_UNTRACKED = "dirty_untracked"
    LOCKED = "locked"


class WorktreeRemovalPolicy(StrEnum):
    """Policy governing worktree deletion safety."""

    SAFE_GUARD_BLOCK_IF_DIRTY = "safe_guard_block_if_dirty"
    FORCE_PURGE_OVERRIDE = "force_purge_override"


@dataclass(frozen=True)
class WorktreeDescriptor:
    """Represents an isolated git worktree branch working directory."""

    worktree_id: str
    project_root: str
    worktree_path: str
    branch_name: str
    head_commit: str
    is_main_checkout: bool = False
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class WorktreeHygieneReport:
    """Hygiene inspection outcome reporting uncommitted or untracked changes."""

    worktree_id: str
    status: WorktreeHygieneStatus
    uncommitted_files: tuple[str, ...] = field(default_factory=tuple)
    untracked_files: tuple[str, ...] = field(default_factory=tuple)
    is_safe_to_remove: bool = True
    inspected_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class SessionWorktreeBinding:
    """Immutable binding locking an agent session to a specific worktree directory."""

    session_id: str
    worktree_id: str
    bound_cwd: str
    branch_name: str
    bound_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class WorktreeRemovalResult:
    """Result emitted after evaluating or executing worktree teardown."""

    worktree_id: str
    removed: bool
    is_blocked_by_dirty: bool
    uncommitted_count: int
    untracked_count: int
    policy_applied: WorktreeRemovalPolicy
    message: str
