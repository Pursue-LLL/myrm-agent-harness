"""流式执行引擎 — 封装 astream 的完整生命周期

[INPUT]
- langchain_core.messages::BaseMessage, HumanMessage (POS: LangChain 消息类型)
- agent.streaming.event_handlers (POS: 事件处理器)
- agent.streaming.artifact_events (POS: Artifact 事件处理器)
- agent.streaming.source_tracker::SourceTracker (POS: 源追踪器)
- agent.streaming.reasoning_scrubber::ReasoningScrubber (POS: 流式清洗器)
- agent.streaming.escalation_scrubber::EscalationScrubber (POS: 流式层升级标记检测)
- agent.streaming.stream_recovery_truncation::reset_ephemeral_max_output_tokens (POS: ephemeral output token cleanup)
- agent.types::AgentEventType, AgentRunStatistics (POS: 类型定义)

[OUTPUT]
- StreamContext: 执行上下文 dataclass (含 drain_subagent_notifications, on_loop_restart 等可选回调)
- StreamExecutor: 流式执行引擎

[POS]
Stream execution engine. Encapsulates the complete lifecycle of Agent.astream().

"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, cast

from langchain.agents.middleware.types import AgentState
from langchain_core.runnables.config import RunnableConfig
from langgraph.types import Command

from myrm_agent_harness.agent.middlewares.tool_interceptor_middleware import (
    reset_loop_guard,
)
from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.agent.types import AgentRunStatistics
from myrm_agent_harness.toolkits.llms.errors import (
    MyrmLLMError,
    classify_failover_reason,
)
from myrm_agent_harness.toolkits.llms.errors.classifier import classify_error
from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .reasoning_scrubber import ReasoningScrubber
from .source_tracker import SourceTracker
from .stream_compactor import StreamCompactor
from .stream_dispatcher import StreamDispatcherMixin
from .stream_recovery import StreamRecoveryMixin, _extract_retry_after_ms

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import BaseMessage
    from langgraph.graph.state import CompiledStateGraph

    from myrm_agent_harness.agent.event_log.logger import EventLogger
    from myrm_agent_harness.agent.goals.protocols import GoalProvider
    from myrm_agent_harness.agent.goals.types import Goal, GoalExecutionSummary
    from myrm_agent_harness.utils.runtime.cancellation import CancellationToken
    from myrm_agent_harness.utils.runtime.steering import SteeringToken

logger = get_agent_logger(__name__)

STREAM_DONE = object()


@dataclasses.dataclass
class StreamContext:
    """astream 执行所需的所有上下文。

    将 10+ 个上下文变量显式化为 dataclass 字段,
    避免闭包隐式捕获, 提高可读性和可测试性。

    支持两种输入模式:
    1. 普通模式: agent_input 为 {"messages": [...]}
    2. Resume 模式: agent_input 为 Command(resume=...)
    """

    agent: CompiledStateGraph[Any, Any, Any, Any]
    agent_input: Command[Any] | AgentState[Any]
    merged_context: dict[str, Any]
    run_config: RunnableConfig
    stats: AgentRunStatistics
    message_id: str
    cancel_token: CancellationToken | None
    steering_token: SteeringToken | None
    source_tracker: SourceTracker
    output_queue: asyncio.Queue[dict[str, object] | object]
    event_logger: EventLogger | None = None
    drain_subagent_notifications: Callable[[], str | None] | None = None
    drain_teammate_messages: Callable[[], str | None] | None = None
    llm_info: dict[str, str | None] | None = None
    goal_provider: GoalProvider | None = None
    on_goal_terminal: Callable[[Goal, list[BaseMessage], GoalExecutionSummary], Awaitable[None]] | None = None
    on_loop_restart: Callable[[str, Goal], Awaitable[None]] | None = None
    escalation_target_llm: BaseChatModel | None = None
    llm: BaseChatModel | None = None


class StreamExecutor(StreamDispatcherMixin, StreamRecoveryMixin):
    """Agent 流式执行引擎。

    封装 astream 的完整生命周期:
    - Context overflow 自动恢复 (最多 2 次)
    - LLM failover (主模型失败时切换备用模型)
    - Steering 注入 (外部在运行时注入消息触发新轮次)
    - Transient retry (瞬态错误抖动重试)
    - 事件分发到 output_queue
    """

    def __init__(
        self,
        ctx: StreamContext,
        fallback_llm: BaseChatModel | None,
        safety_fallback_llm: BaseChatModel | None,
        rebuild_agent_fn: object,
        failover_used: bool = False,
    ) -> None:
        self._ctx = ctx
        self._fallback_llm = fallback_llm
        self._safety_fallback_llm = safety_fallback_llm
        self._rebuild_agent_fn = rebuild_agent_fn
        self.failover_used = failover_used
        self._escalation_used = False
        self.streaming_final_answer = False
        self._tool_truncation_retries = 0
        self._compactor = StreamCompactor(ctx.output_queue)
        self._reasoning_scrubber = ReasoningScrubber()
        self._pseudonym_restorer = None

        from .escalation_scrubber import EscalationScrubber

        self._escalation_scrubber = EscalationScrubber(
            enabled=ctx.escalation_target_llm is not None,
        )
        self._slice_tool_call_ids: list[str] = []

    async def _check_and_emit_trace_slice(self, force_flush: bool = False) -> None:
        """Check if slice length reaches threshold or force_flush, and emit TRACE_SLICE_READY."""
        if not self._slice_tool_call_ids:
            return

        if force_flush or len(self._slice_tool_call_ids) >= 15:
            from myrm_agent_harness.agent.hooks.executor import fire_hook
            from myrm_agent_harness.agent.hooks.types import HookEvent

            await fire_hook(
                HookEvent.TRACE_SLICE_READY,
                {
                    "session_id": self._ctx.message_id,
                    "tool_call_ids": list(self._slice_tool_call_ids),
                    "agent_id": self._ctx.merged_context.get("agent_id"),
                    "agent_type": self._ctx.merged_context.get("agent_type"),
                },
            )
            # Clear slice tracking after emitting
            self._slice_tool_call_ids.clear()

    async def execute(self) -> None:
        """主执行循环。所有事件通过 ctx.output_queue 传递。"""
        from myrm_agent_harness.agent.hooks.executor import fire_hook
        from myrm_agent_harness.agent.hooks.types import HookEvent

        ctx = self._ctx
        overflow_retries = 0
        transient_retries = 0
        length_continue_retries = 0
        empty_response_retries = 0
        thinking_sig_attempted = False
        image_shrink_attempted = False
        media_rejected_attempted = False

        is_resume_mode = isinstance(ctx.agent_input, Command)

        await fire_hook(
            HookEvent.SESSION_START,
            {"session_id": ctx.message_id, "is_resume": is_resume_mode},
        )

        try:
            while True:
                from myrm_agent_harness.utils.token_economics.tracker import (
                    get_token_tracker,
                )

                tracker = get_token_tracker()

                initial_tool_call_count = ctx.stats.tool_call_count

                if tracker and tracker.usage:
                    initial_total_tokens = tracker.usage.total_tokens
                    initial_cached_tokens = tracker.usage.cached_tokens
                else:
                    initial_total_tokens = ctx.stats.token_usage.total_tokens if ctx.stats.token_usage else 0
                    initial_cached_tokens = ctx.stats.token_usage.cached_tokens if ctx.stats.token_usage else 0

                import time

                initial_time = time.time()

                if isinstance(ctx.agent_input, Command):
                    final_agent_input: Any = ctx.agent_input
                    collected_messages: list[BaseMessage] = []
                else:
                    messages_dict = ctx.agent_input
                    messages = cast(list["BaseMessage"], messages_dict.get("messages", []))
                    final_agent_input = {**messages_dict, **ctx.merged_context}
                    collected_messages = list(messages)

                if ctx.steering_token:
                    ctx.steering_token.reset_turn()

                try:
                    async for chunk in ctx.agent.astream(
                        final_agent_input,
                        ctx.run_config,
                        context=ctx.merged_context,
                        stream_mode=["updates", "messages", "custom"],
                    ):
                        if ctx.cancel_token and ctx.cancel_token.is_cancelled:
                            ctx.stats.was_cancelled = True
                            logger.warning(
                                " Cancelled during execution: nodes=%d",
                                ctx.stats.node_execution_count,
                            )
                            await self._compactor.put(
                                {
                                    "type": AgentEventType.CANCELLED.value,
                                    "data": f"Cancelled after {ctx.stats.node_execution_count} nodes",
                                    "messageId": ctx.message_id,
                                }
                            )
                            break

                        await self._dispatch_chunk(chunk, ctx, collected_messages)

                except Exception as astream_exc:
                    iteration_limit_hit = await self._handle_iteration_limit(astream_exc, collected_messages)
                    if iteration_limit_hit:
                        if ctx.goal_provider is None:
                            break
                        logger.info(" Iteration limit in goal mode — falling through to goal continuation")
                    else:
                        if await self._handle_thinking_signature(astream_exc, thinking_sig_attempted):
                            thinking_sig_attempted = True
                            continue

                        if await self._handle_image_shrink(astream_exc, image_shrink_attempted):
                            image_shrink_attempted = True
                            continue

                        if await self._handle_media_rejected(astream_exc, media_rejected_attempted):
                            media_rejected_attempted = True
                            continue

                        if await self._handle_long_context_tier(astream_exc):
                            overflow_retries += 1
                            continue

                        if await self._handle_overflow(astream_exc, overflow_retries):
                            overflow_retries += 1
                            continue

                        if await self._handle_failover(astream_exc):
                            continue

                        if await self._handle_transient_retry(astream_exc, transient_retries):
                            transient_retries += 1
                            continue

                        raise

                if await self._handle_subagent_notifications(collected_messages):
                    continue

                if await self._handle_teammate_messages(collected_messages):
                    continue

                if await self._handle_steering(collected_messages):
                    continue

                if await self._handle_escalation(collected_messages):
                    continue

                if await self._handle_length_truncation(collected_messages, length_continue_retries):
                    length_continue_retries += 1
                    continue

                if await self._handle_empty_response(collected_messages, empty_response_retries):
                    empty_response_retries += 1
                    continue

                from myrm_agent_harness.utils.token_economics.tracker import (
                    get_token_tracker,
                )

                tracker = get_token_tracker()

                tools_called_this_turn = ctx.stats.tool_call_count > initial_tool_call_count

                if tracker and tracker.usage:
                    current_total = tracker.usage.total_tokens
                    current_cached = tracker.usage.cached_tokens
                else:
                    current_total = ctx.stats.token_usage.total_tokens if ctx.stats.token_usage else 0
                    current_cached = ctx.stats.token_usage.cached_tokens if ctx.stats.token_usage else 0

                net_tokens_this_turn = (current_total - initial_total_tokens) - (current_cached - initial_cached_tokens)
                time_this_turn_seconds = int(time.time() - initial_time)

                # Check if we should emit trace slice based on call threshold
                await self._check_and_emit_trace_slice(force_flush=False)

                logger.debug(
                    " _handle_goal_continuation checks: goal_provider=%s, net_tokens_this_turn=%d, session_id=%s",
                    ctx.goal_provider,
                    net_tokens_this_turn,
                    ctx.merged_context.get("chat_id", "none"),
                )

                if await self._handle_goal_continuation(
                    collected_messages,
                    tools_called_this_turn=tools_called_this_turn,
                    net_tokens_this_turn=net_tokens_this_turn,
                    time_this_turn_seconds=time_this_turn_seconds,
                ):
                    reset_loop_guard(
                        is_resume=True,
                        graph_recursion_limit=ctx.run_config.get("recursion_limit", 100),
                    )
                    continue

                break

        except Exception as e:
            await self._emit_fatal_error(e)

        finally:
            from myrm_agent_harness.agent.streaming.stream_recovery_truncation import (
                reset_ephemeral_max_output_tokens,
            )

            reset_ephemeral_max_output_tokens()

            await self._check_and_emit_trace_slice(force_flush=True)

            await fire_hook(
                HookEvent.SESSION_END,
                {
                    "session_id": ctx.message_id,
                    "was_cancelled": ctx.stats.was_cancelled,
                    "error": ctx.stats.error_message or "",
                    "node_count": ctx.stats.node_execution_count,
                },
            )
            escalation_flushed = self._escalation_scrubber.flush()
            if escalation_flushed:
                for scrubbed_type, scrubbed_text in self._reasoning_scrubber.process(escalation_flushed):
                    if scrubbed_text:
                        restored = self._restore_pseudonyms(scrubbed_text)
                        await self._emit_event(
                            {
                                "type": scrubbed_type.value,
                                "data": restored,
                                "messageId": ctx.message_id,
                            },
                            ctx,
                        )
            for event_type, content in self._reasoning_scrubber.flush():
                if content:
                    restored = self._restore_pseudonyms(content)
                    await self._emit_event(
                        {
                            "type": event_type.value,
                            "data": restored,
                            "messageId": ctx.message_id,
                        },
                        ctx,
                    )
            if self._pseudonym_restorer is not None:
                flushed = self._pseudonym_restorer.flush()
                if flushed:
                    await self._emit_event(
                        {
                            "type": AgentEventType.MESSAGE.value,
                            "data": flushed,
                            "messageId": ctx.message_id,
                        },
                        ctx,
                    )
            await self._compactor.flush()
            await self._compactor.put(STREAM_DONE)

    async def _emit_fatal_error(self, exc: Exception) -> None:
        """Build standardized error event with diagnostics and raise MyrmLLMError."""
        ctx = self._ctx
        error_msg = str(exc)
        error_type = type(exc).__name__
        failover_reason = classify_failover_reason(exc)
        error_kind = classify_error(exc)
        ctx.stats.error_message = f"{error_type}: {error_msg}"
        logger.error(
            " Agent execution error [%s]: %s: %s",
            failover_reason.value,
            error_type,
            error_msg[:300],
            exc_info=True,
        )

        error_event: dict[str, object] = {
            "type": AgentEventType.ERROR.value,
            "error": error_msg,
            "error_type": error_type,
            "error_kind": error_kind.value,
            "failover_reason": failover_reason.value,
            "messageId": ctx.message_id,
        }

        if ctx.stats.compression_exhausted:
            error_event["compression_exhausted"] = True

        cooldown_ms = _extract_retry_after_ms(exc)
        if cooldown_ms:
            error_event["cooldown_remaining_ms"] = cooldown_ms

        try:
            from myrm_agent_harness.agent.errors.diagnostics import (
                ErrorContext,
                LLMErrorDiagnostic,
            )

            model_name = "unknown"
            base_url = None
            is_custom_endpoint = False

            if ctx.llm_info:
                model_name = ctx.llm_info.get("model_name") or "unknown"
                base_url = ctx.llm_info.get("base_url")
                is_custom_endpoint = base_url is not None

            context = ErrorContext(
                model_name=model_name,
                is_custom_endpoint=is_custom_endpoint,
                base_url=base_url,
            )

            locale = ctx.merged_context.get("locale", "en") if ctx.merged_context else "en"
            cooldown_remaining_ms = error_event.get("cooldown_remaining_ms")

            diagnostic = LLMErrorDiagnostic.diagnose(
                exc, context, locale=locale, cooldown_remaining_ms=cooldown_remaining_ms
            )

            error_event["diagnostic_result"] = {
                "error_type": diagnostic.error_type,
                "user_message": diagnostic.user_message,
                "resolution_steps": diagnostic.resolution_steps,
                "locale": diagnostic.locale,
            }
        except Exception as diag_err:
            logger.error("Diagnostic generation failed: %s", diag_err)

        await self._compactor.put(error_event)

        raise MyrmLLMError(
            error_code=failover_reason,
            default_msg=error_msg,
            context=(
                {"cooldown_remaining_ms": error_event.get("cooldown_remaining_ms")}
                if "cooldown_remaining_ms" in error_event
                else None
            ),
            original_exc=exc,
            diagnostic_result=error_event.get("diagnostic_result"),
        ) from exc
