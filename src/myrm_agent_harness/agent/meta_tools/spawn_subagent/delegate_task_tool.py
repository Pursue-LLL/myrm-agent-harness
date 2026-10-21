"""Delegate task meta-tool (multi-mode: single|batch|parallel|council|alternatives).

[INPUT]
- _delegate_input (POS: LLM-facing args schema of delegate_task)
- _delegate_single (POS: Single-mode execution: admission, spawn, verification, approval resume)
- _delegate_budget (POS: Budget admission, policy enforcement, delegation call fingerprint, dynamic description)
- _delegate_batch (POS: Batch and parallel delegation execution engine)
- _delegate_cognitive (POS: Council and alternatives mode execution)
- agent.sub_agents.types::SubagentCatalog, DelegateRole
- agent.sub_agents.spawn_prep::coerce_spawn_readonly (POS: readonly floor shared with Dynamic Workflow)
- agent.base_agent::BaseAgent (POS: Base agent with streaming, token tracking, and artifacts)
- langchain.tools::tool

[OUTPUT]
- create_delegate_task_tool: Unified delegate tool (mode=single|batch|parallel|council|alternatives)
- update_delegate_task_description: Async description refresher for catalog roster injection

[POS]
Unified delegate_task LLM tool: a router from `mode` to its executor. Single mode runs in _delegate_single.py,
batch/parallel modes in _delegate_batch.py, council/alternatives modes in _delegate_cognitive.py.
Budget admission, policy denial, the repeated-delegation fingerprint, and dynamic roster live in _delegate_budget.py.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Literal

from langchain.tools import tool

from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch import (
    TaskRequest,
    execute_batch_delegation,
    execute_parallel_delegation,
)
from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
    _build_dynamic_description,
)
from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_cognitive import (
    execute_cognitive_mode,
)
from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_input import DelegateTaskInput
from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_single import execute_single_delegation
from myrm_agent_harness.agent.sub_agents.types import (
    DelegateRole,
    SubagentCatalog,
)
from myrm_agent_harness.utils.runtime.cancellation import get_cancel_token

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.agent.base_agent import BaseAgent


def create_delegate_task_tool(
    parent_agent: BaseAgent,
    tool_registry_getter: Callable[[], list[BaseTool]],
    catalog: SubagentCatalog,
    parent_type: str | None = None,
    allowed_types: list[str] | None = None,
) -> BaseTool:
    """Create delegate_task tool for the parent agent.

    Args:
        parent_agent: The parent agent instance that can spawn children.
        tool_registry_getter: Function that returns available tools for subagent.
        catalog: The catalog to resolve subagent configurations.
        parent_type: Parent agent type (for nesting check).
        allowed_types: Restrict which agent types can be spawned (L0 type admission).
            None = all catalog types are available.

    Returns:
        delegate_task tool function.
    """

    _delegate_tool_holder: dict[str, BaseTool] = {}

    @tool("delegate_task_tool", args_schema=DelegateTaskInput)
    async def delegate_task_func(
        mode: Literal["single", "batch", "parallel", "council", "alternatives"] = "single",
        agent_type: str | None = None,
        objective: str | None = None,
        context_files: list[str] | None = None,
        context: dict[str, object] | None = None,
        wait: bool | None = None,
        readonly: bool = False,
        complexity_tier: str | None = None,
        role: DelegateRole = DelegateRole.LEAF,
        verifier_prompt: str | None = None,
        verifier_agent_type: str | None = None,
        max_verification_rounds: int = 2,
        tasks: list[TaskRequest] | None = None,
        race: bool = False,
        tournament: bool = False,
        judge_criteria: str | None = None,
        max_concurrent: int | None = None,
        expert_agent_types: list[str] | None = None,
        cross_review_rounds: int = 1,
        chair_agent_type: str | None = None,
    ) -> dict[str, object]:
        """Delegate work to specialized subagents (mode=single|batch|parallel|council|alternatives)."""
        if mode == "parallel":
            batch_tasks = tasks or []
            return execute_parallel_delegation(parent_agent, batch_tasks)

        if mode == "batch":
            batch_tasks = tasks or []
            bound_tool = _delegate_tool_holder.get("tool")
            if bound_tool is None:
                return {"success": False, "error": "Internal error: delegate_task_tool not initialized."}
            batch_wait = wait if wait is not None else True
            return await execute_batch_delegation(
                parent_agent=parent_agent,
                delegate_tool=bound_tool,
                catalog=catalog,
                tasks=batch_tasks,
                wait=batch_wait,
                race=race,
                tournament=tournament,
                judge_criteria=judge_criteria,
                max_concurrent=max_concurrent,
                parent_type=parent_type,
            )

        if mode in ("council", "alternatives"):
            from myrm_agent_harness.agent.sub_agents.spawn_prep import coerce_spawn_readonly

            parent_ctx = getattr(parent_agent, "_last_context", None) or {}
            readonly = coerce_spawn_readonly(parent_agent, readonly)
            return await execute_cognitive_mode(
                mode=mode,
                parent_agent=parent_agent,
                catalog=catalog,
                objective=objective,
                expert_agent_types=expert_agent_types,
                context=context,
                context_files=context_files or [],
                tool_registry_getter=tool_registry_getter,
                readonly=readonly,
                cross_review_rounds=cross_review_rounds,
                chair_agent_type=chair_agent_type,
                cancel_token=get_cancel_token(),
                session_id=str(parent_ctx.get("session_id", "")),
                allowed_types=allowed_types,
            )

        return await execute_single_delegation(
            parent_agent=parent_agent,
            tool_registry_getter=tool_registry_getter,
            catalog=catalog,
            parent_type=parent_type,
            allowed_types=allowed_types,
            agent_type=agent_type,
            objective=objective,
            context_files=context_files,
            context=context,
            wait=wait,
            readonly=readonly,
            complexity_tier=complexity_tier,
            role=role,
            verifier_prompt=verifier_prompt,
            verifier_agent_type=verifier_agent_type,
            max_verification_rounds=max_verification_rounds,
        )

    _delegate_tool_holder["tool"] = delegate_task_func
    return delegate_task_func


async def update_delegate_task_description(
    delegate_tool: BaseTool,
    catalog: SubagentCatalog,
    allowed_types: list[str] | None = None,
) -> None:
    """Update delegate_task tool description with available agent types from catalog.

    Call this in an async context after creating the tool to inject
    dynamic agent type information into the tool description.
    """
    dynamic_desc = await _build_dynamic_description(catalog, allowed_types)
    delegate_tool.description = dynamic_desc


__all__ = [
    "TaskRequest",
    "create_delegate_task_tool",
    "update_delegate_task_description",
]
