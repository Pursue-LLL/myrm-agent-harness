"""Workspace execution coordination for parallel subagents.

[POS] Top-level workspace coordination module entry.
[INPUT] Tasks, SubagentConfig, sync-backs.
[OUTPUT] Worktree context, batch merge results, isolation policies, review-merge gates.
"""

from myrm_agent_harness.agent.workspace_coordination.git_worktree import (
    build_worktree_context_note,
    commit_worktree_isolated,
    create_subagent_worktree,
    finalize_subagent_worktree,
    resolve_repo_root,
)
from myrm_agent_harness.agent.workspace_coordination.isolated_commit_guard import (
    CommitIntent,
    CommitResult,
    build_commit_args,
    build_isolated_commit_env,
    run_isolated_commit,
)
from myrm_agent_harness.agent.workspace_coordination.merge.batch_merge import (
    merge_batch_workspace_sync_backs,
)
from myrm_agent_harness.agent.workspace_coordination.policy import (
    apply_parallel_write_isolation,
    count_parallel_writers,
)

__all__ = [
    "CommitIntent",
    "CommitResult",
    "apply_parallel_write_isolation",
    "build_commit_args",
    "build_isolated_commit_env",
    "build_worktree_context_note",
    "commit_worktree_isolated",
    "count_parallel_writers",
    "create_subagent_worktree",
    "finalize_subagent_worktree",
    "merge_batch_workspace_sync_backs",
    "resolve_repo_root",
    "run_isolated_commit",
]
