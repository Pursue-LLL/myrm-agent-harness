"""Pre-call and post-call guard orchestration for tool interception.

Pre-call guards check conditions before a tool executes (e-stop, loop
detection, steering, trust, PII).  Post-call guards process the result
(budget truncation, poisoning, taint, hook validation, loop recording).

[INPUT]
- agent.security.guards.estop (POS: Global guard)
- agent.security.guards.loop_guard (POS: Session-level loop detection guard)
- agent.security.guards.context_budget (POS: Session-level context budget guard)
- agent.security.guards.frequency_guard (POS: Session-level frequency guard)
- agent.security.audit (POS: Cross-cutting security audit)
- agent.middlewares._tool_helpers (POS: Stateless helper functions)
- agent.middlewares._session_context (POS: Middleware session context)
- utils.runtime.steering (POS: Steering token management)

[OUTPUT]
- PreCallResult: data holder for pre-call guard state
- run_pre_call_guards: execute all pre-call guards
- run_post_call_guards: execute all post-call guards

[POS]
Pre-/post-call guard execution for tool interceptor middleware.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from myrm_agent_harness.agent.middlewares._session_context import (
    get_terminal_errors,
)
from myrm_agent_harness.agent.middlewares._tool_helpers import (
    apply_validation_result,
    build_hook_failure_result,
    check_tool_params_pii,
    check_tool_result_pii,
    check_trust_attenuation,
    emit_archive_restore_block_status,
    emit_hook_failure_event,
    extract_text_content,
    make_error_msg,
    run_content_validation,
)
from myrm_agent_harness.agent.security.audit import record_decision
from myrm_agent_harness.agent.security.guards.context_budget import (
    BudgetAction,
    get_context_budget_guard,
)
from myrm_agent_harness.agent.security.guards.estop import EStopLevel, check_estop
from myrm_agent_harness.agent.security.guards.frequency_guard import (
    FrequencyAction,
    get_frequency_guard,
)
from myrm_agent_harness.agent.security.guards.loop_guard import LoopGuard
from myrm_agent_harness.agent.security.guards.loop_guard_types import LoopAction
from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.runtime.steering import (
    STEERING_SKIP_MESSAGE,
    get_steering_token,
)
from myrm_agent_harness.utils.token_economics.tracker import get_token_tracker

logger = get_agent_logger(__name__)


# ---------------------------------------------------------------------------
# Pre-call result holder
# ---------------------------------------------------------------------------


class PreCallResult:
    """Carries forward state from pre-call guards into the post-call phase."""

    __slots__ = (
        "freq_guard",
        "freq_verdict",
        "loop_guard",
        "loop_verdict",
        "steering_token",
    )

    def __init__(
        self,
        loop_guard: LoopGuard,
        loop_verdict: Any,
        freq_guard: Any,
        freq_verdict: Any,
        steering_token: Any,
    ) -> None:
        self.loop_guard = loop_guard
        self.loop_verdict = loop_verdict
        self.freq_guard = freq_guard
        self.freq_verdict = freq_verdict
        self.steering_token = steering_token


# ---------------------------------------------------------------------------
# Pre-call guards
# ---------------------------------------------------------------------------


async def run_pre_call_guards(
    request: ToolCallRequest,
    tool_name: str,
    tool_call_id: str,
    tool_args: dict[str, object],
    get_loop_guard_fn: Any = None,
) -> ToolMessage | PreCallResult:
    """Execute all pre-call guards. Returns ToolMessage if blocked, PreCallResult to proceed."""
    from myrm_agent_harness.agent.hooks.executor import fire_hook
    from myrm_agent_harness.agent.hooks.types import HookEvent

    if get_loop_guard_fn is None:
        from myrm_agent_harness.agent.middlewares.tool_interceptor_middleware import (
            get_loop_guard as get_loop_guard_fn,
        )

    pre_hook_result = await fire_hook(
        HookEvent.PRE_TOOL_USE,
        {"tool_name": tool_name, "tool_input": tool_args, "tool_call_id": tool_call_id},
    )
    if pre_hook_result.blocked:
        record_decision(tool_name, "HOOK_BLOCKED", pre_hook_result.reason)
        return make_error_msg(
            tool_name,
            tool_call_id,
            f"Blocked by hook: {pre_hook_result.reason}",
            error_category="hook_blocked",
        )
    if pre_hook_result.updated_input is not None:
        tool_args.clear()
        tool_args.update(pre_hook_result.updated_input)
        request.tool_call["args"] = tool_args

    blocked = _check_circuit_breaker(tool_name, tool_call_id)
    if blocked:
        return blocked

    estop_state = check_estop()
    if estop_state is not None:
        record_decision(
            tool_name,
            "ESTOP_BLOCKED",
            f"E-Stop active: {estop_state.level} — {estop_state.reason}",
        )
        msg = f"E-Stop active ({estop_state.level}): all tool execution is suspended. Reason: {estop_state.reason}"
        if estop_state.level == EStopLevel.KILL_ALL:
            msg = f"EMERGENCY: {msg}"
        return make_error_msg(tool_name, tool_call_id, msg, error_category="estop")

    from myrm_agent_harness.agent.security.guards.config_protection import check_config_protection

    config_guard_msg = check_config_protection(tool_name, tool_args)
    if config_guard_msg is not None:
        record_decision(tool_name, "CONFIG_PROTECTION_BLOCKED", config_guard_msg)
        return make_error_msg(tool_name, tool_call_id, config_guard_msg, error_category="config_protection")

    loop_guard = get_loop_guard_fn()
    tracker = get_token_tracker()
    if tracker and tracker.usage.last_call:
        loop_guard.feed_output_tokens(
            tracker.call_count,
            tracker.usage.last_call.completion_tokens,
            has_tool_call=True,
        )

    try:
        loop_verdict = loop_guard.pre_check(tool_name, tool_args)
    except Exception as pre_check_exc:
        from myrm_agent_harness.agent.errors.agent_errors import ToolStuckException

        if isinstance(pre_check_exc, ToolStuckException):
            from langgraph.types import interrupt

            logger.warning(
                "ToolStuckException → GraphInterrupt [%s]: %s",
                tool_name,
                str(pre_check_exc)[:200],
            )
            interrupt(
                {
                    "action_type": "tool_stuck",
                    "tool_name": tool_name,
                    "tool_call_id": tool_call_id,
                    "error_message": str(pre_check_exc),
                }
            )
            return make_error_msg(
                tool_name,
                tool_call_id,
                f"Error: {pre_check_exc}",
                error_category="loop_guard",
                loop_kind="iteration_budget",
            )
        raise pre_check_exc

    metrics = loop_guard.get_metrics()
    if metrics.total_calls % 100 == 0 and metrics.total_calls > 0:
        logger.info(
            "Loop guard: %d calls, detection_rate=%.1f%%, avg_streak=%.1f, "
            "param_change=%.1f%%, effective_follow=%.1f%%",
            metrics.total_calls,
            metrics.detection_rate * 100,
            metrics.avg_streak,
            metrics.param_change_rate * 100,
            metrics.effective_follow_rate * 100,
        )

    if loop_verdict.action == LoopAction.BREAK:
        raw_loop_kind = getattr(loop_verdict, "loop_kind", None)
        loop_kind = raw_loop_kind if isinstance(raw_loop_kind, str) else "loop_break"
        record_decision(tool_name, "LOOP_BREAK", loop_verdict.reason)
        logger.warning("Loop break: %s -- %s", tool_name, loop_verdict.reason)
        return make_error_msg(
            tool_name,
            tool_call_id,
            f"Error: {loop_verdict.reason}\n\nHint: {loop_verdict.backoff_hint}",
            error_category="loop_guard",
            loop_kind=loop_kind,
        )
    if loop_verdict.action == LoopAction.WARN:
        record_decision(tool_name, "LOOP_WARN", loop_verdict.reason)
        logger.warning("Loop warning: %s -- %s", tool_name, loop_verdict.reason)

    freq_guard = get_frequency_guard()
    freq_verdict = freq_guard.check(tool_name)

    if freq_verdict.action == FrequencyAction.BREAK:
        record_decision(tool_name, "FREQUENCY_BREAK", freq_verdict.reason)
        logger.warning("Frequency break: %s -- %s", tool_name, freq_verdict.reason)
        return make_error_msg(
            tool_name,
            tool_call_id,
            f"Error: {freq_verdict.reason}\n\n"
            f"Global: {freq_verdict.global_count}/{freq_verdict.global_limit} calls, "
            f"{freq_verdict.global_remaining} remaining.\n"
            f"Tool: {freq_verdict.tool_count}/{freq_verdict.tool_limit} calls, "
            f"{freq_verdict.tool_remaining} remaining.",
            error_category="frequency_guard",
        )
    if freq_verdict.action == FrequencyAction.WARN:
        record_decision(tool_name, "FREQUENCY_WARN", freq_verdict.reason)
        logger.warning("Frequency warning: %s -- %s", tool_name, freq_verdict.reason)

    steering_token = get_steering_token()
    if steering_token and steering_token.is_active:
        logger.warning("Steering skip: %s", tool_name)
        return make_error_msg(
            tool_name,
            tool_call_id,
            STEERING_SKIP_MESSAGE,
            error_category="steering",
        )

    if request.tool is None:
        error_content = (
            f"Error: '{tool_name}' is not a valid tool. Please retry.\n\n"
            "Hint: Do not confuse tools with skills. "
            "Tools are for LLM to call directly. "
            "Skills (ending with _skill) are operation manuals for certain workflows "
            "and cannot be called directly by LLM. "
            "You must first use skill_select_tool to select a skill, then learn from its documentation!"
        )
        logger.warning("Invalid tool call: %s", tool_name)
        return make_error_msg(
            tool_name,
            tool_call_id,
            error_content,
            error_category="invalid_tool",
        )

    attenuation_msg = check_trust_attenuation(tool_name)
    if attenuation_msg:
        return make_error_msg(
            tool_name,
            tool_call_id,
            attenuation_msg,
            error_category="trust_attenuation",
        )

    pii_block_msg = check_tool_params_pii(tool_name, tool_args)
    if pii_block_msg:
        return make_error_msg(
            tool_name,
            tool_call_id,
            pii_block_msg,
            error_category="pii_guard",
        )

    return PreCallResult(loop_guard, loop_verdict, freq_guard, freq_verdict, steering_token)


def _check_circuit_breaker(tool_name: str, tool_call_id: str) -> ToolMessage | None:
    """Check Myrm-Guard hard circuit breaker. Returns error message if blocked."""
    registry = get_terminal_errors()
    registry._load()
    terminal_errors = registry.get_all()
    if not terminal_errors:
        return None

    t_lower = tool_name.lower()
    is_network_tool = any(kw in t_lower for kw in ["web", "search", "browser", "fetch", "http", "network", "mcp"])
    is_write_tool = any(kw in t_lower for kw in ["write", "edit", "create", "delete", "mkdir", "rm", "append"])

    blocker = None
    if "any" in terminal_errors:
        blocker = "any"
    elif "network_blocked" in terminal_errors and is_network_tool:
        blocker = "network_blocked"
    elif "sandbox_ro" in terminal_errors and is_write_tool:
        blocker = "sandbox_ro"

    if blocker:
        hint = f"Circuit breaker active for {blocker}. Previous failures indicate this resource is unavailable."
        logger.warning("Circuit breaker: blocked %s due to terminal %s", tool_name, blocker)
        return make_error_msg(
            tool_name,
            tool_call_id,
            f"Error: [SYSTEM_ENFORCED] Execution of '{tool_name}' blocked by circuit breaker.\nDetails: {hint}",
            error_category="circuit_breaker",
            error_hint=hint,
        )
    return None


# ---------------------------------------------------------------------------
# Post-call guards
# ---------------------------------------------------------------------------


async def run_post_call_guards(
    result: ToolMessage | Any,
    tool_name: str,
    tool_call_id: str,
    tool_args: dict[str, object],
    loop_guard: LoopGuard,
    loop_verdict: Any,
    freq_guard: Any,
    freq_verdict: Any,
    steering_token: Any,
) -> ToolMessage | Any:
    """Execute all post-call guards on a ToolMessage. Returns (possibly modified) result."""
    from myrm_agent_harness.agent.hooks.executor import fire_hook
    from myrm_agent_harness.agent.hooks.types import HookEvent
    from myrm_agent_harness.agent.streaming.types import AgentEventType

    if steering_token and steering_token.has_pending:
        steering_token.activate()

    if not isinstance(result, ToolMessage):
        return result

    result_text = extract_text_content(result.content)

    if not result_text.strip():
        result_text = "(no output)"
        result = ToolMessage(
            content=result_text,
            name=tool_name,
            tool_call_id=result.tool_call_id,
            status=result.status,
        )

    await emit_archive_restore_block_status(result_text, tool_name)

    from myrm_agent_harness.agent.middlewares._mutation_verifier import (
        record_mutation_result,
    )

    record_mutation_result(
        tool_name=tool_name,
        tool_args=dict(tool_args),
        is_error=(result.status == "error"),
        error_content=result_text if result.status == "error" else None,
    )

    budget_guard = get_context_budget_guard()
    budget_verdict = budget_guard.check_and_truncate(result_text, tool_name)
    if budget_verdict.action == BudgetAction.PERSISTED:
        record_decision(tool_name, "CONTEXT_PERSISTED", budget_verdict.reason)
        logger.info(
            "Context budget persisted: %s -> %s",
            tool_name,
            budget_verdict.persisted_path,
        )
        result = ToolMessage(
            content=budget_verdict.content,
            name=tool_name,
            tool_call_id=result.tool_call_id,
            status=result.status,
        )
        result_text = budget_verdict.content
    elif budget_verdict.action == BudgetAction.TRUNCATED:
        record_decision(tool_name, "CONTEXT_TRUNCATED", budget_verdict.reason)
        logger.warning("Context budget truncated: %s -- %s", tool_name, budget_verdict.reason)
        result = ToolMessage(
            content=budget_verdict.content,
            name=tool_name,
            tool_call_id=result.tool_call_id,
            status=result.status,
        )
        result_text = budget_verdict.content
    elif budget_verdict.action == BudgetAction.WARNING:
        logger.warning("Context budget warning: %s", budget_verdict.reason)

    validation = run_content_validation(result_text, tool_name)
    if validation is not None:
        logger.warning("Context poisoning [%s]: %s", tool_name, validation.reason)
        result = apply_validation_result(result, validation, tool_name)

    from myrm_agent_harness.agent.security.guards.taint_tracker import get_taint_tracker

    get_taint_tracker().record_tool_output(tool_name, tool_input=tool_args)

    result, result_text = check_tool_result_pii(result, result_text, tool_name)

    from myrm_agent_harness.agent.workspace_rules.tracker import (
        check_and_append_rules,
    )

    rules_append = check_and_append_rules(tool_name, tool_args, result_text)
    if rules_append and isinstance(result.content, str):
        result = ToolMessage(
            content=f"{result.content}\n{rules_append}",
            name=tool_name,
            tool_call_id=result.tool_call_id,
            status=result.status,
        )
        result_text = extract_text_content(result.content)

    post_verdict = loop_guard.record_result(tool_name, tool_args, result_text)
    if post_verdict.action == LoopAction.WARN:
        record_decision(tool_name, "LOOP_WARN", post_verdict.reason)
        logger.warning("Loop output warning: %s -- %s", tool_name, post_verdict.reason)

    freq_guard.record(tool_name)

    if tool_name == "bash_code_execute_tool":
        from myrm_agent_harness.agent.middlewares.completion_guard import (
            classify_verification,
        )

        vtype = classify_verification(tool_args)
        if vtype is not None:
            loop_guard.tag_last_verification(vtype)

    warnings: list[str] = []
    if loop_verdict.action == LoopAction.WARN or post_verdict.action == LoopAction.WARN:
        hint = loop_verdict.backoff_hint or post_verdict.backoff_hint
        if hint:
            warnings.append(f"Loop detected: {hint}")

    if freq_verdict.action == FrequencyAction.WARN:
        warnings.append(
            f"Frequency warning: {freq_verdict.reason}\n"
            f"Global: {freq_verdict.global_count}/{freq_verdict.global_limit} calls, "
            f"{freq_verdict.global_remaining} remaining.\n"
            f"Tool: {freq_verdict.tool_count}/{freq_verdict.tool_limit} calls, "
            f"{freq_verdict.tool_remaining} remaining."
        )

    if warnings and isinstance(result.content, str):
        warning_text = "\n\n".join(warnings)
        result = ToolMessage(
            content=f"{result.content}\n\n{warning_text}",
            name=tool_name,
            tool_call_id=result.tool_call_id,
            status=result.status,
        )

    post_result_text = extract_text_content(result.content)
    post_hook_result = await fire_hook(
        HookEvent.POST_TOOL_USE,
        {
            "tool_name": tool_name,
            "tool_input": tool_args,
            "tool_output": post_result_text,
            "tool_call_id": tool_call_id,
        },
    )
    if post_hook_result.blocked or not post_hook_result.all_succeeded:
        result = build_hook_failure_result(result, post_hook_result, tool_name, tool_call_id, post_result_text)
        await emit_hook_failure_event(tool_name, post_hook_result, AgentEventType)

    return result
