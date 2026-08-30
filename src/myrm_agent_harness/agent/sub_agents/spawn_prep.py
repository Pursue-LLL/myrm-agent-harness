"""Shared subagent spawn preparation for delegate and DW PTC paths.

[INPUT]
- sub_agents.types::SubagentConfig, ControlScope, MemoryIsolationPolicy, WorkspacePolicy
- agent.security.engine::disabled_permissions (POS: global permission deny probe for readonly floor)
- workspace_coordination.policy::apply_parallel_write_isolation
- workspace_coordination.merge.merge_metadata::strip_merge_transient_inner_keys (POS: merge metadata key SSOT)

[OUTPUT]
- coerce_spawn_readonly: parent Security Profile file_write deny → readonly floor
- apply_readonly_to_config: readonly sandbox policy + mutating tool blocks
- build_spawn_child_context: workspace/session context fields
- apply_spawn_workspace_isolation: parallel writer ISOLATED_COPY promotion
- sanitize_spawn_result_for_store / spawn_result_for_store_after_merge: JSON-safe durable cache rows
- merge_candidate_from_spawn_dict: detect pending ISOLATED_COPY merge metadata
- MemoryIsolationScope: ContextVar memory manager for spawn lifetime

[POS]
Single SSOT for spawn prep so delegate_task_tool and SpawnSubagentTool stay aligned.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace

from myrm_agent_harness.agent.sub_agents.types import (
    ControlScope,
    MemoryIsolationPolicy,
    SubagentConfig,
    WorkspacePolicy,
)
from myrm_agent_harness.agent.workspace_coordination.merge.merge_metadata import (
    strip_merge_transient_inner_keys,
)
from myrm_agent_harness.agent.workspace_coordination.policy import (
    apply_parallel_write_isolation,
)

logger = logging.getLogger(__name__)

_READONLY_BLOCKED_TOOLS = frozenset(
    {
        "write_file",
        "execute_terminal_command",
        "bash_run_command",
        "git_commit",
    }
)
_READONLY_HINT = (
    "\n\n[READONLY MODE] You are in read-only mode. You can only read and analyze — "
    "do NOT attempt file writes, terminal commands, or git commits."
)
_MEMORY_WRITE_TOOLS = frozenset({"memory_save_tool", "memory_manage_tool"})

_PARENT_CONTEXT_KEYS = (
    "workspace_path",
    "workspace_binding",
    "workspaces_storage_root",
    "user_id",
    "session_id",
)


@dataclass(frozen=True)
class SpawnWorkspacePrep:
    """Config + context after workspace isolation policy."""

    config: SubagentConfig
    child_context: dict[str, object]


def coerce_spawn_readonly(parent_agent: object, readonly: bool) -> bool:
    """Force readonly when the parent Security Profile globally denies file_write."""
    if readonly:
        return True
    agent_config = getattr(parent_agent, "config", None)
    security_config = getattr(agent_config, "security_config", None)
    if security_config is None:
        return False
    from myrm_agent_harness.core.security.types import SecurityConfig

    if not isinstance(security_config, SecurityConfig):
        return False
    from myrm_agent_harness.agent.security.engine import disabled_permissions

    return "file_write" in disabled_permissions(
        ["file_write"],
        security_config.ruleset,
        security_config.capabilities,
    )


def apply_readonly_to_config(config: SubagentConfig, readonly: bool) -> SubagentConfig:
    """Apply readonly sandbox policy and block mutating tools."""
    if not readonly:
        return config
    return replace(
        config,
        workspace_policy=WorkspacePolicy.READ_ONLY_SANDBOX,
        disallowed_tools=config.disallowed_tools | _READONLY_BLOCKED_TOOLS,
        system_prompt=config.system_prompt + _READONLY_HINT,
    )


def enforce_spawn_policy_on_config(config: SubagentConfig) -> SubagentConfig:
    """LEAF scope depth cap and READ_ONLY_GLOBAL memory write blocks."""
    updated = config
    if updated.control_scope == ControlScope.LEAF:
        updated = replace(updated, max_spawn_depth=0)
    if updated.memory_isolation == MemoryIsolationPolicy.READ_ONLY_GLOBAL:
        updated = replace(updated, disallowed_tools=updated.disallowed_tools | _MEMORY_WRITE_TOOLS)
    return updated


def build_spawn_child_context(
    *,
    parent_ctx: dict[str, object],
    base_context: dict[str, object] | None = None,
    payload_hashes: list[str] | None = None,
) -> dict[str, object]:
    """Merge delegate/DW child context with parent workspace/session fields."""
    child_context: dict[str, object] = dict(base_context or {})
    if payload_hashes is not None:
        child_context["subagent_payload_hashes"] = payload_hashes
    for key in _PARENT_CONTEXT_KEYS:
        if key in parent_ctx and key not in child_context:
            child_context[key] = parent_ctx[key]
    return child_context


def build_child_context_from_parent_agent(parent_agent: object) -> dict[str, object]:
    """DW path: copy workspace/session keys from parent agent context."""
    parent_ctx = getattr(parent_agent, "context", None)
    if not isinstance(parent_ctx, dict):
        return {}
    return build_spawn_child_context(parent_ctx=parent_ctx)


def resolve_delegate_parallel_write_batch(parent_agent: object) -> bool:
    """True when delegate batch runner marked concurrent writers on parent."""
    return bool(getattr(parent_agent, "_parallel_write_batch_active", False))


def apply_spawn_workspace_isolation(
    *,
    config: SubagentConfig,
    child_context: dict[str, object],
    readonly: bool,
    parallel_write_batch: bool,
) -> SpawnWorkspacePrep:
    """Promote to ISOLATED_COPY when multiple non-readonly spawns share a workspace."""
    updated_config, updated_context = apply_parallel_write_isolation(
        config=config,
        child_context=child_context,
        readonly=readonly,
        parallel_write_batch=parallel_write_batch,
    )
    return SpawnWorkspacePrep(config=updated_config, child_context=updated_context)


@contextmanager
def memory_isolation_scope(
    *,
    parent_agent: object,
    config: SubagentConfig,
) -> Iterator[None]:
    """Set ephemeral/collaborative/read-only memory ContextVar for spawn lifetime."""
    reset_token: object | None = None
    try:
        from myrm_agent_harness.agent.skill_agent.context import (
            _memory_manager_var,
            get_memory_manager,
        )
        from myrm_agent_harness.toolkits.memory.ephemeral import (
            EphemeralMemoryManager,
            ReadOnlyMemoryView,
        )

        global_mem = get_memory_manager()
        if global_mem:
            if config.memory_isolation == MemoryIsolationPolicy.COLLABORATIVE_SESSION:
                if not hasattr(parent_agent, "_collaborative_memory"):
                    parent_agent._collaborative_memory = EphemeralMemoryManager(global_mem)
                reset_token = _memory_manager_var.set(parent_agent._collaborative_memory)
            elif config.memory_isolation == MemoryIsolationPolicy.READ_ONLY_GLOBAL:
                reset_token = _memory_manager_var.set(ReadOnlyMemoryView(global_mem))
            else:
                reset_token = _memory_manager_var.set(EphemeralMemoryManager(global_mem))
        yield
    finally:
        if reset_token is not None:
            try:
                from myrm_agent_harness.agent.skill_agent.context import (
                    _memory_manager_var,
                )

                _memory_manager_var.reset(reset_token)
            except Exception as exc:
                logger.warning("Failed to reset memory manager context var: %s", exc)


def merge_candidate_from_spawn_dict(result: dict[str, object]) -> bool:
    """True when result carries deferred ISOLATED_COPY merge metadata."""
    if not result.get("success"):
        return False
    inner = result.get("result")
    return isinstance(inner, dict) and "_isolated_child_workspace" in inner


def sanitize_spawn_result_for_store(result: dict[str, object]) -> dict[str, object]:
    """Strip non-JSON merge metadata before SQLite persistence."""
    had_pending_merge = merge_candidate_from_spawn_dict(result)
    out = dict(result)
    inner = out.get("result")
    if isinstance(inner, dict):
        out["result"] = strip_merge_transient_inner_keys(inner)
    if had_pending_merge and out.get("workspace_merge_status") != "merged":
        out["workspace_merge_status"] = "pending"
    return out


def spawn_result_for_store_after_merge(result: dict[str, object]) -> dict[str, object]:
    """Persistable spawn result after batch_merge completes."""
    out = sanitize_spawn_result_for_store(result)
    if result.get("workspace_merge_status") == "merged":
        out["workspace_merge_status"] = "merged"
    return out
