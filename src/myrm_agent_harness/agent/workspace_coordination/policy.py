"""Policy helpers for parallel subagent workspace safety."""

from __future__ import annotations

from dataclasses import replace

from myrm_agent_harness.agent.sub_agents.types import SubagentConfig, WorkspacePolicy


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
) -> tuple[SubagentConfig, dict[str, object]]:
    """Use isolated copy + deferred merge when multiple writers share a workspace."""
    if readonly or not parallel_write_batch:
        return config, child_context
    if config.workspace_policy != WorkspacePolicy.INHERIT:
        return config, child_context

    updated_config = replace(config, workspace_policy=WorkspacePolicy.ISOLATED_COPY)
    updated_context = {
        **child_context,
        "_defer_workspace_merge": True,
        "_parallel_write_batch": True,
    }
    return updated_config, updated_context
