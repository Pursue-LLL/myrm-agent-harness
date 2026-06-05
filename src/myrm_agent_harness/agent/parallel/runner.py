"""Shared parallel subagent execution for batch delegate and swarm fission."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from inspect import isawaitable
from typing import TYPE_CHECKING, cast

from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.parallel.config import DEFAULT_MAX_BATCH_PARALLEL
from myrm_agent_harness.agent.parallel.summary import (
    batch_summary,
    inject_capacity_signal,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from myrm_agent_harness.agent.base_agent import BaseAgent
    from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch import (
        TaskRequest,
    )
    from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
        _BatchBudgetAdmission,
    )

logger = get_agent_logger(__name__)


async def run_parallel_task_requests(
    *,
    parent_agent: BaseAgent,
    delegate_tool: BaseTool,
    tasks: list[TaskRequest],
    wait: bool = True,
    race: bool = False,
    skip_merge: bool = False,
    max_concurrent: int | None = None,
    budget_admission: _BatchBudgetAdmission | None = None,
    on_progress: Callable[[int, str, dict[str, object] | None], Awaitable[None]] | None = None,
) -> dict[str, object]:
    """Run TaskRequest items concurrently via an existing delegate_task tool."""
    if not tasks:
        return {"success": False, "error": "No tasks provided."}

    if max_concurrent is not None:
        effective_concurrent = max(1, min(max_concurrent, len(tasks), DEFAULT_MAX_BATCH_PARALLEL))
    else:
        effective_concurrent = 3 if race else 1
    semaphore = asyncio.Semaphore(effective_concurrent)

    async def _run_task(task: TaskRequest, index: int) -> dict[str, object]:
        if on_progress:
            await on_progress(index, "running", None)
        async with semaphore:
            coroutine = getattr(delegate_tool, "coroutine", None)
            if coroutine is None:
                err_res = {
                    "success": False,
                    "error": "delegate_task tool has no async coroutine",
                    "task_index": index,
                    "agent_type": task.agent_type,
                }
                if on_progress:
                    await on_progress(index, "failed", err_res)
                return err_res
            res = await coroutine(
                agent_type=task.agent_type,
                objective=task.objective,
                context_files=task.context_files,
                context=task.context,
                wait=wait or race,
                readonly=task.readonly,
                complexity_tier=task.complexity_tier,
                role=task.role,
                verifier_prompt=task.verifier_prompt,
                verifier_agent_type=task.verifier_agent_type,
                max_verification_rounds=task.max_verification_rounds,
            )
            if isinstance(res, dict):
                res.setdefault("agent_type", task.agent_type)
                res["task_index"] = index
                if on_progress:
                    status = "completed" if res.get("success") else "failed"
                    await on_progress(index, status, res)
                return res

            err_res = {
                "success": False,
                "error": str(res),
                "task_index": index,
                "agent_type": task.agent_type,
            }
            if on_progress:
                await on_progress(index, "failed", err_res)
            return err_res

    if race:
        pending_tasks: set[asyncio.Task[dict[str, object]]] = {
            asyncio.create_task(_run_task(task, index)) for index, task in enumerate(tasks)
        }
        winner_result: dict[str, object] | None = None
        failed_results: list[object] = []

        while pending_tasks:
            done, pending_tasks = await asyncio.wait(pending_tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                try:
                    res = task.result()
                    if isinstance(res, dict) and res.get("success"):
                        winner_result = res
                        break
                    failed_results.append(res)
                except Exception as exc:
                    logger.warning("A speculative execution task failed: %s", exc)
                    failed_results.append({"success": False, "error": str(exc)})

            if winner_result:
                sync_back_fn = winner_result.get("_workspace_sync_back")
                if callable(sync_back_fn):
                    try:
                        sync_result = sync_back_fn()
                        if isawaitable(sync_result):
                            await cast("Awaitable[object]", sync_result)
                        winner_result["race_merge_status"] = "success"
                        del winner_result["_workspace_sync_back"]
                    except Exception as exc:
                        logger.error("Error syncing speculative execution workspace: %s", exc)
                        winner_result["race_merge_status"] = "error"
                        winner_result["race_merge_error"] = str(exc)

                for task in pending_tasks:
                    task.cancel()
                break

        if winner_result:
            return inject_capacity_signal(
                {
                    "success": True,
                    "status": "completed",
                    "race_winner": True,
                    "result": winner_result,
                    "budget_admission": (budget_admission.to_dict() if budget_admission else None),
                },
                parent_agent,
            )

        normalized_failures = [
            res if isinstance(res, dict) else {"success": False, "error": str(res)} for res in failed_results
        ]
        return inject_capacity_signal(
            {
                "success": False,
                "status": "failed",
                "error": "All speculative execution tasks failed.",
                "failed_results": failed_results,
                **batch_summary(normalized_failures),
                "budget_admission": (budget_admission.to_dict() if budget_admission else None),
            },
            parent_agent,
        )

    parallel_write_batch = sum(1 for task in tasks if not task.readonly) > 1
    if parallel_write_batch:
        parent_agent._parallel_write_batch_active = True
    try:
        coros = [_run_task(task, index) for index, task in enumerate(tasks)]
        gathered = await asyncio.gather(*coros, return_exceptions=True)
    finally:
        if parallel_write_batch:
            delattr(parent_agent, "_parallel_write_batch_active")

    final_results: list[dict[str, object]] = []
    for index, gathered_result in enumerate(gathered):
        if isinstance(gathered_result, Exception):
            final_results.append(
                {
                    "success": False,
                    "error": str(gathered_result),
                    "task_index": index,
                    "agent_type": tasks[index].agent_type,
                }
            )
        elif isinstance(gathered_result, dict):
            final_results.append(gathered_result)
        else:
            final_results.append(
                {
                    "success": False,
                    "error": str(gathered_result),
                    "task_index": index,
                    "agent_type": tasks[index].agent_type,
                }
            )

    payload: dict[str, object] = {
        **batch_summary(final_results),
        "results": final_results,
        "budget_admission": (budget_admission.to_dict() if budget_admission else None),
    }
    if parallel_write_batch and wait and not race and not skip_merge:
        from myrm_agent_harness.agent.workspace_coordination.batch_merge import (
            merge_batch_workspace_sync_backs,
        )

        payload.update(await merge_batch_workspace_sync_backs(final_results))

    return inject_capacity_signal(payload, parent_agent)
