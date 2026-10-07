"""Git Worktree Multi-Branch Parallel Session Isolation and State Matrix Suite.

Provides deep session-to-worktree CWD binding, adaptive worktree context restoration,
project-root hierarchy aggregation, and safe removal guards protecting dirty files.
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
