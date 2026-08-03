"""Dynamic Workflow preflight — static spawn analysis and cost estimation.

[INPUT]
- agent.base_agent::BaseAgent (POS: Parent agent with budget checker)
- agent.sub_agents.types::SubagentCatalog (POS: Subagent type resolution)
- agent.meta_tools.spawn_subagent._delegate_budget::_estimate_batch_cost (POS: Batch cost estimation)

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

if TYPE_CHECKING:
    from myrm_agent_harness.agent.base_agent import BaseAgent
    from myrm_agent_harness.agent.sub_agents.types import SubagentCatalog

logger = logging.getLogger(__name__)

_SPAWN_CALL_PATTERN = re.compile(r"myrm_tools\.spawn_subagent\s*\(")


@dataclass(frozen=True, slots=True)
class WorkflowPlanReview:
    """Preflight summary shown before PTC execution."""

    script_code: str
    spawn_count: int
    estimated_cost_usd: float | None
    remaining_budget_usd: float | None
    cost_status: str


WorkflowApprovalGate = Callable[[WorkflowPlanReview], Awaitable[bool]]


def count_spawn_calls(script_code: str) -> int:
    return len(_SPAWN_CALL_PATTERN.findall(script_code))


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
    cost_line = "Cost estimate unavailable"
    if review.estimated_cost_usd is not None:
        cost_line = f"Estimated cost: ${review.estimated_cost_usd:.2f}"
        if review.remaining_budget_usd is not None:
            cost_line += f" (remaining budget: ${review.remaining_budget_usd:.2f})"

    header = (
        f"Detected {review.spawn_count} literal spawn call(s) in the orchestration script.\n"
        f"Runtime hard cap: 50 spawns, max 5 concurrent.\n"
        f"{cost_line} (status: {review.cost_status})\n\n"
        "--- Orchestration script preview ---\n"
    )
    preview = review.script_code
    if len(preview) > 12_000:
        preview = preview[:12_000] + "\n... [truncated]"
    return header + preview


async def estimate_workflow_cost(
    parent_agent: BaseAgent,
    catalog: SubagentCatalog | None,
    spawn_count: int,
    query: str,
) -> tuple[float | None, float | None, str]:
    if spawn_count <= 0 or catalog is None:
        return None, None, "no_spawns"

    from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch import TaskRequest
    from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import _estimate_batch_cost

    objective = query[:500] if query else "Dynamic Workflow sub-agent task"
    tasks = [TaskRequest(agent_type="generalPurpose", objective=objective) for _ in range(spawn_count)]
    try:
        estimate = await _estimate_batch_cost(
            parent_agent=parent_agent,
            catalog=catalog,
            tasks=tasks,
        )
    except Exception as exc:
        logger.debug("DW preflight cost estimation failed: %s", exc)
        return None, None, "unavailable"

    if estimate.status == "unavailable":
        return None, estimate.remaining_budget_usd, estimate.reason or "unavailable"

    return estimate.estimated_cost_usd, estimate.remaining_budget_usd, estimate.cost_status or "estimated"


def resume_action(resume_value: dict[str, object] | None) -> str | None:
    if not resume_value:
        return None
    action = resume_value.get("action")
    return action if isinstance(action, str) else None
