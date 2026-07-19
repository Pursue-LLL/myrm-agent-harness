"""Batch and parallel delegation tool factories.

[INPUT]
- _delegate_budget::_BatchBudgetAdmission, _admit_race_budget, _estimate_batch_cost (POS: Budget admission and cost estimation)
- sub_agents.types::SubagentCatalog, DelegateRole
- parallel.runner::run_parallel_task_requests (POS: Parallel task execution engine)

[OUTPUT]
- TaskRequest: Pydantic model for a single delegation task
- BatchDelegateInput: Pydantic model for batch delegation input schema
- execute_parallel_delegation: Swarm Fission interrupt path (yield-resume)
- execute_batch_delegation: Budget-aware concurrent batch delegation core

[POS]
Batch and parallel delegation execution engines invoked by delegate_task_tool modes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from langchain.tools import tool
from pydantic import BaseModel, Field

from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
    _admit_race_budget,
    _BatchBudgetAdmission,
    _estimate_batch_cost,
)
from myrm_agent_harness.agent.sub_agents.types import (
    DelegateRole,
    SubagentCatalog,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.agent.base_agent import BaseAgent

_DELEGATION_PAUSED_ERROR = (
    "Delegation is paused for this session. Resume delegation from the subagent dashboard before spawning new workers."
)

logger = get_agent_logger(__name__)

_DEFAULT_MAX_BATCH_TASKS = 5
_DEFAULT_COST_APPROVAL_THRESHOLD_USD = 0.50


class TaskRequest(BaseModel):
    agent_type: str = Field(description="Type of subagent")
    objective: str = Field(description="Core objective for the subagent")
    context_files: list[str] = Field(default_factory=list, description="Relevant file paths")
    context: dict[str, object] | None = Field(default=None, description="Optional context data")
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
    verifier_prompt: str | None = Field(
        default=None,
        description="Optional. If provided, enables adversarial verification. The verifier will use this prompt to critique the result and force a retry if it fails.",
    )
    verifier_agent_type: str | None = Field(
        default=None,
        description="Optional. The agent type to use for the verifier. If omitted, defaults to the same agent type as the worker.",
    )
    max_verification_rounds: int = Field(
        default=2,
        description="Maximum number of retry rounds if the verifier rejects the output.",
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
    tournament: bool = Field(
        default=False,
        description=(
            "Tournament Mode: Run tasks in parallel, then use an LLM Judge to evaluate all successful "
            "results via pairwise comparison and return only the best one. Useful for subjective/creative tasks."
        ),
    )
    judge_criteria: str | None = Field(
        default=None,
        description="Criteria for the Judge Agent to evaluate the results in tournament mode (e.g., 'Best performance', 'Cleanest code').",
    )
    max_concurrent: int | None = Field(
        default=None,
        description=(
            "Max parallel workers. Default: 3 for race mode, 1 for non-race. "
            "Set higher (e.g. 3-5) when tasks are independent."
        ),
    )


def _session_id_from_agent(parent_agent: BaseAgent) -> str:
    parent_ctx = getattr(parent_agent, "_last_context", None) or {}
    if isinstance(parent_ctx, dict):
        return str(parent_ctx.get("session_id", "") or "")
    return ""


def _delegation_paused_response(parent_agent: BaseAgent) -> dict[str, object]:
    return {
        "success": False,
        "error": _DELEGATION_PAUSED_ERROR,
        "session_id": _session_id_from_agent(parent_agent),
    }


def execute_parallel_delegation(
    parent_agent: BaseAgent,
    tasks: list[TaskRequest],
) -> dict[str, object]:
    """Swarm Fission: yield-resume parallel Map-Reduce via graph interrupt."""
    from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegation_pause_gate import (
        is_delegation_paused,
    )

    if is_delegation_paused(_session_id_from_agent(parent_agent)):
        return _delegation_paused_response(parent_agent)

    if not tasks:
        return {"success": False, "error": "No tasks provided."}

    from langgraph.types import interrupt

    interrupt_payload = {
        "action_type": "swarm_fission",
        "tasks": [t.model_dump() for t in tasks],
    }

    decisions = interrupt(interrupt_payload)
    return {"success": True, "results": decisions}


async def execute_batch_delegation(
    *,
    parent_agent: BaseAgent,
    delegate_tool: BaseTool,
    catalog: SubagentCatalog,
    tasks: list[TaskRequest],
    wait: bool = True,
    race: bool = False,
    tournament: bool = False,
    judge_criteria: str | None = None,
    max_concurrent: int | None = None,
    parent_type: str | None = None,
) -> dict[str, object]:
    """Budget-aware concurrent batch delegation (mode=batch)."""
    from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegation_pause_gate import (
        is_delegation_paused,
    )

    if is_delegation_paused(_session_id_from_agent(parent_agent)):
        return _delegation_paused_response(parent_agent)

    if not tasks:
        return {"success": False, "error": "No tasks provided."}

    if tournament:
        wait = True
        race = False
        for task in tasks:
            task.objective = (
                "【TOURNAMENT MODE ACTIVE】\n"
                "You are competing against other agents. Your output will be judged.\n"
                "CRITICAL: You MUST NOT perform any irreversible external actions (e.g., sending emails, calling external webhooks, making payments). "
                "Your execution is speculative and your sandbox may be discarded if you lose the tournament. "
                "Confine all your work to the local sandbox files.\n\n"
                f"Original Objective:\n{task.objective}"
            )

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
                f"Too many batch delegation tasks: {len(tasks)}/{max_batch}. Split the work into smaller batches."
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

    if len(tasks) >= 2:
        cost_estimate = budget_admission
        if cost_estimate is None:
            try:
                cost_estimate = await _estimate_batch_cost(
                    parent_agent=parent_agent,
                    catalog=catalog,
                    tasks=tasks,
                )
            except Exception as e:
                logger.debug("Pre-flight cost estimation failed: %s", e)

        if (
            cost_estimate is not None
            and cost_estimate.status != "unavailable"
            and cost_estimate.estimated_cost_usd is not None
            and cost_estimate.estimated_cost_usd >= _DEFAULT_COST_APPROVAL_THRESHOLD_USD
        ):
            from langgraph.types import interrupt

            task_summaries = [
                {"agent_type": t.agent_type, "objective": t.objective[:200]}
                for t in tasks
            ]
            interrupt_payload = {
                "action_type": "batch_cost_approval",
                "task_count": len(tasks),
                "estimated_cost_usd": round(cost_estimate.estimated_cost_usd, 4),
                "remaining_budget_usd": (
                    round(cost_estimate.remaining_budget_usd, 4)
                    if cost_estimate.remaining_budget_usd is not None
                    else None
                ),
                "cost_status": cost_estimate.cost_status,
                "race": race,
                "tournament": tournament,
                "tasks": task_summaries,
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
                    "reason": "batch_cost_rejected_by_user",
                    "estimated_cost_usd": cost_estimate.estimated_cost_usd,
                }

    from myrm_agent_harness.agent.parallel.runner import run_parallel_task_requests

    payload = await run_parallel_task_requests(
        parent_agent=parent_agent,
        delegate_tool=delegate_tool,
        tasks=tasks,
        wait=wait,
        race=race,
        skip_merge=tournament,
        max_concurrent=max_concurrent,
        budget_admission=budget_admission,
    )

    if tournament and payload.get("success") and "results" in payload:
        results = payload["results"]
        if isinstance(results, list):
            payload = await _run_tournament_bracket(parent_agent, results, judge_criteria)

    return payload


async def _run_tournament_bracket(
    parent_agent: BaseAgent,
    results: list[dict[str, object]],
    judge_criteria: str | None,
) -> dict[str, object]:
    """Run a pairwise PK tournament to select the best result."""
    candidates = [r for r in results if isinstance(r, dict) and r.get("success")]
    if not candidates:
        return {"success": False, "error": "Tournament failed: No successful tasks to judge."}

    if len(candidates) == 1:
        winner = candidates[0]
    else:
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = getattr(parent_agent, "llm", None)
        if not llm:
            logger.warning("Parent agent has no LLM attribute. Falling back to first successful result for tournament.")
            winner = candidates[0]
        else:
            current_round = candidates
            while len(current_round) > 1:
                next_round = []
                for i in range(0, len(current_round), 2):
                    if i + 1 >= len(current_round):
                        next_round.append(current_round[i])
                        break

                    cand_a = current_round[i]
                    cand_b = current_round[i + 1]

                    res_a_str = str(cand_a.get("result", cand_a))[:20000]
                    res_b_str = str(cand_b.get("result", cand_b))[:20000]

                    sys_prompt = "You are an expert Judge Agent. Your task is to evaluate two candidate results based on the provided criteria and select the better one."
                    human_prompt = (
                        f"Criteria: {judge_criteria or 'Select the overall best quality and most complete result.'}\n\n"
                    )
                    human_prompt += f"--- Candidate A ---\n{res_a_str}\n\n"
                    human_prompt += f"--- Candidate B ---\n{res_b_str}\n\n"
                    human_prompt += "Which candidate is better? You MUST reply with exactly 'A' or 'B' on the first line, followed by your reasoning on subsequent lines."

                    try:
                        response = await llm.ainvoke(
                            [SystemMessage(content=sys_prompt), HumanMessage(content=human_prompt)]
                        )
                        content = str(response.content).strip().upper()
                        if content.startswith("A"):
                            next_round.append(cand_a)
                        elif content.startswith("B"):
                            next_round.append(cand_b)
                        else:
                            next_round.append(cand_a)
                    except Exception as e:
                        logger.error("Error during tournament judging: %s", e)
                        next_round.append(cand_a)

                current_round = next_round
            winner = current_round[0]

    # Merge the winner's workspace if it has one
    from myrm_agent_harness.agent.workspace_coordination.batch_merge import (
        merge_batch_workspace_sync_backs,
    )

    merge_info = await merge_batch_workspace_sync_backs([winner])

    return {"success": True, "status": "completed", "tournament_winner": True, "result": winner, **merge_info}
