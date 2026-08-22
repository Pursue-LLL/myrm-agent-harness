"""Streaming execution engine — recovery and loop control strategies Mixin.

[INPUT]
- agent._internals.agent_recovery (POS: message compression/truncation utilities)
- toolkits.llms.errors.classifier (POS: error classification)
- toolkits.llms.reliability.jittered_backoff (POS: jittered backoff)
- toolkits.llms.adapters.safety_termination_detector (POS: Safety termination detector)
- utils.token_economics.tracker (POS: LLM call metadata tracker)
- agent.streaming.recovery.stream_recovery_oneshot (POS: one-shot recovery strategies)
- agent.streaming.recovery.stream_recovery_continuation (POS: steering, subagent, and goal continuation recovery)
- agent.streaming.recovery.stream_recovery_truncation (POS: length truncation recovery)
- agent.streaming.escalation_scrubber::EscalationScrubber (POS: 流式层升级标记检测)
- utils.chat_utils::extract_answer_text (POS: 兼容 reasoning 模型 content 空回退的答案提取)

[OUTPUT]
- StreamRecoveryMixin: used by StreamExecutor via multiple inheritance
- _extract_retry_after_ms: module-level helper function
- _is_escalation_marker_message: module-level helper function

[POS]
StreamRecoveryMixin composes overflow, deferred failover (429 never failover; 529 after 3 consecutive; emits `model_failover_unconfigured` when failoverable but no fallback LLM), safety refusal fallback (HTTP 200 refusal/content_filter → safety_fallback_llm), escalation, transient retry, iteration-limit (with grace-call summary), empty-response, truncation, steering, subagent, and goal continuation recovery strategies.

"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from myrm_agent_harness.agent._internals.agent_recovery import (
    emergency_compact as _emergency_compact,
)
from myrm_agent_harness.agent._internals.agent_recovery import (
    truncate_oldest_rounds as _truncate_oldest_rounds,
)
from myrm_agent_harness.agent.errors.fault_side import FaultSide
from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.toolkits.llms.errors.classifier import (
    ErrorKind,
    classify_error,
    is_context_overflow,
)
from myrm_agent_harness.utils.chat_utils import extract_answer_text
from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .stream_recovery_continuation import (
    StreamContinuationRecoveryMixin,
)
from .stream_recovery_oneshot import (
    OneshotRecoveryMixin,
    _resolve_model_name_from_ctx,
)
from .stream_recovery_truncation import (
    StreamTruncationRecoveryMixin,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AnyMessage, BaseMessage
    from langgraph.graph.state import CompiledStateGraph

    from myrm_agent_harness.agent.streaming.stream_compactor import StreamCompactor
    from myrm_agent_harness.agent.streaming.stream_executor import StreamContext


logger = get_agent_logger(__name__)

_MAX_OVERFLOW_RETRIES = 2
_MAX_CONSECUTIVE_OVERLOADED_BEFORE_FAILOVER = 3
_RETRY_AFTER_RE = re.compile(r"retry.*?after.*?(\d+).*?second", re.IGNORECASE)


def _extract_retry_after_ms(exc: Exception) -> int | None:
    """Try to extract a retry-after duration from the exception.

    Priority:
    1. HTTP ``Retry-After`` header (seconds → ms)
    2. "retry after N seconds" in the error message
    """
    headers: dict[str, str] | None = getattr(exc, "headers", None) or getattr(exc, "response_headers", None)
    if headers:
        raw = headers.get("retry-after") or headers.get("Retry-After")
        if raw:
            try:
                return int(float(raw) * 1000)
            except (ValueError, TypeError, OverflowError):
                pass

    m = _RETRY_AFTER_RE.search(str(exc))
    if m:
        return int(m.group(1)) * 1000

    return None


class StreamRecoveryMixin(
    StreamContinuationRecoveryMixin,
    StreamTruncationRecoveryMixin,
    OneshotRecoveryMixin,
):
    """Error recovery strategy collection, used by StreamExecutor via multiple inheritance.

    One-shot handlers (thinking_signature, image_shrink, long_context_tier)
    are provided by OneshotRecoveryMixin.

    All methods access StreamExecutor attributes via self:
    _ctx, _compactor, _fallback_llm, _safety_fallback_llm,
    _rebuild_agent_fn, failover_used, _consecutive_overloaded, streaming_final_answer
    """

    _fallback_llm: BaseChatModel | None
    _safety_fallback_llm: BaseChatModel | None
    _rebuild_agent_fn: object
    _ctx: StreamContext
    _compactor: StreamCompactor
    failover_used: bool
    _escalation_used: bool
    _consecutive_overloaded: int

    def _rebind_agent_after_rebuild(self, new_llm: BaseChatModel) -> None:
        """Rebuild the agent graph for a different LLM and re-bind the active stream.

        ``rebuild_agent_with_llm`` replaces ``BaseAgent._agent`` with a freshly
        compiled graph, but ``StreamContext.agent`` still points at the previous
        graph — without re-binding here, the next ``astream`` retry would keep
        calling the failed primary LLM and failover would never take effect.
        """
        rebuild_fn = cast(
            "Callable[[BaseChatModel], CompiledStateGraph[Any, Any, Any, Any]]",
            self._rebuild_agent_fn,
        )
        self._ctx.agent = rebuild_fn(new_llm)

    async def _handle_overflow(self, exc: Exception, retries: int) -> bool:
        """Progressive overflow recovery using full structured compaction pipeline.

        Tier 1 (retries==0): attempt full structured summary compaction with entity
          audit and physical execution state reconciliation via generate_structured_summary.
        Tier 2 (fallback if Tier 1 yields 0 savings or errors): emergency tool-output compaction
          via _emergency_compact.
        Tier 3 (retries==1 or Tier 2 saved==0): drop oldest API-round groups
          via _truncate_oldest_rounds.
        """
        if not is_context_overflow(exc):
            return False
        if retries >= _MAX_OVERFLOW_RETRIES:
            self._ctx.stats.compression_exhausted = True
            logger.warning(" Context overflow recovery exhausted after %d retries", retries)
            return False

        ctx = self._ctx
        if isinstance(ctx.agent_input, Command):
            logger.warning(" Resume mode overflow, cannot compact — giving up")
            return False

        assert not isinstance(ctx.agent_input, Command)
        messages_dict = ctx.agent_input
        messages = cast(list["BaseMessage"], messages_dict.get("messages", []))

        saved = 0
        step_key = "context_compaction"

        if retries == 0:
            # Tier 1: Full structured summary compaction
            llm = ctx.llm or getattr(self, "_fallback_llm", None)
            if llm is not None:
                try:
                    from myrm_agent_harness.agent.context_management.strategies.summary.summarizer import (
                        generate_structured_summary,
                    )
                    from myrm_agent_harness.utils.token_estimation import (
                        estimate_messages_tokens,
                    )

                    orig_tokens = estimate_messages_tokens(messages)
                    chat_id = getattr(ctx, "message_id", None)
                    new_messages, _ = await generate_structured_summary(
                        messages=messages,
                        llm=llm,
                        chat_id=chat_id,
                    )
                    new_tokens = estimate_messages_tokens(new_messages)
                    if orig_tokens - new_tokens > 0:
                        saved = orig_tokens - new_tokens
                        messages.clear()
                        messages.extend(new_messages)
                        logger.warning(
                            " Context overflow Tier 1 structured summary succeeded: freed %d tokens",
                            saved,
                        )
                except Exception as e:
                    logger.warning(" Context overflow Tier 1 structured summary failed: %s", e)

            # Tier 2: Tool emergency compaction fallback
            if saved == 0:
                saved = await _emergency_compact(messages)
                if saved > 0:
                    logger.warning(
                        " Context overflow Tier 2 emergency tool compaction succeeded: freed %d tokens",
                        saved,
                    )

            # Tier 3: Oldest rounds truncation
            if saved == 0:
                saved = _truncate_oldest_rounds(messages)
                step_key = "context_truncation"
        else:
            saved = _truncate_oldest_rounds(messages)
            step_key = "context_truncation"

        logger.warning(
            " Context overflow recovery stage %d/%d: freed %d tokens, retrying",
            retries + 1,
            _MAX_OVERFLOW_RETRIES,
            saved,
        )
        await self._emit_recovery_event(step_key, restart=True)
        self.streaming_final_answer = False
        return True

    async def _handle_failover(self, exc: Exception) -> bool:
        """Handle LLM failover: switch to backup model + retry. Returns True if should continue."""
        error_kind = classify_error(exc)

        # Determine target fallback candidate
        if error_kind == ErrorKind.SAFETY_BLOCK:
            target_fallback_llm = self._safety_fallback_llm
            fallback_type = "safety_fallback"
        else:
            fallback_type = "fallback"
            fallback_candidates = getattr(self, "_fallback_llms", None) or (
                [self._fallback_llm] if self._fallback_llm else []
            )
            curr_idx = getattr(self, "_fallback_index", 0)
            if curr_idx < len(fallback_candidates):
                target_fallback_llm = fallback_candidates[curr_idx]
            else:
                target_fallback_llm = None

        logger.warning(
            " LLM error: %s (failoverable=%s, %s=%s)",
            error_kind.value,
            error_kind.is_failoverable,
            fallback_type,
            "ready" if target_fallback_llm and not self.failover_used else "none",
        )

        can_failover = error_kind.is_failoverable or (error_kind == ErrorKind.AUTH and target_fallback_llm is not None)
        if not can_failover or self.failover_used:
            return False

        if target_fallback_llm is None:
            if self._should_hint_missing_fallback(error_kind):
                await self._emit_failover_unconfigured_hint(error_kind)
            return False

        if error_kind == ErrorKind.RATE_LIMIT:
            logger.warning(" Rate limit: deferring to transient retry (failover skipped)")
            return False

        if error_kind == ErrorKind.OVERLOADED:
            self._consecutive_overloaded += 1
            if self._consecutive_overloaded < _MAX_CONSECUTIVE_OVERLOADED_BEFORE_FAILOVER:
                logger.warning(
                    " Overloaded (%d/%d): deferring to transient retry",
                    self._consecutive_overloaded,
                    _MAX_CONSECUTIVE_OVERLOADED_BEFORE_FAILOVER,
                )
                return False

        if error_kind == ErrorKind.SAFETY_BLOCK:
            self.failover_used = True
        else:
            self._fallback_index = getattr(self, "_fallback_index", 0) + 1
            fallback_candidates = getattr(self, "_fallback_llms", [])
            if self._fallback_index >= len(fallback_candidates):
                self.failover_used = True

        self._rebind_agent_after_rebuild(target_fallback_llm)
        fallback_model = getattr(target_fallback_llm, "model_name", None) or getattr(
            target_fallback_llm, "model", "backup"
        )

        logger.warning(" Failover: %s → switching to %s (step %s)", error_kind.value, fallback_model, getattr(self, "_fallback_index", 1))

        step_key = "safety_fallback_active" if error_kind == ErrorKind.SAFETY_BLOCK else "model_failover"

        await self._emit_recovery_event(
            step_key,
            error_kind=error_kind.value,
            fallback_model=fallback_model,
            restart=True,
        )
        from_model = _resolve_model_name_from_ctx(self._ctx) or "primary"
        await self._emit_failover_sse_notify(
            error_kind=error_kind,
            from_model=from_model,
            to_model=str(fallback_model),
            error_message=str(exc),
        )
        self.streaming_final_answer = False
        return True

    async def _emit_failover_sse_notify(
        self,
        *,
        error_kind: ErrorKind,
        from_model: str,
        to_model: str,
        error_message: str | None,
    ) -> None:
        """Mirror stream-recovery failover into MODEL_FAILOVER SSE for WebUI toasts."""
        from myrm_agent_harness.toolkits.llms.fallback import FailoverEvent
        from myrm_agent_harness.toolkits.llms.fallback.context import (
            get_active_failover_emitter,
        )

        emitter = get_active_failover_emitter()
        if emitter is None:
            return
        try:
            await emitter.emit_failover(
                FailoverEvent(
                    from_model=from_model,
                    to_model=to_model,
                    reason=error_kind.to_failover_reason(),
                    error_message=error_message,
                )
            )
        except Exception as emit_exc:
            logger.warning(" Failover SSE notify failed: %s", emit_exc)

    async def _emit_failover_unconfigured_hint(self, error_kind: ErrorKind) -> None:
        """Emit STATUS when failover is possible but no fallback LLM is configured."""
        if getattr(self, "failover_unconfigured_notified", False):
            return
        self.failover_unconfigured_notified = True
        step_key = (
            "safety_fallback_unconfigured" if error_kind == ErrorKind.SAFETY_BLOCK else "model_failover_unconfigured"
        )
        logger.warning(
            " Failover skipped: no %s LLM configured (%s)",
            "safety fallback" if error_kind == ErrorKind.SAFETY_BLOCK else "fallback",
            error_kind.value,
        )
        await self._emit_recovery_event(step_key, error_kind=error_kind.value)

    @staticmethod
    def _should_hint_missing_fallback(error_kind: ErrorKind) -> bool:
        """Hint only when missing fallback is the blocker (not deferred-retry kinds)."""
        return error_kind not in (ErrorKind.RATE_LIMIT, ErrorKind.OVERLOADED)

    async def _handle_safety_refusal_fallback(self) -> bool:
        """Fallback on HTTP 200 safety refusal (finish_reason in SAFETY_FINISH_REASONS).

        When the LLM returns a successful response but with a safety-related
        finish_reason (e.g. ``refusal``, ``content_filter``, ``SAFETY``), the
        response is typically empty. Without this handler, it falls through to
        ``_handle_empty_response`` which wastes 2 retries on a deterministic
        refusal, then raises FORMAT_ERROR (non-failoverable) — making the
        configured ``safety_fallback_llm`` unreachable.

        This handler intercepts the safety refusal *before* the empty-response
        retry path and routes it through the existing safety fallback mechanism.

        Returns True when a safety fallback was activated (caller should ``continue``).
        """
        from myrm_agent_harness.toolkits.llms.adapters.safety_termination_detector import (
            detect_safety_termination,
        )
        from myrm_agent_harness.utils.token_economics.tracker import get_token_tracker

        tracker = get_token_tracker()
        if tracker is None:
            return False

        finish_reason = tracker.last_finish_reason
        if not finish_reason or not detect_safety_termination(finish_reason):
            return False

        if self._safety_fallback_llm is None or self.failover_used:
            logger.warning(
                " Safety refusal (finish_reason=%s) but no fallback available (fallback_used=%s)",
                finish_reason,
                self.failover_used,
            )
            return False

        self.failover_used = True
        self._rebind_agent_after_rebuild(self._safety_fallback_llm)
        fallback_model = getattr(self._safety_fallback_llm, "model_name", None) or getattr(
            self._safety_fallback_llm, "model", "backup"
        )

        logger.warning(
            " Safety refusal fallback: finish_reason=%s → switching to %s",
            finish_reason,
            fallback_model,
        )

        await self._emit_recovery_event(
            "safety_fallback_active",
            error_kind=ErrorKind.SAFETY_BLOCK.value,
            fallback_model=fallback_model,
            restart=True,
        )
        self.streaming_final_answer = False
        return True

    async def _handle_escalation(
        self,
        collected_messages: list[BaseMessage],
    ) -> bool:
        """Handle model self-escalation: switch to a stronger model and retry.

        When the EscalationScrubber detects a marker (e.g. ``<<<NEEDS_PRO>>>``),
        this handler switches to the escalation target model and replays the turn.

        Returns True when an escalation was performed (caller should ``continue``).
        """
        from myrm_agent_harness.agent.streaming.escalation_scrubber import (
            EscalationScrubber,
        )

        scrubber: EscalationScrubber = self._escalation_scrubber  # type: ignore[attr-defined]
        if not scrubber.detected:
            return False

        ctx = self._ctx
        escalation_target = ctx.escalation_target_llm
        if escalation_target is None:
            logger.warning(" Escalation marker detected but no escalation_target_llm configured — ignoring")
            return False

        if self._escalation_used:
            logger.warning(" Escalation already used this session — marker treated as normal content")
            return False

        self._escalation_used = True

        current_model = (ctx.llm_info or {}).get("model_name", "unknown")

        target_model = getattr(escalation_target, "model_name", None) or getattr(
            escalation_target, "model", "stronger-model"
        )

        if current_model == target_model:
            logger.warning(
                " Current model == escalation target (%s) — marker ignored",
                current_model,
            )
            return False

        if isinstance(ctx.agent_input, Command):
            logger.warning(" Resume mode — escalation not supported")
            return False

        logger.warning(
            " Model self-escalation: %s → %s (reason: %s)",
            current_model,
            target_model,
            scrubber.reason or "none",
        )

        self._rebind_agent_after_rebuild(escalation_target)

        await self._compactor.put(
            {
                "type": AgentEventType.MODEL_ESCALATED.value,
                "data": {
                    "from_model": current_model,
                    "to_model": target_model,
                    "reason": scrubber.reason,
                    "restart": True,
                },
                "messageId": ctx.message_id,
            }
        )

        messages_dict = ctx.agent_input
        messages = cast(list["BaseMessage"], messages_dict.get("messages", []))
        messages.clear()
        original_messages = [m for m in collected_messages if not _is_escalation_marker_message(m)]
        messages.extend(original_messages)
        messages_dict["messages"] = cast("list[AnyMessage]", messages)

        scrubber.reset()
        self.streaming_final_answer = False
        return True

    async def _handle_transient_retry(self, exc: Exception, retries: int) -> bool:
        """Handle transient errors via jittered backoff. Returns True to retry."""
        from myrm_agent_harness.toolkits.llms.reliability.jittered_backoff import (
            calculate_jittered_delay,
        )

        error_kind = classify_error(exc)

        transient_kinds = {
            ErrorKind.RATE_LIMIT,
            ErrorKind.OVERLOADED,
            ErrorKind.TIMEOUT,
        }
        if error_kind not in transient_kinds:
            return False

        max_transient_retries = 15
        if retries >= max_transient_retries:
            logger.warning(
                " Transient retry exhausted after %d attempts for %s",
                retries,
                error_kind.value,
            )

            # If we have an active goal, pause it instead of failing completely
            if hasattr(self._ctx, "goal_provider") and self._ctx.goal_provider:
                from myrm_agent_harness.agent.goals.types import GoalStatus

                goal = await self._ctx.goal_provider.get_active_goal(self._ctx.message_id)
                if goal:
                    logger.warning(
                        " Goal %s paused due to exhausted transient retries (e.g. 429 Rate Limit)",
                        goal.goal_id,
                    )
                    await self._ctx.goal_provider.update_status(goal.goal_id, GoalStatus.PAUSED)

            return False

        retry_after_ms = _extract_retry_after_ms(exc)
        retry_after_sec = (retry_after_ms / 1000.0) if retry_after_ms else None

        delay_seconds = calculate_jittered_delay(
            attempt=retries + 1,
            base_delay=2.0,
            max_delay=60.0,
            retry_after=retry_after_sec,
        )

        logger.warning(
            " Transient error (%s): %s. Jittered Retry attempt %d/%d in %.2fs",
            error_kind.value,
            str(exc)[:100],
            retries + 1,
            max_transient_retries,
            delay_seconds,
        )

        await self._emit_recovery_event(
            "transient_retry",
            error_kind=error_kind.value,
            delay_ms=int(delay_seconds * 1000),
            attempt=retries + 1,
            restart=True,
        )

        if self._ctx.cancel_token:
            steps = int(delay_seconds * 10)
            for _ in range(steps):
                if self._ctx.cancel_token.is_cancelled:
                    return False
                await asyncio.sleep(0.1)
            remainder = delay_seconds - (steps * 0.1)
            if remainder > 0:
                await asyncio.sleep(remainder)
        else:
            await asyncio.sleep(delay_seconds)

        if self._ctx.cancel_token and self._ctx.cancel_token.is_cancelled:
            return False

        self.streaming_final_answer = False
        return True

    async def _handle_iteration_limit(
        self,
        exc: Exception,
        collected_messages: list[BaseMessage],
    ) -> bool:
        """Detect GraphRecursionError, generate a grace-call summary, and emit events.

        When the LangGraph recursion limit is reached:
        1. Emit ITERATION_LIMIT_REACHED event (frontend shows a warning badge).
        2. Perform a **grace call**: one extra toolless LLM invocation that produces
           a summary from the conversation so far, ensuring the user never sees a
           blank response.
        3. Return True so the caller can decide whether to break (normal mode) or
           fall through to goal-continuation (goal mode).
        """
        from langgraph.errors import GraphRecursionError

        if not isinstance(exc, GraphRecursionError):
            return False

        ctx = self._ctx
        recursion_limit = ctx.run_config.get("recursion_limit", "?")
        logger.warning(
            " Iteration limit reached (%s). Completed %d nodes before limit. Detail: %s",
            recursion_limit,
            ctx.stats.node_execution_count,
            exc,
        )

        await self._compactor.put(
            {
                "type": AgentEventType.ITERATION_LIMIT_REACHED.value,
                "data": {
                    "limit": recursion_limit,
                    "nodes_completed": ctx.stats.node_execution_count,
                    # Recursion limit is an engine pipeline guard, not a model or
                    # tool failure — attribute to HARNESS_PIPELINE.
                    "fault_side": FaultSide.HARNESS_PIPELINE.value,
                },
                "messageId": ctx.message_id,
            }
        )

        await self._grace_call_summary(collected_messages)
        return True

    _GRACE_FALLBACK_EN = (
        "I reached the iteration limit before completing the task. "
        "Please try again with a more specific request, or I can "
        "continue from where I left off."
    )
    _GRACE_FALLBACK_ZH = "本轮执行已达到迭代上限，任务尚未完成。你可以尝试更具体的指令，或者让我从上次中断的地方继续。"

    def _grace_fallback_text(self) -> str:
        locale = self._ctx.merged_context.get("locale", "en") if self._ctx.merged_context else "en"
        return self._GRACE_FALLBACK_ZH if locale.startswith("zh") else self._GRACE_FALLBACK_EN

    async def _grace_call_summary(
        self,
        collected_messages: list[BaseMessage],
    ) -> None:
        """Perform a single toolless LLM call to summarise progress so far.

        The summary is emitted as a normal ``MESSAGE`` event so the frontend
        renders it automatically — no frontend changes required.
        """
        from langchain_core.messages import AIMessage, HumanMessage

        from myrm_agent_harness.agent.middlewares.tooling.dangling_tool_call_middleware import (
            repair_dangling_tool_calls,
        )
        from myrm_agent_harness.agent.middlewares.tooling.tool_history_hygiene import (
            sanitize_tool_history,
        )

        llm = self._ctx.llm
        if llm is None:
            await self._emit_message_pair(self._grace_fallback_text())
            return

        grace_prompt = HumanMessage(
            content=(
                "[SYSTEM] You have reached the maximum iteration limit for this turn. "
                "Based on the work you have done so far, provide a concise summary of "
                "your findings and any remaining tasks. Do NOT call any tools. "
                "If prior tool messages already contain successful MCP, web search, or "
                "browser results, summarize that data faithfully — do not claim tools "
                "were not called. "
                "Respond in the same language as the conversation."
            ),
        )
        repaired_messages = repair_dangling_tool_calls(sanitize_tool_history(list(collected_messages)))
        tail = repaired_messages[-20:]
        while tail and getattr(tail[0], "type", None) == "tool":
            tail = tail[1:]
        summary_messages: list[BaseMessage] = tail
        summary_messages.append(grace_prompt)

        try:
            response: AIMessage = await llm.ainvoke(summary_messages)
            # 兼容 reasoning 模型 content 空回退（Qwen3/DeepSeek-R1 等）
            summary_text = extract_answer_text(response).strip()
        except Exception:
            logger.warning("Grace call LLM invocation failed; using fallback message")
            summary_text = ""

        await self._emit_message_pair(summary_text.strip() if summary_text else self._grace_fallback_text())

    async def _emit_message_pair(self, text: str) -> None:
        """Emit a MESSAGE + MESSAGE_END event pair."""
        mid = self._ctx.message_id
        await self._compactor.put({"type": AgentEventType.MESSAGE.value, "data": text, "messageId": mid})
        await self._compactor.put({"type": AgentEventType.MESSAGE_END.value, "data": "", "messageId": mid})

    async def _handle_empty_response(
        self,
        collected_messages: list[BaseMessage],
        retries: int = 0,
    ) -> bool:
        """Detect empty LLM response and inject a prompt to recover.

        Returns True when a continuation prompt was injected (caller should ``continue``
        the outer loop to re-run astream). Returns False otherwise.
        """
        from langchain_core.messages import AIMessage

        last_ai_msg: AIMessage | None = None
        for msg in reversed(collected_messages):
            if isinstance(msg, AIMessage):
                last_ai_msg = msg
                break

        if last_ai_msg is None:
            return False

        has_tool_calls = bool(last_ai_msg.tool_calls)
        has_content = self._has_non_reasoning_content(last_ai_msg)

        # If it has tool calls or any user-visible content, it's not an empty response.
        # Note: We do NOT exempt reasoning-only responses (e.g. <thinking> blocks without actual output).
        # A reasoning-only response is still an empty response from the user's perspective and must be retried.
        if has_tool_calls or has_content:
            return False

        max_empty_retries = 2
        if retries >= max_empty_retries:
            logger.error(
                " Empty response recovery exhausted after %d retries. Raising error.",
                retries,
            )
            from myrm_agent_harness.toolkits.llms.errors import MyrmLLMError
            from myrm_agent_harness.toolkits.llms.errors.error_types import (
                FailoverReason,
            )

            raise MyrmLLMError(
                error_code=FailoverReason.FORMAT_ERROR,
                default_msg="LLM returned an empty response repeatedly.",
            )

        ctx = self._ctx
        if isinstance(ctx.agent_input, Command):
            logger.warning(" Resume mode — empty response recovery not supported")
            return False

        messages_dict = ctx.agent_input
        messages = cast(list["BaseMessage"], messages_dict.get("messages", []))

        messages.clear()
        messages.extend(collected_messages)

        recovery_prompt = (
            "[System: Your response was completely empty (no text and no tool calls). "
            "Please provide your answer or call a tool to proceed with the task.]"
        )
        messages.append(HumanMessage(content=recovery_prompt))
        messages_dict["messages"] = cast("list[AnyMessage]", messages)
        self.streaming_final_answer = False

        logger.warning(
            "↻ Empty response detected. Injecting recovery prompt (%d/%d)...",
            retries + 1,
            max_empty_retries,
        )

        await self._emit_recovery_event("empty_response_recovery", restart=True)
        return True


def _is_escalation_marker_message(msg: BaseMessage) -> bool:
    """Check if a message is an AI response that only contains an escalation marker."""
    from langchain_core.messages import AIMessage

    if not isinstance(msg, AIMessage):
        return False
    content = msg.content
    if isinstance(content, str):
        trimmed = content.strip()
        return trimmed.startswith("<<<NEEDS_PRO") and trimmed.endswith(">>>")
    return False
