"""Swarm Fission execution — parallel spawn with TaskRequest fidelity."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.parallel.config import resolve_max_parallel_fission
from myrm_agent_harness.agent.parallel.resume_compact import (
    compact_batch_results_for_resume,
)
from myrm_agent_harness.agent.parallel.runner import run_parallel_task_requests
from myrm_agent_harness.agent.parallel.schemas import ParallelTaskResults

if TYPE_CHECKING:
    from myrm_agent_harness.agent.base_agent import BaseAgent
    from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
        TaskRequest,
    )


def parse_task_requests_from_payload(
    fission_payload: dict[str, object],
) -> list[TaskRequest]:
    raw_tasks = fission_payload.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise ValueError("Swarm fission payload missing tasks array.")
    tasks: list[TaskRequest] = []
    for item in raw_tasks:
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            TaskRequest,
        )

        if isinstance(item, TaskRequest):
            tasks.append(item)
        elif isinstance(item, dict):
            tasks.append(TaskRequest.model_validate(item))
    if not tasks:
        raise ValueError("Swarm fission payload contains no valid tasks.")
    return tasks


def resolve_delegate_tool(parent_agent: BaseAgent) -> BaseTool | None:
    cached_tools = getattr(parent_agent, "_cached_tools", None) or []
    user_tools = getattr(parent_agent, "user_tools", None) or []
    for tool in [*cached_tools, *user_tools]:
        if getattr(tool, "name", None) == "delegate_task_tool":
            return tool
    return None


def resolve_parent_workspace_path(parent_agent: BaseAgent) -> str | None:
    for attr in ("_runtime_context", "context", "_context"):
        ctx = getattr(parent_agent, attr, None)
        if isinstance(ctx, dict):
            workspace = ctx.get("workspace_path")
            if isinstance(workspace, str) and workspace:
                return workspace
    return None


async def execute_swarm_fission(
    parent_agent: BaseAgent,
    fission_payload: dict[str, object],
    *,
    max_concurrent: int | None = None,
    on_progress: Callable[[int, str, dict[str, object] | None], Awaitable[None]] | None = None,
) -> dict[str, object]:
    """Execute swarm fission tasks using the same spawn path as batch_delegate_tasks."""
    tasks = parse_task_requests_from_payload(fission_payload)
    delegate_tool = resolve_delegate_tool(parent_agent)
    if delegate_tool is None:
        return {
            "success": False,
            "status": "failed",
            "error": "Parent agent has no delegate_task tool installed.",
            "results": [],
            "total_count": len(tasks),
            "completed_count": 0,
            "failed_count": len(tasks),
            "failure_reasons": ["Parent agent has no delegate_task tool installed."],
            "all_success": False,
            "partial_success": False,
        }

    effective_concurrent = resolve_max_parallel_fission(max_concurrent)
    batch_result = await run_parallel_task_requests(
        parent_agent=parent_agent,
        delegate_tool=delegate_tool,
        tasks=tasks,
        wait=True,
        race=False,
        max_concurrent=effective_concurrent,
        on_progress=on_progress,
    )
    batch_result = compact_batch_results_for_resume(
        batch_result,
        workspace_path=resolve_parent_workspace_path(parent_agent),
    )
    return ParallelTaskResults.from_batch_dict(batch_result).to_resume_dict()
