"""Council and alternatives mode execution for delegate_task.

[INPUT]
- agent.sub_agents.types::SubagentCatalog (POS: Subagent type catalog with async config resolution)
- agent.sub_agents.types::SubagentConfig (POS: Frozen subagent configuration dataclass)
- agent.sub_agents.types::CouncilResult (POS: Structured multi-expert cross-review result)
- agent.sub_agents.types::SubAgentResult (POS: Single subagent execution result)
- agent.sub_agents.orchestrator::run_council (POS: Council orchestration primitive)
- agent.sub_agents.orchestrator::run_alternatives (POS: Alternatives generation primitive)
- agent.parallel.summary::inject_capacity_signal (POS: Capacity signal injection for context management)
- delegation_pause_gate::is_delegation_paused (POS: Session delegation pause check)
- _delegate_budget::_estimate_batch_cost, _BatchBudgetAdmission (POS: Pre-flight cost estimation)
- _delegate_batch::TaskRequest, _DEFAULT_COST_APPROVAL_THRESHOLD_USD (POS: Cost approval threshold)

[OUTPUT]
- execute_cognitive_mode: Execute council or alternatives delegation mode

[POS]
Cognitive delegation executor. Handles council (multi-expert cross-review with chair synthesis) and
alternatives (N parallel solutions for user comparison) modes, separate from single/batch/parallel in
_delegate_batch.py. Validates inputs, resolves expert configs, runs pre-flight cost estimation with
user approval interrupt when above threshold, and delegates to orchestrator primitives.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.parallel.summary import (
    inject_capacity_signal as _inject_capacity_signal,
)
from myrm_agent_harness.agent.sub_agents.types import (
    CouncilResult,
    SubagentCatalog,
    SubagentConfig,
    SubAgentResult,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from myrm_agent_harness.agent.base_agent import BaseAgent

logger = get_agent_logger(__name__)


async def execute_cognitive_mode(
    *,
    mode: str,
    parent_agent: BaseAgent,
    catalog: SubagentCatalog,
    objective: str | None,
    expert_agent_types: list[str] | None,
    context: dict[str, object] | None,
    context_files: list[str],
    tool_registry_getter: Callable[[], list[object]],
    readonly: bool,
    cross_review_rounds: int,
    chair_agent_type: str | None,
    cancel_token: object | None,
    session_id: str,
    allowed_types: list[str] | None,
) -> dict[str, object]:
    """Execute council or alternatives mode delegation."""
    from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegation_pause_gate import (
        is_delegation_paused,
    )

    if is_delegation_paused(session_id):
        return {
            "success": False,
            "error": "Delegation is paused for this session.",
            "session_id": session_id,
        }

    if not objective:
        return {"success": False, "error": f"objective is required for mode={mode}."}

    if not expert_agent_types or len(expert_agent_types) < 2:
        return {
            "success": False,
            "error": f"mode={mode} requires expert_agent_types with at least 2 entries.",
        }

    task = objective
    if context_files:
        task += "\n\nRelevant files/resources:\n" + "\n".join(f"- {f}" for f in context_files)
    if context:
        try:
            context_str = json.dumps(context, ensure_ascii=False, indent=2)
            task += f"\n\nAdditional Context Data:\n```json\n{context_str}\n```"
        except Exception:
            task += f"\n\nAdditional Context Data:\n{context!s}"

    expert_configs: list[tuple[str, SubagentConfig]] = []
    from myrm_agent_harness.agent.sub_agents.spawn_prep import apply_readonly_to_config

    for agent_type_id in expert_agent_types:
        if allowed_types is not None and agent_type_id not in allowed_types:
            return {
                "success": False,
                "error": f"Agent type '{agent_type_id}' not allowed.",
            }
        config = await catalog.resolve(agent_type_id)
        if not config:
            return {
                "success": False,
                "error": f"Agent type '{agent_type_id}' not found in catalog.",
            }
        config = apply_readonly_to_config(config, readonly)
        expert_configs.append((agent_type_id, config))

    parent_manager = getattr(parent_agent, "_subagent_manager", None)
    if parent_manager is None:
        return {"success": False, "error": "Parent agent has no subagent manager."}

    rejection = await _preflight_cost_check(
        parent_agent=parent_agent,
        catalog=catalog,
        expert_agent_types=expert_agent_types,
        objective=objective,
        context_files=context_files,
        context=context,
        mode=mode,
        cross_review_rounds=cross_review_rounds,
    )
    if rejection is not None:
        return rejection

    parent_ctx = getattr(parent_agent, "_last_context", None) or {}
    child_context = dict(context or {})
    for _ctx_key in ("workspace_binding", "workspaces_storage_root", "user_id", "session_id"):
        if _ctx_key in parent_ctx:
            child_context[_ctx_key] = parent_ctx[_ctx_key]

    try:
        if mode == "council":
            from myrm_agent_harness.agent.sub_agents.orchestrator import run_council

            chair_config: SubagentConfig | None = None
            if chair_agent_type:
                chair_config = await catalog.resolve(chair_agent_type)

            council_result: CouncilResult = await run_council(
                manager=parent_manager,
                task_description=task,
                expert_configs=expert_configs,
                context=child_context,
                tool_registry_getter=tool_registry_getter,
                chair_config=chair_config,
                cross_review_rounds=cross_review_rounds,
                cancel_token=cancel_token,
            )

            result_dict = council_result.to_dict()
            return _inject_capacity_signal(
                {"success": council_result.success, "mode": "council", **result_dict},
                parent_agent,
            )

        from myrm_agent_harness.agent.sub_agents.orchestrator import run_alternatives

        alt_results: list[SubAgentResult] = await run_alternatives(
            manager=parent_manager,
            task_description=task,
            configs=expert_configs,
            context=child_context,
            tool_registry_getter=tool_registry_getter,
            cancel_token=cancel_token,
        )

        return _inject_capacity_signal(
            {
                "success": any(r.success for r in alt_results),
                "mode": "alternatives",
                "alternatives": [r.to_dict() for r in alt_results],
                "alternative_count": len(alt_results),
                "successful_count": sum(1 for r in alt_results if r.success),
            },
            parent_agent,
        )

    except Exception as e:
        logger.error("Cognitive mode %s failed: %s", mode, e, exc_info=True)
        return {
            "success": False,
            "error": f"{type(e).__name__}: {e}",
            "mode": mode,
        }


async def _preflight_cost_check(
    *,
    parent_agent: BaseAgent,
    catalog: SubagentCatalog,
    expert_agent_types: list[str],
    objective: str,
    context_files: list[str],
    context: dict[str, object] | None,
    mode: str,
    cross_review_rounds: int,
) -> dict[str, object] | None:
    """Estimate cost for cognitive modes and interrupt for user approval if above threshold.

    Council mode multiplies expert count by (1 + cross_review_rounds) to account for
    independent analysis + cross-review rounds. Alternatives uses expert count directly.

    Returns None if approved or estimation unavailable; returns rejection dict otherwise.
    """
    from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch import (
        _DEFAULT_COST_APPROVAL_THRESHOLD_USD,
        TaskRequest,
    )
    from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
        _estimate_batch_cost,
    )

    if mode == "council":
        rounds = max(1, min(cross_review_rounds, 3))
        # Phase1(N independent) + Phase2(N × rounds cross-review) + Phase3(1 chair)
        effective_count = len(expert_agent_types) * (1 + rounds) + 1
    else:
        effective_count = len(expert_agent_types)

    synthetic_tasks = [
        TaskRequest(
            agent_type=expert_agent_types[i % len(expert_agent_types)],
            objective=objective,
            context_files=context_files,
            context=context,
        )
        for i in range(effective_count)
    ]

    try:
        estimate = await _estimate_batch_cost(
            parent_agent=parent_agent,
            catalog=catalog,
            tasks=synthetic_tasks,
        )
    except Exception as exc:
        logger.debug("Cognitive pre-flight cost estimation failed: %s", exc)
        return None

    if (
        estimate.status == "unavailable"
        or estimate.estimated_cost_usd is None
        or estimate.estimated_cost_usd < _DEFAULT_COST_APPROVAL_THRESHOLD_USD
    ):
        return None

    from langgraph.types import interrupt

    interrupt_payload = {
        "action_type": "batch_cost_approval",
        "task_count": effective_count,
        "estimated_cost_usd": round(estimate.estimated_cost_usd, 4),
        "remaining_budget_usd": (
            round(estimate.remaining_budget_usd, 4) if estimate.remaining_budget_usd is not None else None
        ),
        "cost_status": estimate.cost_status,
        "mode": mode,
        "expert_count": len(expert_agent_types),
    }
    decision = interrupt(interrupt_payload)

    approved = True
    if isinstance(decision, dict):
        approved = decision.get("approved", True)
    elif isinstance(decision, list) and decision:
        first = decision[0]
        approved = first.get("approved", True) if isinstance(first, dict) else bool(first)

    if not approved:
        return {
            "success": False,
            "status": "user_rejected",
            "reason": "cognitive_cost_rejected_by_user",
            "estimated_cost_usd": estimate.estimated_cost_usd,
            "mode": mode,
        }

    return None
