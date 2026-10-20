"""Subagent composition patterns — chain, batch, alternatives, and verified orchestration.

Higher-level execution patterns built on top of SubagentManager.spawn_child.

[INPUT]
- agent.sub_agents.result_output::answer_text (POS: Subagent result payload (answer text, or a dict carrying isolation merge metadata).)
- agent.sub_agents.types::SubagentConfig, SubAgentResult, SubAgentStatus, WorkspacePolicy (POS: Subagent subsystem core type definitions. Defines all subagent-related data types, enums, and protocols.)
- agent.sub_agents._orchestrator_council::run_council (POS: Council orchestration — multi-expert parallel analysis with cross-review debate and chair synthesis.)
- agent.sub_agents._orchestrator_verification::VerificationVerdict, run_with_verification, verify_worker_output (POS: Adversarial verification orchestration — Worker -> Verifier -> Retry loop with workspace diff injection and a fail-closed BLOCKED outcome when no conclusive verdict exists.)
- agent.workspace_coordination.merge.batch_merge::discard_deferred_isolated_workspaces (POS: Serial lifecycle for deferred ISOLATED_COPY workspaces after parallel batch delegation.)

[OUTPUT]
- run_chain: Execute subagents in chain: A -> B -> C, each receiving previous result.
- run_alternatives: Spawn N subagents in parallel for the same task; return text results without merging isolated workspaces (discarded after completion).
- run_council: Multi-expert council orchestration with cross-review rounds and chair synthesis.
- wait_children: Wait for multiple child tasks to complete and aggregate results.
- run_with_verification: Execute a worker then verify via an adversarial verifier, retrying on failure.
- VerificationVerdict: Parsed verdict from a Verifier agent's structured JSON output.
- verify_worker_output: Verify an existing worker output with a verifier-only round (``None`` = inconclusive round).

[POS]
Subagent composition patterns — chain, batch, alternatives, and verified orchestration.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from dataclasses import replace as dc_replace
from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.sub_agents.result_output import answer_text
from myrm_agent_harness.agent.sub_agents.types import (
    SubagentConfig,
    SubAgentResult,
    SubAgentStatus,
    WorkspacePolicy,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

from ._orchestrator_council import run_council
from ._orchestrator_verification import (
    VerificationVerdict,
    run_with_verification,
    verify_worker_output,
)

if TYPE_CHECKING:
    from myrm_agent_harness.utils.runtime.cancellation import CancellationToken

    from .manager import SubagentManager, SubagentTask

logger = get_agent_logger(__name__)


async def run_alternatives(
    manager: SubagentManager,
    task_description: str,
    configs: list[tuple[str, SubagentConfig]],
    context: dict[str, object],
    tool_registry_getter: Callable[[], list[BaseTool]],
    cancel_token: CancellationToken | None = None,
) -> list[SubAgentResult]:
    """Spawn N subagents in parallel for the same task; return all results without auto-merging.

    Each subagent runs in an isolated workspace copy (ISOLATED_COPY) with deferred
    workspace cleanup. Outputs are compared as text in the tool response; isolated
    child workspaces are discarded after completion (not merged into the parent).

    Results are returned to the calling LLM as a tool call response containing all
    alternatives.  The LLM synthesises a comparative analysis and presents the best
    option(s) to the user.  SubagentDashboard provides real-time visibility into
    each alternative's progress during execution.

    Args:
        manager: SubagentManager instance.
        task_description: Common task description shared by all alternatives.
        configs: List of (agent_type, config) tuples — one per alternative.
            Each config may specify a different system_prompt/model to produce diverse results.
        context: Shared execution context (workspace_path is required for isolation).
        tool_registry_getter: Tool provider.
        cancel_token: Propagated to each spawned child.

    Returns:
        List of SubAgentResult in the same order as *configs*.  Merge metadata is
        stripped; deferred isolated child workspaces are removed before return.
    """
    if not configs:
        return []

    batch_id = uuid.uuid4().hex[:8]
    task_ids: list[str] = []
    early_failures: dict[str, SubAgentResult] = {}

    for idx, (agent_type, config) in enumerate(configs):
        iso_config = dc_replace(config, workspace_policy=WorkspacePolicy.ISOLATED_COPY)
        iso_context = {**context, "_defer_workspace_merge": True}

        task_id = f"alt-{batch_id}-{idx}-{agent_type}"
        task_ids.append(task_id)

        spawn_result = await manager.spawn_child(
            task_id=task_id,
            agent_type=agent_type,
            task_description=task_description,
            config=iso_config,
            context=iso_context,
            tool_registry_getter=tool_registry_getter,
            wait=False,
            cancel_token=cancel_token,
        )
        if isinstance(spawn_result, SubAgentResult) and not spawn_result.success:
            early_failures[task_id] = spawn_result

    spawned_ids = [tid for tid in task_ids if tid not in early_failures]
    if spawned_ids:
        batch = await wait_children(manager, spawned_ids, min_success_rate=0.0)
    else:
        batch = {"results": [], "failures": []}

    # Collect SubAgentResult from manager (wait_children returns to_dict() snapshots,
    # but we need the original objects for deferred workspace cleanup).
    results_map: dict[str, SubAgentResult] = dict(early_failures)
    batch_items: list[object] = []
    for key in ("results", "failures"):
        entries = batch.get(key)
        if isinstance(entries, list):
            batch_items.extend(entries)
    for item in batch_items:
        if isinstance(item, SubAgentResult):
            results_map[item.task_id] = item
        elif isinstance(item, dict):
            tid = str(item.get("task_id", ""))
            completed = manager.child_results.get(tid)
            if completed is not None:
                results_map[tid] = completed

    ordered: list[SubAgentResult] = [results_map[tid] for tid in task_ids if tid in results_map]

    success_count = sum(1 for r in ordered if r.success)
    logger.info(
        "[alternatives] Completed %d/%d alternatives (%d succeeded)",
        len(ordered),
        len(configs),
        success_count,
    )

    from myrm_agent_harness.agent.workspace_coordination.merge.batch_merge import (
        discard_deferred_isolated_workspaces,
    )

    discarded = discard_deferred_isolated_workspaces(ordered)
    if discarded:
        logger.info("[alternatives] Discarded %d deferred isolated workspace(s)", discarded)

    return ordered


async def run_chain(
    manager: SubagentManager,
    configs: list[tuple[str, SubagentConfig, str]],
    context: dict[str, object],
    tool_registry_getter: Callable[[], list[BaseTool]],
    cancel_token: CancellationToken | None = None,
) -> SubAgentResult:
    """Execute subagents in chain: A -> B -> C, each receiving previous result.

    Args:
        manager: SubagentManager instance to spawn children through.
        configs: List of (agent_type, config, task_template) tuples.
                 task_template may contain {previous} placeholder.
        context: Shared context.
        tool_registry_getter: Tool provider.
        cancel_token: Propagated to each spawned child for user-initiated cancellation.

    Returns:
        Final SubAgentResult from the last step.
    """
    previous_result = ""
    batch_id = uuid.uuid4().hex[:8]
    last_result = SubAgentResult(
        success=False,
        task_id="chain",
        agent_type="chain",
        error="Empty chain",
        completed_at=time.time(),
        status=SubAgentStatus.FAILED,
    )

    for idx, (agent_type, config, task_template) in enumerate(configs):
        if cancel_token and cancel_token.is_cancelled:
            last_result = SubAgentResult(
                success=False,
                task_id=f"chain-{batch_id}-{idx}-{agent_type}",
                agent_type=agent_type,
                error="Chain cancelled by user",
                completed_at=time.time(),
                status=SubAgentStatus.CANCELLED,
            )
            return last_result

        # Batch-scoped id keeps repeated/parallel chain delegations unique on the
        # same manager (completed business nodes persist in _children_results).
        task_id = f"chain-{batch_id}-{idx}-{agent_type}"
        task_desc = task_template.replace("{previous}", previous_result)

        spawned = await manager.spawn_child(
            task_id=task_id,
            agent_type=agent_type,
            task_description=task_desc,
            config=config,
            context=context,
            tool_registry_getter=tool_registry_getter,
            wait=True,
            cancel_token=cancel_token,
        )
        if isinstance(spawned, dict):
            last_result = SubAgentResult(
                success=bool(spawned.get("success", False)),
                task_id=task_id,
                agent_type=agent_type,
                result=str(spawned.get("result", "")),
                completed_at=time.time(),
                status=SubAgentStatus.COMPLETED,
            )
        else:
            last_result = spawned

        if not last_result.success:
            total_steps = len(configs)
            last_result.error = f"[chain step {idx + 1}/{total_steps} ({agent_type})] {last_result.error}"
            logger.warning(
                "[chain] Step %d/%d (%s) failed, aborting chain",
                idx + 1,
                total_steps,
                agent_type,
            )
            return last_result

        previous_result = answer_text(last_result.result)

    return last_result


async def wait_children(
    manager: SubagentManager,
    task_ids: list[str],
    min_success_rate: float = 0.5,
    timeout: float | None = None,
) -> dict[str, object]:
    """Wait for multiple child tasks to complete and aggregate results.

    Args:
        manager: SubagentManager whose children to wait on.
        task_ids: Task IDs to wait for.
        min_success_rate: Minimum success ratio to consider batch successful.
        timeout: Total timeout for all tasks (None = no limit).

    Returns:
        Dict with success, results, success_rate, and failures.
    """
    if not task_ids:
        return {
            "success": False,
            "results": [],
            "success_rate": 0.0,
            "failures": ["No tasks found"],
        }

    seen: set[str] = set()
    duplicates = [tid for tid in task_ids if tid in seen or seen.add(tid)]  # type: ignore[func-returns-value]
    if duplicates:
        return {
            "success": False,
            "results": [],
            "success_rate": 0.0,
            "failures": [f"Duplicate task_ids: {duplicates}"],
        }

    running_tasks: list[SubagentTask] = []
    running_ids: list[str] = []
    successes: list[dict[str, object]] = []
    failures: list[object] = []

    for task_id in task_ids:
        task = manager.children.get(task_id)
        if task is not None:
            running_tasks.append(task)
            running_ids.append(task_id)
            continue

        completed = manager.child_results.get(task_id)
        if completed is not None:
            data = completed.to_dict()
            (successes if completed.success else failures).append(data)
            continue

        failures.append({"task_id": task_id, "error": "Task not found"})

    if running_tasks:
        if timeout:
            done, _ = await asyncio.wait(running_tasks, timeout=timeout)
        else:
            done, _ = await asyncio.wait(running_tasks)

        for idx, task in enumerate(running_tasks):
            tid = running_ids[idx]
            if task in done:
                try:
                    raw = task.result()
                    if isinstance(raw, SubAgentResult):
                        data = raw.to_dict()
                        (successes if raw.success else failures).append(data)
                    else:
                        failures.append({"task_id": tid, "error": str(raw)})
                except Exception as exc:
                    failures.append({"task_id": tid, "error": f"{type(exc).__name__}: {exc}"})
            else:
                failures.append(
                    {
                        "task_id": tid,
                        "status": SubAgentStatus.TIMED_OUT.value,
                        "still_running": True,
                        "error": (
                            f"Wait timeout after {timeout}s, agent still running in background. "
                            "Use list_subagents to check progress."
                        ),
                    }
                )

    rate = len(successes) / len(task_ids) if task_ids else 0.0
    logger.info(
        f"Batch completed: {len(successes)}/{len(task_ids)} succeeded "
        f"(rate={rate:.1%}, threshold={min_success_rate:.1%})"
    )
    return {
        "success": rate >= min_success_rate,
        "results": successes,
        "success_rate": rate,
        "failures": failures,
    }


__all__ = [
    "VerificationVerdict",
    "run_alternatives",
    "run_chain",
    "run_council",
    "run_with_verification",
    "verify_worker_output",
    "wait_children",
]
