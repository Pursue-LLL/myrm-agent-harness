"""Dynamic Workflow preflight — static spawn analysis and cost estimation.

[INPUT]
- agent.base_agent::BaseAgent (POS: Parent agent with budget checker)
- agent.sub_agents.types::SubagentCatalog (POS: Subagent type resolution)
- agent.meta_tools.spawn_subagent._delegate_budget::_estimate_batch_cost (POS: Batch cost estimation)
- agent.dynamic_workflow.tools::DEFAULT_MAX_CONCURRENT_SPAWNS (POS: Per-workflow concurrency cap)

[OUTPUT]
- WorkflowPlanReview: Preflight summary DTO for HITL card
- WorkflowApprovalGate: Callable protocol for server-injected PhaseWaiter gate
- count_spawn_calls, strip_script_markdown, format_plan_preview: Static script analysis helpers
- estimate_workflow_cost: Spawn-count-based cost estimate
- resume_action: Normalize resume_value action field

[POS]
Trust-layer preflight for Dynamic Workflow. Keeps orchestration engine lean by isolating
static script analysis and batch cost estimation from PTC execution.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.dynamic_workflow.tools import (
    DEFAULT_MAX_CONCURRENT_SPAWNS,
)

if TYPE_CHECKING:
    from myrm_agent_harness.agent.base_agent import BaseAgent
    from myrm_agent_harness.agent.sub_agents.types import SubagentCatalog

logger = logging.getLogger(__name__)

_SPAWN_CALL_PATTERN = re.compile(r"myrm_tools\.spawn_subagent\s*\(")
_LLM_QUERY_CALL_PATTERN = re.compile(r"myrm_tools\.llm_query\s*\(")
_LLM_QUERY_BATCHED_CALL_PATTERN = re.compile(r"myrm_tools\.llm_query_batched\s*\(")

# 静态预估：单次 llm_query 的 prompt/completion token 基准（无法精确解析脚本内容，
# 仅用于 HITL 审批卡片给出量级感。batched 按批次大小粗估 20 条）。
_LLM_QUERY_ESTIMATE_INPUT_TOKENS = 800
_LLM_QUERY_ESTIMATE_OUTPUT_TOKENS = 200
_LLM_QUERY_BATCHED_ASSUMED_ITEMS = 20


@dataclass(frozen=True, slots=True)
class WorkflowPlanReview:
    """Preflight summary shown before PTC execution."""

    script_code: str
    spawn_count: int
    estimated_cost_usd: float | None
    remaining_budget_usd: float | None
    cost_status: str
    # Call-site counts for llm_query (direct) and llm_query_batched (parallel batch).
    # A batched call is a single call site that fans out to many LLM sub-calls at runtime.
    llm_query_single_calls: int = 0
    llm_query_batched_calls: int = 0


WorkflowApprovalGate = Callable[[WorkflowPlanReview], Awaitable[bool]]


def count_spawn_calls(script_code: str) -> int:
    return len(_SPAWN_CALL_PATTERN.findall(script_code))


def count_llm_query_calls(script_code: str) -> tuple[int, int]:
    """Count literal llm_query and llm_query_batched call sites in the script.

    Returns (single_calls, batched_calls). A batched call is a single PTC RPC but
    fans out to multiple LLM sub-calls internally.
    """
    single = len(_LLM_QUERY_CALL_PATTERN.findall(script_code))
    batched = len(_LLM_QUERY_BATCHED_CALL_PATTERN.findall(script_code))
    return single, batched


def strip_script_markdown(script_code: str) -> str:
    cleaned = script_code
    if cleaned.startswith("```python"):
        cleaned = cleaned[9:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()


def format_plan_preview(review: WorkflowPlanReview) -> str:
    lines: list[str] = []

    if review.spawn_count > 0:
        lines.append(
            f"This workflow will run {review.spawn_count} sub-agent task(s), "
            f"with up to {DEFAULT_MAX_CONCURRENT_SPAWNS} at a time."
        )

    if review.llm_query_single_calls or review.llm_query_batched_calls:
        labels: list[str] = []
        if review.llm_query_single_calls > 0:
            labels.append(f"{review.llm_query_single_calls} direct AI call(s)")
        if review.llm_query_batched_calls > 0:
            labels.append(
                f"{review.llm_query_batched_calls} parallel batch(es) of AI calls"
            )
        lead = "It also includes " if review.spawn_count > 0 else "It includes "
        lines.append(lead + ", ".join(labels) + " for quick analysis.")

    if review.estimated_cost_usd is not None:
        cost_line = f"Estimated cost: ${review.estimated_cost_usd:.2f}"
        if review.remaining_budget_usd is not None:
            cost_line += f" (remaining budget: ${review.remaining_budget_usd:.2f})"
        cost_line += (
            ". Estimate is approximate; actual cost depends on runtime calls "
            "and token counts."
        )
    else:
        cost_line = "Cost estimate unavailable."
    lines.append(cost_line)

    header = "\n".join(lines) + "\n\n--- Workflow plan preview ---\n"
    preview = review.script_code
    if len(preview) > 12_000:
        preview = preview[:12_000] + "\n... [truncated]"
    return header + preview


def _estimate_llm_query_cost(
    parent_agent: BaseAgent,
    single_calls: int,
    batched_calls: int,
) -> tuple[float | None, str]:
    """Estimate the USD cost of llm_query call sites using the parent model's pricing.

    Static estimation: llm_query ≈ single call; llm_query_batched ≈ assumed N items
    in one batch. Returns (cost_usd, cost_status); cost may be None when the parent
    model price is unknown.
    """
    from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
        _resolve_model_name,
    )
    from myrm_agent_harness.utils.token_economics.cost_engine import (
        compute_cost_by_tokens,
    )

    model_name = _resolve_model_name(parent_agent, None)
    single_estimation = compute_cost_by_tokens(
        model=model_name,
        prompt_tokens=_LLM_QUERY_ESTIMATE_INPUT_TOKENS,
        completion_tokens=_LLM_QUERY_ESTIMATE_OUTPUT_TOKENS,
    )
    if not single_estimation.is_known:
        return None, "model_cost_unavailable"

    batched_items = batched_calls * _LLM_QUERY_BATCHED_ASSUMED_ITEMS
    batch_estimation = compute_cost_by_tokens(
        model=model_name,
        prompt_tokens=_LLM_QUERY_ESTIMATE_INPUT_TOKENS * batched_items,
        completion_tokens=_LLM_QUERY_ESTIMATE_OUTPUT_TOKENS * batched_items,
    )
    total = (single_calls * single_estimation.usd) + batch_estimation.usd
    return total, single_estimation.status.value


async def estimate_workflow_cost(
    parent_agent: BaseAgent,
    catalog: SubagentCatalog | None,
    spawn_count: int,
    query: str,
    *,
    llm_query_calls: tuple[int, int] = (0, 0),
) -> tuple[float | None, float | None, str]:
    """Estimate total workflow cost from spawn calls plus llm_query call sites.

    ``llm_query_calls`` is (single_calls, batched_calls) as returned by
    ``count_llm_query_calls``. Spawn cost dominates; llm_query cost is added when
    both are estimable, otherwise the llm_query portion is reported best-effort.
    """
    if spawn_count <= 0 and llm_query_calls == (0, 0):
        return None, None, "no_spawns"

    spawn_cost: float | None = None
    remaining_budget_usd: float | None = None
    spawn_status = "no_spawns"

    if spawn_count > 0 and catalog is not None:
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch import (
            TaskRequest,
        )
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _estimate_batch_cost,
        )

        objective = query[:500] if query else "Dynamic Workflow sub-agent task"
        tasks = [
            TaskRequest(agent_type="generalPurpose", objective=objective)
            for _ in range(spawn_count)
        ]
        try:
            estimate = await _estimate_batch_cost(
                parent_agent=parent_agent,
                catalog=catalog,
                tasks=tasks,
            )
        except Exception as exc:
            logger.debug("DW preflight cost estimation failed: %s", exc)
            spawn_status = "unavailable"
        else:
            remaining_budget_usd = estimate.remaining_budget_usd
            if estimate.status == "unavailable":
                spawn_status = estimate.reason or "unavailable"
            else:
                spawn_cost = estimate.estimated_cost_usd
                spawn_status = estimate.cost_status or "estimated"

    llm_query_cost, llm_query_status = _estimate_llm_query_cost(
        parent_agent, llm_query_calls[0], llm_query_calls[1]
    )

    if llm_query_cost is None and spawn_cost is None:
        return (
            None,
            remaining_budget_usd,
            spawn_status if spawn_status != "no_spawns" else "unavailable",
        )

    total = (spawn_cost or 0.0) + (llm_query_cost or 0.0)
    status = llm_query_status if spawn_cost is None else spawn_status
    return total, remaining_budget_usd, status


def resume_action(resume_value: dict[str, object] | None) -> str | None:
    if not resume_value:
        return None
    action = resume_value.get("action")
    return action if isinstance(action, str) else None
