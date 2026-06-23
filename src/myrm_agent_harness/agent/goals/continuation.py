"""Continuation guard chain for Goal engine.

[INPUT]
- .protocols::GoalProvider (POS: Goal provider protocol)
- .audit::build_continuation_prompt, build_judge_criteria, build_wrapup_prompt (POS: Prompt/criteria builders)
- .types::ContinuationDecision, GoalStatus (POS: Guard chain result)
- langchain_core.messages::HumanMessage, AIMessage (POS: Message types)
- utils.runtime.cancellation::CancellationToken (POS: Cancellation state)
- utils.runtime.steering::SteeringToken (POS: Steering state)

[OUTPUT]
- check_continuation: Evaluates the guard chain, returns ContinuationDecision.

[POS]
Core logic for determining if a goal should automatically continue to the next turn.
Evaluates budget, suppression, cancellation, steering, convergence, loop restart,
and semantic completion.
Returns a structured ContinuationDecision with verdict/reason for downstream consumers.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain_core.messages import AIMessage, HumanMessage

from .audit import build_continuation_prompt, build_judge_criteria, build_wrapup_prompt
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

_MAX_CONSECUTIVE_JUDGE_PARSE_FAILURES = 3

_WRAPUP_SENTINEL = "[Budget reached — wrap-up turn]"

_MAX_VERIFICATION_RETRIES = 3


async def _run_acceptance_verification(
    goal_provider: GoalProvider,
    goal: Goal,
) -> bool:
    """Run VerificationGatekeeper if acceptance_criteria are configured.

    Returns True if no criteria or all passed, False if any failed.
    When verification fails, increments verification_retries on the goal.
    When retries exceed the threshold, pauses the goal to prevent infinite loops.
    """
    if not goal.acceptance_criteria:
        return True

    from .verification.gatekeeper import VerificationGatekeeper

    gatekeeper = VerificationGatekeeper(goal.acceptance_criteria)
    result = await gatekeeper.verify_all(goal_provider)

    if result.passed:
        logger.info("Goal %s: acceptance criteria verification passed", goal.goal_id)
        return True

    updated_goal = await goal_provider.increment_verification_retries(goal.goal_id)
    new_retries = updated_goal.verification_retries

    if new_retries >= _MAX_VERIFICATION_RETRIES:
        logger.warning(
            "Goal %s: verification failed %d times — pausing to prevent infinite loop",
            goal.goal_id,
            new_retries,
        )
        await goal_provider.update_status(goal.goal_id, GoalStatus.PAUSED)
        return False

    logger.info(
        "Goal %s: verification failed (retry %d/%d): %s",
        goal.goal_id,
        new_retries,
        _MAX_VERIFICATION_RETRIES,
        result.reason,
    )
    return False


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


def _wrapup_already_injected(messages: list[BaseMessage]) -> bool:
    """Check if the wrap-up prompt was already injected in a previous turn."""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            content = msg.content if isinstance(msg.content, str) else ""
            return content.startswith(_WRAPUP_SENTINEL)
    return False


async def _judge_completion(
    goal_provider: GoalProvider,
    goal: Goal,
    last_response: str,
    collected_messages: list[BaseMessage] | None = None,
) -> tuple[str | None, bool]:
    """Run the semantic completion judge.

    Returns:
        (None, False)  — goal is complete (DONE).
        (str, False)   — goal is NOT complete; the string is the judge's reason.
        (str, True)    — goal is NOT complete AND judge output was unparseable.

    Fail-open: API/transport errors default to 'not complete' with parse_failed=False
    (network issues should not trigger the auto-pause circuit breaker).
    """
    if not last_response.strip():
        return "", False

    criteria = build_judge_criteria(goal)
    if goal.subgoals:
        criteria += "\n\nCRITICAL - Newly Added Subgoals (Latest subgoals take absolute precedence):\n"
        for i, sg in enumerate(goal.subgoals):
            criteria += f"{i + 1}. {sg.get('text')} (Added at: {sg.get('created_at')})\n"

    content = last_response[:_JUDGE_RESPONSE_MAX_CHARS]

    try:
        result = await goal_provider.evaluate_semantic(criteria, content, context_messages=collected_messages)
        if result.passed:
            logger.info("Judge verdict: DONE for goal %s", goal.goal_id)
            return None, False
        reason = result.reason or ""
        parse_failed = result.parse_failed
        logger.info(
            "Judge verdict: CONTINUE for goal %s (reason: %s, parse_failed: %s)",
            goal.goal_id,
            reason or "not complete",
            parse_failed,
        )
        return reason, parse_failed
    except NotImplementedError:
        logger.debug("Judge skipped: evaluate_semantic not implemented")
        return "", False
    except Exception:
        logger.warning(
            "Judge error for goal %s — defaulting to continue (fail-open)",
            goal.goal_id,
            exc_info=True,
        )
        return "", False


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
        goal.goal_id,
        goal.status.value,
        goal.turns_used,
    )

    # Track no-progress streak for convergence detection
    if not tools_called_this_turn:
        await goal_provider.suppress_continuation(session_id)
    goal = await goal_provider.record_progress(goal.goal_id, made_progress=tools_called_this_turn)

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
        if _wrapup_already_injected(collected_messages):
            logger.warning("Goal %s stopped: budget limited (wrap-up complete)", goal.goal_id)
            return _make_decision("budget", "Budget exhausted", goal)

        # Grant one wrap-up turn: inject a summary prompt so the LLM
        # can produce a graceful conclusion instead of stopping mid-sentence.
        wrapup_text = build_wrapup_prompt(goal)
        collected_messages.append(HumanMessage(content=wrapup_text, name="developer"))
        logger.info("Goal %s: injecting wrap-up prompt for graceful budget conclusion", goal.goal_id)
        return _make_decision("continue", "Budget exhausted — wrap-up turn granted", goal, message=wrapup_text)

    # 6. Convergence detection + suppression (zero tool calls)
    is_suppressed = await goal_provider.is_continuation_suppressed(session_id)

    if is_suppressed:
        convergence_window = goal.budget.convergence_window if goal.budget else None

        # 6a. Convergence reached: no progress for K consecutive turns → COMPLETE
        if convergence_window and goal.no_progress_streak >= convergence_window:
            logger.info(
                "Goal %s completed by convergence (streak=%d, window=%d)",
                goal.goal_id,
                goal.no_progress_streak,
                convergence_window,
            )
            await goal_provider.update_status(goal.goal_id, GoalStatus.COMPLETE)
            await goal_provider.reset_suppression(session_id)
            return _make_decision(
                "convergence",
                f"No new progress for {goal.no_progress_streak} consecutive turns — convergence reached",
                goal,
            )

        # 6b. Loop-on-pause: restart with fresh context instead of staying PAUSED
        loop_on_pause = goal.budget.loop_on_pause if goal.budget else False
        max_restarts = goal.budget.max_loop_restarts if goal.budget else 10
        if loop_on_pause and goal.loop_restarts < max_restarts:
            goal = await goal_provider.record_loop_restart(goal.goal_id)
            logger.info(
                "Goal %s: loop restart %d/%d (no tool calls, restarting with fresh context)",
                goal.goal_id,
                goal.loop_restarts,
                max_restarts,
            )
            await goal_provider.reset_suppression(session_id)
            return _make_decision(
                "loop_restart",
                f"Loop restart {goal.loop_restarts}/{max_restarts} — restarting with fresh context",
                goal,
            )

        # 6c. Standard suppression: pause the goal
        logger.warning("Goal %s stopped: suppressed (zero progress)", goal.goal_id)
        await goal_provider.update_status(goal.goal_id, GoalStatus.PAUSED)
        await goal_provider.reset_suppression(session_id)
        return _make_decision("suppressed", "No tool calls — paused to prevent spinning", goal)

    # 7. Semantic completion judge (skip first N turns)
    last_judge_reason: str | None = None
    if goal.turns_used >= _JUDGE_SKIP_INITIAL_TURNS and tools_called_this_turn:
        last_response = _extract_last_ai_response(collected_messages)
        judge_reason, parse_failed = await _judge_completion(goal_provider, goal, last_response, collected_messages)
        if judge_reason is None:
            verification_passed = await _run_acceptance_verification(goal_provider, goal)
            if verification_passed:
                logger.info("Goal %s completed by semantic judge (verification passed)", goal.goal_id)
                await goal_provider.update_status(goal.goal_id, GoalStatus.COMPLETE)
                return _make_decision("done", "Semantic judge determined goal is complete", goal)
            # Verification failed — check if retries exhausted (goal already PAUSED inside helper)
            refreshed = await goal_provider.get_goal(goal.goal_id)
            if refreshed and refreshed.status == GoalStatus.PAUSED:
                return _make_decision(
                    "suppressed",
                    f"Acceptance criteria verification failed {refreshed.verification_retries} times — paused",
                    refreshed,
                )

        # Track consecutive judge parse failures (circuit breaker)
        if parse_failed:
            goal = await goal_provider.record_judge_parse_result(goal.goal_id, parse_failed=True)
            if goal.consecutive_judge_parse_failures >= _MAX_CONSECUTIVE_JUDGE_PARSE_FAILURES:
                logger.warning(
                    "Goal %s auto-paused: judge returned unparseable output %d turns in a row",
                    goal.goal_id,
                    goal.consecutive_judge_parse_failures,
                )
                await goal_provider.update_status(goal.goal_id, GoalStatus.PAUSED)
                return _make_decision(
                    "suppressed",
                    f"Judge model returned unparseable output {goal.consecutive_judge_parse_failures} "
                    "turns in a row — paused to prevent token waste",
                    goal,
                )
            # Don't inject garbage reason into continuation prompt
            last_judge_reason = None
        else:
            if goal.consecutive_judge_parse_failures > 0:
                goal = await goal_provider.record_judge_parse_result(goal.goal_id, parse_failed=False)
            last_judge_reason = judge_reason

    # Refresh Goal-scoped protected_paths ContextVar so InvariantValidator
    # blocks writes to protected files during this turn.
    from myrm_agent_harness.agent.middlewares._session_context import (
        set_protected_paths,
    )

    set_protected_paths(tuple(goal.protected_paths))

    # All guards passed — inject continuation prompt
    prompt_text = build_continuation_prompt(goal, last_judge_reason=last_judge_reason)
    msg = HumanMessage(content=prompt_text, name="developer")
    collected_messages.append(msg)

    logger.info(
        "Goal %s continuing: turn=%d, tokens=%d",
        goal.goal_id,
        goal.turns_used,
        goal.tokens_used,
    )

    # Reset suppression for the new turn
    await goal_provider.reset_suppression(session_id)

    return _make_decision("continue", "All guards passed", goal, message=prompt_text)
