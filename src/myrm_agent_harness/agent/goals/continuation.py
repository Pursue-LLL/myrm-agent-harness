"""Continuation guard chain for Goal engine.

[INPUT]
- .protocols::GoalProvider (POS: Goal provider protocol)
- .audit::build_continuation_prompt, build_judge_criteria, build_wrapup_prompt (POS: Prompt/criteria builders)
- .continuation_checkpoint::check_todo_checkpoint (POS: Per-todo checkpoint detection)
- .continuation_drift::check_goal_drift (POS: Goal drift detection for continuation guard chain)
- .invariant_snapshot::ProtectedFileViolation, verify_protected_integrity (POS: Post-hoc tamper detection)
- .types::ContinuationDecision, GoalStatus (POS: Guard chain result)
- langchain_core.messages::HumanMessage, AIMessage (POS: Message types)
- utils.runtime.cancellation::CancellationToken (POS: Cancellation state)
- utils.runtime.steering::SteeringToken (POS: Steering state)
- middlewares.tool_interceptor_middleware::get_loop_guard (POS: LoopGuard accessor)

[OUTPUT]
- check_continuation: Evaluates the guard chain, returns ContinuationDecision.

[POS]
Core logic for determining if a goal should automatically continue to the next turn.
Evaluates budget, suppression, cancellation, steering, convergence, loop restart,
goal drift detection, sandbox boundary HITL, per-todo checkpoint, semantic completion,
and protected file integrity (InvariantSnapshot tamper detection).
Returns a structured ContinuationDecision with verdict/reason for downstream consumers.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from langchain_core.messages import AIMessage, HumanMessage

from .audit import build_continuation_prompt, build_judge_criteria, build_wrapup_prompt
from .finalizer import finalize_goal_complete, resolve_deferred_tool_completion
from .goal_prompt_prefixes import GOAL_WRAPUP_PREFIX
from .invariant_snapshot import ProtectedFileViolation, verify_protected_integrity
from .types import ContinuationDecision, Goal, GoalStatus

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage

    from myrm_agent_harness.utils.runtime.cancellation import CancellationToken
    from myrm_agent_harness.utils.runtime.steering import SteeringToken

    from .protocols import GoalProvider

logger = logging.getLogger(__name__)

_JUDGE_SKIP_INITIAL_TURNS = 2

_JUDGE_RESPONSE_MAX_CHARS = 4000

_MAX_CONSECUTIVE_JUDGE_PARSE_FAILURES = 3

_WRAPUP_SENTINEL = GOAL_WRAPUP_PREFIX

_MAX_VERIFICATION_RETRIES = 3

_WAIT_TIMEOUT_PAUSE_REASON = "Wait timeout exceeded — goal paused"

from .continuation_checkpoint import check_todo_checkpoint as _check_todo_checkpoint
from .continuation_drift import (
    _DRIFT_CHECK_INTERVAL,
    check_goal_drift as _check_goal_drift,
)


def _is_wait_expired(goal: Goal) -> bool:
    started_raw = goal.metadata.get("wait_started_at")
    max_seconds_raw = goal.metadata.get("wait_max_seconds")
    if not isinstance(started_raw, str) or not isinstance(max_seconds_raw, int):
        return False
    try:
        started = datetime.fromisoformat(started_raw)
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        elapsed = (datetime.now(UTC) - started).total_seconds()
        return elapsed >= max_seconds_raw
    except (TypeError, ValueError):
        return False


async def _run_acceptance_verification(
    goal_provider: GoalProvider,
    goal: Goal,
) -> bool:
    """Run VerificationGatekeeper if acceptance_criteria are configured.

    Returns True if no criteria or all passed, False if any failed.
    Persists per-criterion results via record_acceptance_results.
    When verification fails, increments verification_retries on the goal.
    When retries exceed the threshold, pauses the goal to prevent infinite loops.
    """
    if not goal.acceptance_criteria:
        return True

    from .verification.gatekeeper import VerificationGatekeeper

    try:
        gatekeeper = VerificationGatekeeper(goal.acceptance_criteria)
        result = await gatekeeper.verify_all(goal_provider)
    except Exception:
        logger.exception("Goal %s: acceptance criteria verification crashed", goal.goal_id)
        updated = await goal_provider.increment_verification_retries(goal.goal_id)
        if updated.verification_retries >= _MAX_VERIFICATION_RETRIES:
            logger.warning(
                "Goal %s: verification crashed %d times — pausing to prevent infinite loop",
                goal.goal_id,
                updated.verification_retries,
            )
            await goal_provider.update_status(goal.goal_id, GoalStatus.PAUSED)
        return False

    await goal_provider.record_acceptance_results(goal.goal_id, result.to_dicts())

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
        "Goal %s: verification failed (retry %d/%d, %d/%d passed)",
        goal.goal_id,
        new_retries,
        _MAX_VERIFICATION_RETRIES,
        len(result.per_criterion) - result.failed_count,
        len(result.per_criterion),
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


def _check_protected_integrity(goal_id: str) -> list[ProtectedFileViolation]:
    """Verify protected files were not tampered with via bash bypass."""
    return verify_protected_integrity(goal_id)


def _make_tamper_decision(goal: Goal, violations: list[ProtectedFileViolation]) -> ContinuationDecision:
    """Build a 'continue' decision with tamper violation details for the agent to fix."""
    detail = ", ".join(f"{v.path} ({v.kind})" for v in violations)
    msg = (
        f"BLOCKED: {len(violations)} protected file(s) were tampered with during this Goal.\n"
        f"Violations: {detail}\n"
        f"You MUST restore these files before the Goal can be marked complete."
    )
    return ContinuationDecision(
        should_continue=True,
        verdict="continue",  # type: ignore[arg-type]
        reason=f"Protected file tamper detected: {detail}",
        turns_used=goal.turns_used,
        max_turns=goal.budget.max_turns if goal.budget else None,
        message=msg,
    )


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


async def _maybe_auto_enter_wait_for_background_bash(
    goal_provider: GoalProvider,
    goal: Goal,
) -> ContinuationDecision | None:
    """Park the goal when a whitelisted background bash job was spawned this turn."""
    if not hasattr(goal_provider, "enter_wait"):
        return None

    from myrm_agent_harness.agent.middlewares.tool_interceptor_middleware import get_loop_guard

    from .wait_background_bash import (
        WAIT_ON_BACKGROUND_JOB_ID_KEY,
        find_latest_background_spawn_in_window,
    )

    spawn = find_latest_background_spawn_in_window(list(get_loop_guard()._window))
    if spawn is None:
        return None

    existing_job_id = goal.metadata.get(WAIT_ON_BACKGROUND_JOB_ID_KEY)
    if existing_job_id is not None and str(existing_job_id) == spawn.job_id:
        return None

    reason = f"Waiting for background job {spawn.job_id}"
    await goal_provider.enter_wait(goal.goal_id, reason=reason)
    await goal_provider.update_metadata(
        goal.goal_id,
        {WAIT_ON_BACKGROUND_JOB_ID_KEY: spawn.job_id},
    )
    refreshed = await goal_provider.get_goal(goal.goal_id)
    target = refreshed or goal
    logger.info(
        "Goal %s auto-entered WAIT for background job_id=%s pid=%s",
        goal.goal_id,
        spawn.job_id,
        spawn.pid,
    )
    return _make_decision("wait", reason, target)


async def check_continuation(
    goal_provider: GoalProvider | None,
    session_id: str,
    cancel_token: CancellationToken | None,
    steering_token: SteeringToken | None,
    collected_messages: list[BaseMessage],
    tools_called_this_turn: bool,
    net_tokens_this_turn: int,
    cost_this_turn: float,
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
        latest = await goal_provider.get_latest_goal(session_id)
        if latest and latest.status == GoalStatus.WAIT:
            if _is_wait_expired(latest):
                await goal_provider.update_status(latest.goal_id, GoalStatus.PAUSED)
                await goal_provider.update_metadata(
                    latest.goal_id,
                    {"pause_reason": _WAIT_TIMEOUT_PAUSE_REASON},
                )
                return _make_decision(
                    "suppressed",
                    _WAIT_TIMEOUT_PAUSE_REASON,
                    latest,
                )
            wait_reason = str(latest.metadata.get("wait_reason") or "Waiting for external process")
            return _make_decision("wait", wait_reason, latest)

        deferred = await resolve_deferred_tool_completion(goal_provider, session_id)
        if deferred is not None:
            return deferred

        return _make_decision("no_goal", "No active goal for session")

    await goal_provider.account_usage(
        goal.goal_id,
        token_delta=max(0, net_tokens_this_turn),
        cost_delta=max(0.0, cost_this_turn),
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

    if goal.status == GoalStatus.ACTIVE and tools_called_this_turn:
        auto_wait = await _maybe_auto_enter_wait_for_background_bash(
            goal_provider,
            goal,
        )
        if auto_wait is not None:
            return auto_wait

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
            violations = _check_protected_integrity(goal.goal_id)
            if violations:
                logger.warning(
                    "Goal %s convergence blocked: %d protected file violation(s)",
                    goal.goal_id,
                    len(violations),
                )
                await goal_provider.reset_suppression(session_id)
                return _make_tamper_decision(goal, violations)

            logger.info(
                "Goal %s completed by convergence (streak=%d, window=%d)",
                goal.goal_id,
                goal.no_progress_streak,
                convergence_window,
            )
            await finalize_goal_complete(goal_provider, goal, source="convergence")
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

    # 6.5a Sandbox boundary escalation: PAUSE goal if LoopGuard flagged permission probing
    from myrm_agent_harness.agent.middlewares.tool_interceptor_middleware import get_loop_guard as _get_lg

    _lg = _get_lg()
    if _lg.sandbox_boundary_triggered:
        logger.warning("Goal %s paused: sandbox boundary violation detected", goal.goal_id)
        await goal_provider.update_status(goal.goal_id, GoalStatus.PAUSED)
        await goal_provider.update_metadata(
            goal.goal_id,
            {"pause_reason": "Sandbox boundary violation — repeated permission denied"},
        )
        return _make_decision(
            "drift_pause",
            "Sandbox boundary violation — goal paused for human review",
            goal,
        )

    # 6.5b Goal drift detection (skip first few turns; only when tools were called)
    if goal.turns_used >= _DRIFT_CHECK_INTERVAL and tools_called_this_turn:
        drift_decision = await _check_goal_drift(goal_provider, goal, collected_messages)
        if drift_decision is not None:
            return drift_decision

    # 6.5c Per-todo checkpoint: PAUSE when new todos completed (opt-in)
    if tools_called_this_turn:
        checkpoint_decision = await _check_todo_checkpoint(goal_provider, goal)
        if checkpoint_decision is not None:
            return checkpoint_decision

    # 7. Semantic completion judge (skip first N turns)
    last_judge_reason: str | None = None
    if goal.turns_used >= _JUDGE_SKIP_INITIAL_TURNS and tools_called_this_turn:
        last_response = _extract_last_ai_response(collected_messages)
        judge_reason, parse_failed = await _judge_completion(goal_provider, goal, last_response, collected_messages)
        if judge_reason is None:
            verification_passed = await _run_acceptance_verification(goal_provider, goal)
            if verification_passed:
                violations = _check_protected_integrity(goal.goal_id)
                if violations:
                    logger.warning(
                        "Goal %s completion blocked: %d protected file violation(s)",
                        goal.goal_id,
                        len(violations),
                    )
                    return _make_tamper_decision(goal, violations)

                logger.info("Goal %s completed by semantic judge (verification passed)", goal.goal_id)
                await finalize_goal_complete(goal_provider, goal, source="semantic_judge")
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
