"""Batch and parallel delegation tool factories.

[INPUT]
- _delegate_budget::_BatchBudgetAdmission, _admit_race_budget (POS: Budget admission for race mode)
- sub_agents.types::SubagentCatalog, DelegateRole
- parallel.runner::run_parallel_task_requests (POS: Parallel task execution engine)

[OUTPUT]
- TaskRequest: Pydantic model for a single delegation task
- BatchDelegateInput: Pydantic model for batch delegation input schema
- create_delegate_parallel_tasks_tool: Swarm Fission interrupt tool (yield-resume)
- create_batch_delegate_tasks_tool: Budget-aware concurrent batch delegation

[POS]
Batch and parallel delegation tool factories for the delegate_task tool family.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from langchain.tools import tool
from pydantic import BaseModel, Field

from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
    _admit_race_budget,
    _BatchBudgetAdmission,
)
from myrm_agent_harness.agent.sub_agents.types import (
    DelegateRole,
    SubagentCatalog,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.agent.base_agent import BaseAgent

logger = get_agent_logger(__name__)

_DEFAULT_MAX_BATCH_TASKS = 5


class TaskRequest(BaseModel):
    agent_type: str = Field(description="Type of subagent")
    objective: str = Field(description="Core objective for the subagent")
    context_files: list[str] = Field(
        default_factory=list, description="Relevant file paths"
    )
    context: dict[str, object] | None = Field(
        default=None, description="Optional context data"
    )
    readonly: bool = Field(
        default=False,
        description="If true, subagent cannot write files or run bash commands",
    )
    complexity_tier: str | None = Field(
        default=None,
        description="Optional explicit complexity tier ('simple', 'standard', 'reasoning').",
    )
    role: DelegateRole = Field(
        default=DelegateRole.LEAF,
        description="Delegation role for this child task.",
    )


class BatchDelegateInput(BaseModel):
    tasks: list[TaskRequest] = Field(description="List of tasks to run concurrently")
    wait: bool = Field(
        default=True,
        description="Wait for all results (true) or return task_ids immediately (false)",
    )
    race: bool = Field(
        default=False,
        description=(
            "Speculative Execution: Run tasks in parallel, return the first successful "
            "result and cancel the rest. Useful for trying multiple solutions simultaneously."
        ),
    )
    max_concurrent: int | None = Field(
        default=None,
        description=(
            "Max parallel workers. Default: 3 for race mode, 1 for non-race. "
            "Set higher (e.g. 3-5) when tasks are independent."
        ),
    )


def create_delegate_parallel_tasks_tool(
    parent_agent: BaseAgent,
    tool_registry_getter: Callable[[], list[object]],
    catalog: SubagentCatalog,
    parent_type: str | None = None,
    allowed_types: list[str] | None = None,
) -> BaseTool:
    """Create a tool for Swarm Fission (Resumable Dynamic Fission)."""

    @tool("delegate_parallel_tasks_tool", args_schema=BatchDelegateInput)
    def delegate_parallel_tasks_func(
        tasks: list[TaskRequest],
        wait: bool = True,
        race: bool = False,
        max_concurrent: int | None = None,
    ) -> dict[str, object]:
        """Spawn multiple specialized subagents concurrently using Swarm Fission.

        Unlike batch_delegate_tasks, this tool uses Yield-Resume semantics.
        It immediately suspends the current agent, freeing up resources, and delegates
        the parallel tasks to the DAG orchestrator. Once all tasks complete, this agent
        will be resumed with the results.

        Use this for Deep Research, Bulk Code Review, or any heavy Map-Reduce workload
        to avoid timeouts and context rot.
        """
        if not tasks:
            return {"success": False, "error": "No tasks provided."}

        from langgraph.types import interrupt

        interrupt_payload = {
            "action_type": "swarm_fission",
            "tasks": [t.model_dump() for t in tasks],
        }

        decisions = interrupt(interrupt_payload)
        return {"success": True, "results": decisions}

    return delegate_parallel_tasks_func


def create_batch_delegate_tasks_tool(
    parent_agent: BaseAgent,
    tool_registry_getter: Callable[[], list[object]],
    catalog: SubagentCatalog,
    parent_type: str | None = None,
    allowed_types: list[str] | None = None,
    *,
    delegate_tool: BaseTool | None = None,
) -> BaseTool:
    """Create a tool to spawn multiple subagents concurrently.

    Args:
        delegate_tool: Pre-built delegate_task tool to reuse. When provided,
            avoids redundant closure construction on each batch invocation.
    """
    if delegate_tool is None:
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            create_delegate_task_tool,
        )

        delegate_tool = create_delegate_task_tool(
            parent_agent,
            tool_registry_getter,
            catalog,
            parent_type,
            allowed_types,
        )
    _delegate = delegate_tool

    @tool("batch_delegate_tasks_tool", args_schema=BatchDelegateInput)
    async def batch_delegate_tasks_func(
        tasks: list[TaskRequest],
        wait: bool = True,
        race: bool = False,
        max_concurrent: int | None = None,
    ) -> dict[str, object]:
        """Spawn multiple specialized subagents concurrently.

        Use wait=true to wait for all results.
        Use race=true for Speculative Execution: spawn multiple subagents to solve
        a hard problem in parallel. The first one to succeed wins.
        Use max_concurrent to control parallelism (default: 3 for race, 1 for non-race).
        """
        if not tasks:
            return {"success": False, "error": "No tasks provided."}

        max_batch = _DEFAULT_MAX_BATCH_TASKS
        if parent_type:
            try:
                parent_cfg = await catalog.resolve(parent_type)
                if parent_cfg and parent_cfg.max_batch_size > 0:
                    max_batch = parent_cfg.max_batch_size
            except Exception as e:
                logger.debug("Failed to resolve max_batch_size for %s: %s", parent_type, e)
        if len(tasks) > max_batch:
            return {
                "success": False,
                "status": "budget_exceeded",
                "reason": "batch_size_exceeded",
                "error": (
                    f"Too many batch delegation tasks: {len(tasks)}/{max_batch}. "
                    "Split the work into smaller batches."
                ),
            }

        budget_admission: _BatchBudgetAdmission | None = None
        if race:
            try:
                budget_admission = await _admit_race_budget(
                    parent_agent=parent_agent,
                    catalog=catalog,
                    tasks=tasks,
                )
                if budget_admission.status == "downgraded":
                    logger.warning(
                        "Race delegation downgraded to sequential mode: reason=%s estimated_cost=%s remaining_budget=%s",
                        budget_admission.reason,
                        budget_admission.estimated_cost_usd,
                        budget_admission.remaining_budget_usd,
                    )
                    race = False
            except Exception as e:
                logger.warning("Failed to check budget for race mode: %s", e)
                budget_admission = _BatchBudgetAdmission(
                    status="unavailable",
                    reason="budget_admission_error",
                )

        from myrm_agent_harness.agent.parallel.runner import run_parallel_task_requests

        return await run_parallel_task_requests(
            parent_agent=parent_agent,
            delegate_tool=_delegate,
            tasks=tasks,
            wait=wait,
            race=race,
            max_concurrent=max_concurrent,
            budget_admission=budget_admission,
        )

    return batch_delegate_tasks_func
