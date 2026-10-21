"""Shared subagent spawn preparation for delegate and DW PTC paths.

[INPUT]
- sub_agents.types::SubagentConfig, ControlScope, MemoryIsolationPolicy, WorkspacePolicy
- agent.security.engine::disabled_permissions (POS: global permission deny probe for readonly floor)
- sub_agents.spawn_capability::parent_capability_handle (POS: the handle the running (delegating) agent is bound to, if any)
- core.security.ocap::CapabilityAction (POS: capability vocabulary: READ, WRITE, EXECUTE)
- workspace_coordination.policy::apply_parallel_write_isolation
- workspace_coordination.merge.merge_metadata::strip_merge_transient_inner_keys (POS: merge metadata key SSOT)

[OUTPUT]
- coerce_spawn_readonly: parent Security Profile file_write deny or a parent handle without WRITE → readonly floor
- apply_readonly_to_config: READ_ONLY_SANDBOX policy + native mutating tool blocks (side-effect MCP tools are dropped by builder.filter_tools)
- build_spawn_child_context: the child's runtime context, taken only from the parent's workspace/session fields
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
from typing import TYPE_CHECKING, Protocol, cast

from myrm_agent_harness.agent.sub_agents.spawn_capability import parent_capability_handle
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
from myrm_agent_harness.core.security.ocap import CapabilityAction

if TYPE_CHECKING:
    from contextvars import Token

    from myrm_agent_harness.toolkits.memory.ephemeral import EphemeralMemoryManager
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager

logger = logging.getLogger(__name__)


class _CollaborativeMemoryHost(Protocol):
    """Parent agent that lazily owns the memory view its collaborative subagents share."""

    _collaborative_memory: EphemeralMemoryManager


# Native workspace mutators. MCP tools with side effects are dropped by ``builder.filter_tools``
# for every READ_ONLY_SANDBOX config, so they need no entry here.
_READONLY_BLOCKED_TOOLS = frozenset({"file_write_tool", "file_edit_tool", "bash_code_execute_tool"})
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
    """Force readonly when the parent cannot write itself.

    That is the case when its Security Profile globally denies file_write or when it runs under a
    capability handle without WRITE, so a read-only subagent cannot hand write access to its children.
    """
    if readonly:
        return True
    parent_handle = parent_capability_handle()
    if parent_handle is not None and CapabilityAction.WRITE not in parent_handle.actions:
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
    payload_hashes: list[str] | None = None,
) -> dict[str, object]:
    """The child's runtime context: the parent's workspace/session fields and nothing the model supplied.

    Model-supplied ``context`` reaches the child as task text only. As runtime context it would let the
    model pick the workspace the child's executor binds to and the internal keys the merge pipeline reads.
    """
    child_context: dict[str, object] = {key: parent_ctx[key] for key in _PARENT_CONTEXT_KEYS if key in parent_ctx}
    if payload_hashes is not None:
        child_context["subagent_payload_hashes"] = payload_hashes
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
    reset_token: Token[MemoryManager | None] | None = None
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
                host = cast("_CollaborativeMemoryHost", parent_agent)
                if not hasattr(host, "_collaborative_memory"):
                    host._collaborative_memory = EphemeralMemoryManager(global_mem)
                reset_token = _memory_manager_var.set(host._collaborative_memory)
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
