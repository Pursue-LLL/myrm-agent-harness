"""Assemble the MESSAGE_END payload emitted at the end of a turn.

The payload is a union of independent facts (usage, cost, context budget, budget alerts,
per-turn disclosure, loaded skills), each produced by a different subsystem. Keeping the
assembly here lets ``run_lifecycle`` stay about the run's lifecycle while this file owns
the event contract the frontend consumes.

[INPUT]
- agent.types::AgentRunStatistics (POS: 单轮运行统计)
- agent.middlewares.completion::attach_disclosure_to_event (POS: 每轮披露证据等级)
- agent.skill_agent.turn_loaded_skills::build_turn_loaded_skills_payload (POS: 本轮已加载技能清单)
- utils.token_economics.tracker::get_token_tracker (POS: 请求级 token 追踪器)

[OUTPUT]
- build_message_end_event(): 组装 MESSAGE_END 事件负载（usage / cost / budget / disclosure）

[POS]
MESSAGE_END contract owner. Every field is optional and omitted when the producing
subsystem has nothing to say, so a plain turn stays a two-key event.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.agent.types import CompletionStatus

if TYPE_CHECKING:
    from myrm_agent_harness.agent.types import AgentRunStatistics
    from myrm_agent_harness.utils.token_economics.tracker import TokenTracker


def _attach_usage(event: dict[str, object], stats: AgentRunStatistics) -> dict[str, object] | None:
    """Attach the turn's token usage; return the tracker used for the later fields."""
    from myrm_agent_harness.utils.token_economics.tracker import get_token_tracker

    tracker = get_token_tracker()
    try:
        if tracker is not None:
            event["token_economics"] = tracker.to_dict()
    except Exception:
        pass
    return tracker


def build_message_end_event(
    stats: AgentRunStatistics,
    message_id: str,
    *,
    tracker: TokenTracker | None = None,
    completion_status: str,
) -> dict[str, object]:
    """Return the MESSAGE_END event for a finished turn.

    ``tracker`` is an explicit reference preferred over the ContextVar lookup: async
    generators can resume in a different task than the one that initialized the tracker,
    so the ContextVar is not guaranteed to be visible here.
    """
    from myrm_agent_harness.agent.middlewares.completion import attach_disclosure_to_event

    event: dict[str, object] = {
        "type": AgentEventType.MESSAGE_END.value,
        "data": "",
        "messageId": message_id,
        "completion_status": completion_status,
    }

    # Per-turn disclosure (evidence tier + staged drafts) published by the completion guard.
    attach_disclosure_to_event(event, message_id)

    if stats.token_usage:
        usage_dict = stats.token_usage.to_dict()
        if stats.model_usage:
            usage_dict["model_usage"] = stats.model_usage
        event["usage"] = usage_dict

    resolved_tracker = tracker
    try:
        if resolved_tracker is None:
            from myrm_agent_harness.utils.token_economics.tracker import get_token_tracker

            resolved_tracker = get_token_tracker()
        if resolved_tracker is not None:
            event["token_economics"] = resolved_tracker.to_dict()
    except Exception:
        resolved_tracker = None

    if stats.cost_usd > 0:
        event["cost_usd"] = round(stats.cost_usd, 6)
        event["cost_status"] = stats.cost_status
    if stats.primary_model:
        event["model"] = stats.primary_model
    if stats.context_budget:
        event["context_budget"] = stats.context_budget.to_dict()

    if resolved_tracker is not None and resolved_tracker.budget_checker is not None:
        remaining = resolved_tracker.budget_checker.get_remaining_budget()
        budget_status = resolved_tracker.last_budget_status
        if remaining is not None and budget_status in ("warning", "exceeded"):
            event["usage_alert"] = {
                "status": budget_status,
                "today_cost": round(resolved_tracker.total_cost_usd, 6),
                "remaining": round(remaining, 6),
            }

    try:
        from myrm_agent_harness.agent.skill_agent.turn_loaded_skills import (
            build_turn_loaded_skills_payload,
        )

        turn_loaded = build_turn_loaded_skills_payload()
        if turn_loaded:
            event["turn_loaded_skills"] = turn_loaded
    except Exception:
        pass

    return event


def resolve_completion_status(stats: AgentRunStatistics) -> str:
    """Return the turn's completion status, downgraded to ``warning`` on a merge warning."""
    from myrm_agent_harness.agent.workspace_coordination.merge.merge_warning import (
        has_workspace_merge_warning,
    )

    completion_status = stats.completion_status.value
    if has_workspace_merge_warning() and completion_status == CompletionStatus.COMPLETE.value:
        return "warning"
    return completion_status
