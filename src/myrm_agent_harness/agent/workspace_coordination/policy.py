"""Policy helpers for parallel subagent workspace safety."""

from __future__ import annotations

from dataclasses import replace

from myrm_agent_harness.agent.sub_agents.types import SubagentConfig, WorkspacePolicy
from myrm_agent_harness.agent.workspace_coordination.git_worktree import (
    build_worktree_context_note,
    create_subagent_worktree,
)


def count_parallel_writers(tasks: object) -> int:
    """Count non-readonly tasks in a batch delegate payload."""
    if not isinstance(tasks, list):
        return 0
    writers = 0
    for item in tasks:
        readonly = getattr(item, "readonly", False)
        if isinstance(item, dict):
            readonly = bool(item.get("readonly", False))
        if not readonly:
            writers += 1
    return writers


def apply_parallel_write_isolation(
    *,
    config: SubagentConfig,
    child_context: dict[str, object],
    readonly: bool,
    parallel_write_batch: bool,
    prefer_git_worktree: bool = True,
) -> tuple[SubagentConfig, dict[str, object]]:
    """Use git worktree or isolated copy + deferred merge when multiple writers share a workspace."""
    if readonly or not parallel_write_batch:
        return config, child_context
    if config.workspace_policy != WorkspacePolicy.INHERIT:
        return config, child_context

    if prefer_git_worktree:
        from myrm_agent_harness.agent.workspace_coordination.git_worktree import (
            build_worktree_context_note,
            create_subagent_worktree,
        )

        parent_ws = str(child_context.get("workspace_path") or child_context.get("workspace") or "")
        wt_info = create_subagent_worktree(parent_ws) if parent_ws else None
        if wt_info:
            note = build_worktree_context_note(wt_info)
            updated_config = replace(
                config,
                workspace_policy=WorkspacePolicy.GIT_WORKTREE,
                system_prompt=config.system_prompt + note,
            )
            updated_context = {
                **child_context,
                "workspace_path": wt_info["path"],
                "_git_worktree_info": wt_info,
                "_parallel_write_batch": True,
            }
            return updated_config, updated_context

    updated_config = replace(config, workspace_policy=WorkspacePolicy.ISOLATED_COPY)
    updated_context = {
        **child_context,
        "_defer_workspace_merge": True,
        "_parallel_write_batch": True,
    }
    return updated_config, updated_context
