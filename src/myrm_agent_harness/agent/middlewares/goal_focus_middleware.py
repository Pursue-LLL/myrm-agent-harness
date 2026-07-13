"""Goal focus middleware — inject active goal objective into last HumanMessage.

[INPUT]
- agent.goals.goal_prompt_prefixes::GOAL_CONTINUATION_PREFIX, GOAL_WRAPUP_PREFIX (POS: skip-detection SSOT)
- agent.goals.types::Goal, GoalStatus (POS: ACTIVE gate + focus line fields)
- agent.middlewares._session_context::get_goal_provider (POS: per-run GoalProvider ContextVar)
- langchain.agents.middleware::ModelRequest, wrap_model_call (POS: LC middleware)

[OUTPUT]
- goal_focus_middleware: Non-persistent active-goal reminder on user-initiated turns

[POS]
Cache-safe HumanMessage injection for ACTIVE goals on user-initiated turns. Skips turns
that already carry continuation or wrap-up goal prompts.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import ModelRequest, ModelResponse, wrap_model_call
from langchain_core.messages import HumanMessage

from myrm_agent_harness.agent.goals.goal_prompt_prefixes import (
    GOAL_CONTINUATION_PREFIX,
    GOAL_WRAPUP_PREFIX,
)
from myrm_agent_harness.agent.goals.types import Goal, GoalStatus
from myrm_agent_harness.agent.middlewares._session_context import get_goal_provider

logger = logging.getLogger(__name__)

_MAX_OBJECTIVE_CHARS = 200


def _truncate_objective(objective: str) -> str:
    text = " ".join(objective.split())
    if len(text) <= _MAX_OBJECTIVE_CHARS:
        return text
    return f"{text[: _MAX_OBJECTIVE_CHARS - 1].rstrip()}…"


def _format_budget_hint(goal: Goal) -> str:
    if goal.budget is None:
        return f"tokens used: {goal.tokens_used}"
    parts: list[str] = []
    if goal.budget.max_tokens is not None:
        parts.append(f"tokens {goal.tokens_used}/{goal.budget.max_tokens}")
    elif goal.tokens_used:
        parts.append(f"tokens used: {goal.tokens_used}")
    if goal.budget.max_turns is not None:
        parts.append(f"turns {goal.turns_used}/{goal.budget.max_turns}")
    return ", ".join(parts) if parts else "no budget limits"


def _build_goal_focus_line(goal: Goal) -> str:
    objective = _truncate_objective(goal.objective)
    budget_hint = _format_budget_hint(goal)
    return (
        f"Active goal: {objective} ({budget_hint}) — "
        "advance it or call update_goal_status_tool when fully complete."
    )


def _has_goal_continuation_prompt(messages: list[object]) -> bool:
    for msg in messages:
        if not isinstance(msg, HumanMessage):
            continue
        content = msg.content
        if isinstance(content, str):
            if content.startswith(GOAL_CONTINUATION_PREFIX) or content.startswith(GOAL_WRAPUP_PREFIX):
                return True
        elif isinstance(content, list):
            joined = " ".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
            if joined.startswith(GOAL_CONTINUATION_PREFIX) or joined.startswith(GOAL_WRAPUP_PREFIX):
                return True
    return False


def _append_to_last_human_message(
    messages: list[object],
    injection_text: str,
) -> list[object]:
    new_messages = list(messages)
    last_human_idx = -1
    for i in range(len(new_messages) - 1, -1, -1):
        if isinstance(new_messages[i], HumanMessage):
            last_human_idx = i
            break

    if last_human_idx != -1:
        last_msg = new_messages[last_human_idx]
        if isinstance(last_msg.content, str):
            new_messages[last_human_idx] = HumanMessage(
                content=f"{last_msg.content}\n\n{injection_text}",
                id=last_msg.id,
            )
        elif isinstance(last_msg.content, list):
            new_messages[last_human_idx] = HumanMessage(
                content=[*last_msg.content, {"type": "text", "text": f"\n\n{injection_text}"}],
                id=last_msg.id,
            )
    else:
        new_messages.append(HumanMessage(content=injection_text))

    return new_messages


def goal_focus_middleware() -> Any:
    """Inject active goal focus into the last HumanMessage (non-persistent)."""

    @wrap_model_call(name="goal_focus_middleware")  # type: ignore[arg-type]
    async def _middleware(
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        if _has_goal_continuation_prompt(list(request.messages)):
            return await handler(request)

        goal_provider = get_goal_provider()
        if goal_provider is None:
            return await handler(request)

        context = getattr(request.runtime, "context", None) if hasattr(request, "runtime") and request.runtime else None
        if not isinstance(context, dict):
            return await handler(request)

        session_id = str(context.get("chat_id") or context.get("session_id") or "")
        if not session_id:
            return await handler(request)

        try:
            goal = await goal_provider.get_active_goal(session_id)
        except Exception as exc:
            logger.warning("goal_focus_middleware: failed to load active goal: %s", exc)
            return await handler(request)

        if goal is None or goal.status != GoalStatus.ACTIVE:
            return await handler(request)

        injection_text = _build_goal_focus_line(goal)
        new_messages = _append_to_last_human_message(list(request.messages), injection_text)
        return await handler(request.override(messages=new_messages))

    return _middleware


__all__ = [
    "goal_focus_middleware",
    "_build_goal_focus_line",
    "_has_goal_continuation_prompt",
]
