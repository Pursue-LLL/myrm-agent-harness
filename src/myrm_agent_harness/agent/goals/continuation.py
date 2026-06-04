"""Continuation guard chain for Goal engine.

[INPUT]
- .protocol::GoalProvider (POS: Goal provider protocol)
- .audit::build_continuation_prompt, build_judge_criteria (POS: Prompt/criteria builders)
- .types::ContinuationDecision, GoalStatus (POS: Guard chain result)
- langchain_core.messages::HumanMessage, AIMessage (POS: Message types)
- utils.runtime.cancellation::CancellationToken (POS: Cancellation state)
- utils.runtime.steering::SteeringToken (POS: Steering state)

[OUTPUT]
- check_continuation: Evaluates the 7-step guard chain, returns ContinuationDecision.

[POS]
Core logic for determining if a goal should automatically continue to the next turn.
Evaluates budget, suppression, cancellation, steering, and semantic completion.
Returns a structured ContinuationDecision with verdict/reason for downstream consumers.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain_core.messages import AIMessage, HumanMessage

from .audit import build_continuation_prompt, build_judge_criteria
from .types import ContinuationDecision, GoalStatus

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage

    from myrm_agent_harness.utils.runtime.cancellation import CancellationToken
    from myrm_agent_harness.utils.runtime.steering import SteeringToken

    from .protocols import GoalProvider
    from .types import Goal

logger = logging.getLogger(__name__)

_JUDGE_SKIP_INITIAL_TURNS = 2

_JUDGE_RESPONSE_MAX_CHARS = 4000


def _extract_last_ai_response(messages: list[BaseMessage]) -> str:
    """Extract the last AI response text from collected messages."""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            content = msg.content
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                # Extract text blocks, skip thinking blocks
                parts = []
                for block in content:
                    if isinstance(block, str):
                        parts.append(block)
                    elif isinstance(block, dict) and block.get("type") != "thinking":
                        text = block.get("text", "")
                        if text:
                            parts.append(str(text))
                return "\n".join(parts)
    return ""


async def _judge_completion(
    goal_provider: GoalProvider,
    goal: Goal,
    last_response: str,
    collected_messages: list[BaseMessage] | None = None,
) -> bool:
    """Run the semantic completion judge. Returns True if the goal is complete.

    Fail-open: any error defaults to 'not complete' (continue working).
    """
    if not last_response.strip():
        return False

    criteria = build_judge_criteria(goal)
    if goal.subgoals:
        criteria += "\n\nCRITICAL - Newly Added Subgoals (Latest subgoals take absolute precedence):\n"
        for i, sg in enumerate(goal.subgoals):
            criteria += f"{i+1}. {sg.get('text')} (Added at: {sg.get('created_at')})\n"

    # Truncate response to avoid sending too much to the judge
    content = last_response[:_JUDGE_RESPONSE_MAX_CHARS]

    try:
        result = await goal_provider.evaluate_semantic(criteria, content, context_messages=collected_messages)
        if result.passed:
            logger.info(
                "Judge verdict: DONE for goal %s", goal.goal_id
            )
            return True
        logger.info(
            "Judge verdict: CONTINUE for goal %s (reason: %s)",
            goal.goal_id,
            result.reason or "not complete",
        )
        return False
    except NotImplementedError:
        # Server layer hasn't implemented evaluate_semantic — skip judge
        logger.debug("Judge skipped: evaluate_semantic not implemented")
        return False
    except Exception:
        # Fail-open: judge error → continue working
        logger.warning(
            "Judge error for goal %s — defaulting to continue (fail-open)",
            goal.goal_id,
            exc_info=True,
        )
        return False


def _make_decision(
    verdict: str,
    reason: str,
    goal: Goal | None = None,
    message: str = "",
) -> ContinuationDecision:
    """Build a ContinuationDecision with optional goal metrics."""
    return ContinuationDecision(
        should_continue=(verdict == "continue"),
        verdict=verdict,  # type: ignore[arg-type]
        reason=reason,
        turns_used=goal.turns_used if goal else None,
        max_turns=goal.budget.max_turns if goal and goal.budget else None,
        message=message,
    )


async def check_continuation(
    goal_provider: GoalProvider | None,
    session_id: str,
    cancel_token: CancellationToken | None,
    steering_token: SteeringToken | None,
    collected_messages: list[BaseMessage],
    tools_called_this_turn: bool,
    net_tokens_this_turn: int,
    time_this_turn_seconds: int,
) -> ContinuationDecision:
    """Evaluate the 7-step guard chain for goal continuation.

    Returns a ContinuationDecision with structured verdict and reason.
    When continuing, injects the continuation prompt into collected_messages.
    """
    # 1. Goal provider exists?
    if not goal_provider:
        return _make_decision("no_goal", "No goal provider configured")

    # 2. Active goal exists?
    goal = await goal_provider.get_active_goal(session_id)
    if not goal:
        return _make_decision("no_goal", "No active goal for session")

    # Record usage for this turn (including turn count)
    await goal_provider.account_usage(
        goal.goal_id,
        token_delta=max(0, net_tokens_this_turn),
        cost_delta=0.0,
        time_delta_seconds=max(0, time_this_turn_seconds),
        turn_delta=1,
    )

    # Refresh goal state after accounting
    goal = await goal_provider.get_goal(goal.goal_id)
    if not goal:
        return _make_decision("no_goal", "Goal disappeared after accounting")

    logger.info(
        "Goal %s: status=%s, turn=%d after accounting",
        goal.goal_id, goal.status.value, goal.turns_used,
    )

    # Handle suppression trigger (zero tool calls -> suppress next turn)
    if not tools_called_this_turn:
        await goal_provider.suppress_continuation(session_id)

    # 3. Cancelled?
    if cancel_token and cancel_token.is_cancelled:
        logger.info("Goal %s stopped: cancelled by user", goal.goal_id)
        await goal_provider.update_status(goal.goal_id, GoalStatus.PAUSED)
        return _make_decision("cancelled", "Cancelled by user", goal)

    # 4. Pending steering messages?
    if steering_token and steering_token.has_pending:
        logger.info("Goal %s stopped: pending steering messages", goal.goal_id)
        return _make_decision("steering", "Pending steering messages", goal)

    # 5. Budget exhausted? (account_usage already transitions to BUDGET_LIMITED)
    if goal.status == GoalStatus.BUDGET_LIMITED:
        logger.warning("Goal %s stopped: budget limited", goal.goal_id)
        return _make_decision("budget", "Budget exhausted", goal)

    # 6. Continuation suppressed (zero tool calls)?
    is_suppressed = await goal_provider.is_continuation_suppressed(session_id)

    if is_suppressed:
        logger.warning("Goal %s stopped: suppressed (zero progress)", goal.goal_id)
        await goal_provider.update_status(goal.goal_id, GoalStatus.PAUSED)
        await goal_provider.reset_suppression(session_id)
        return _make_decision("suppressed", "No tool calls — paused to prevent spinning", goal)

    # 7. Semantic completion judge (skip first N turns)
    if goal.turns_used >= _JUDGE_SKIP_INITIAL_TURNS and tools_called_this_turn:
        last_response = _extract_last_ai_response(collected_messages)
        is_complete = await _judge_completion(goal_provider, goal, last_response, collected_messages)
        if is_complete:
            logger.info("Goal %s completed by semantic judge", goal.goal_id)
            await goal_provider.update_status(goal.goal_id, GoalStatus.COMPLETE)
            return _make_decision("done", "Semantic judge determined goal is complete", goal)

    # All guards passed — inject continuation prompt
    prompt_text = build_continuation_prompt(goal)
    msg = HumanMessage(content=prompt_text, name="developer")
    collected_messages.append(msg)

    logger.info(
        "Goal %s continuing: turn=%d, tokens=%d",
        goal.goal_id, goal.turns_used, goal.tokens_used,
    )

    # Reset suppression for the new turn
    await goal_provider.reset_suppression(session_id)

    return _make_decision("continue", "All guards passed", goal, message=prompt_text)
