"""Git Worktree Multi-Branch Parallel Session Isolation and State Matrix Suite.

Provides deep session-to-worktree CWD binding, adaptive worktree context restoration,
project-root hierarchy aggregation, and safe removal guards protecting dirty files.

[INPUT]
- agent.context_management.worktree_isolation.worktree_isolation_types::SessionWorktreeBinding,
  WorktreeDescriptor, WorktreeHygieneReport, WorktreeHygieneStatus, WorktreeRemovalPolicy,
  WorktreeRemovalResult (POS: Type definitions for Git Worktree Multi-Branch Parallel Session Isolation and
  State Matrix.)
-
  agent.context_management.worktree_isolation.worktree_session_isolation_engine::WorktreeSessionIsolationEngine
  (POS: Core implementation of Git Worktree Multi-Branch Parallel Session Isolation Engine.)

[OUTPUT]
- Re-exports: SessionWorktreeBinding, WorktreeDescriptor, WorktreeHygieneReport, WorktreeHygieneStatus,
  WorktreeRemovalPolicy, WorktreeRemovalResult, WorktreeSessionIsolationEngine

[POS]
Git Worktree Multi-Branch Parallel Session Isolation and State Matrix Suite.
"""

from .worktree_isolation_types import (
    SessionWorktreeBinding,
    WorktreeDescriptor,
    WorktreeHygieneReport,
    WorktreeHygieneStatus,
    WorktreeRemovalPolicy,
    WorktreeRemovalResult,
)
from .worktree_session_isolation_engine import (
    WorktreeSessionIsolationEngine,
)

__all__ = [
    "SessionWorktreeBinding",
    "WorktreeDescriptor",
    "WorktreeHygieneReport",
    "WorktreeHygieneStatus",
    "WorktreeRemovalPolicy",
    "WorktreeRemovalResult",
    "WorktreeSessionIsolationEngine",
]
