"""流式执行引擎 — 事件分发 Mixin

[INPUT]
- agent.streaming.event_handlers::process_messages_chunk, process_updates_chunk (POS: 事件处理器)
- agent.streaming.artifact_events::collect_inline_artifacts, process_realtime_content_events (POS: Artifact 事件处理器)
- agent.streaming.escalation_scrubber::EscalationScrubber (POS: 流式层升级标记检测)

[OUTPUT]
- StreamDispatcherMixin: dispatches events and forwards structured agent_status fields.

[POS]
StreamDispatcherMixin dispatches astream chunks to the output_queue and preserves GUI-safe status payload fields.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from myrm_agent_harness.agent.context_management.infra.cache_metrics_collector import (
    get_pending_cache_break_event,
)
from myrm_agent_harness.agent.security.guards.privacy_tracker import (
    get_pending_privacy_event,
    get_pending_route_event,
)
from myrm_agent_harness.agent.streaming.types import AgentEventType, AgentStreamEvent
from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.token_economics.tracker import get_pending_token_events

if TYPE_CHECKING:
    from myrm_agent_harness.agent.security.detection.pseudonymizer import PseudonymRestorer as _PseudonymRestorer

from .artifact_events import collect_inline_artifacts, process_realtime_content_events
from .event_handlers import process_messages_chunk, process_updates_chunk

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage

    from myrm_agent_harness.agent.streaming.escalation_scrubber import EscalationScrubber
    from myrm_agent_harness.agent.streaming.reasoning_scrubber import ReasoningScrubber
    from myrm_agent_harness.agent.streaming.stream_compactor import StreamCompactor
    from myrm_agent_harness.agent.streaming.stream_executor import StreamContext

logger = get_agent_logger(__name__)


class StreamDispatcherMixin:
    """事件分发策略集合。由 StreamExecutor 通过多继承使用。

    通过 self 访问 StreamExecutor 的属性:
    _ctx, _compactor, streaming_final_answer
    """

    _ctx: StreamContext
    _compactor: StreamCompactor
    _reasoning_scrubber: ReasoningScrubber
    _escalation_scrubber: EscalationScrubber
    streaming_final_answer: bool
    _pseudonym_restorer: _PseudonymRestorer | None
    _slice_tool_call_ids: list[str]

    async def _dispatch_chunk(
        self,
        chunk: tuple[str, object],
        ctx: StreamContext,
        collected_messages: list[BaseMessage],
    ) -> None:
        """分发一个 astream chunk 到 output_queue。"""
        if isinstance(chunk, AgentStreamEvent):
            await self._emit_event(chunk, ctx)
            return

        stream_mode_name, data = chunk
        if isinstance(data, AgentStreamEvent):
            await self._emit_event(data, ctx)
            return

        if stream_mode_name == "updates":
            await self._dispatch_updates(data, ctx, collected_messages)
        elif stream_mode_name == "messages":
            await self._dispatch_messages(data, ctx)
        elif stream_mode_name == "custom":
            await self._dispatch_custom(data, ctx)

    async def _dispatch_updates(
        self,
        data: object,
        ctx: StreamContext,
        collected_messages: list[BaseMessage],
    ) -> None:
        """Process 'updates' stream mode chunks."""
        data_dict = cast("dict[str, dict[str, object]]", data)
        if isinstance(data_dict, dict) and "__interrupt__" in data_dict:
            interrupts = data_dict["__interrupt__"]
            if interrupts and isinstance(interrupts, tuple):
                interrupt_obj = interrupts[0]
                interrupt_val = getattr(interrupt_obj, "value", None)
                if isinstance(interrupt_val, dict):
                    interrupt_type = interrupt_val.get("type")
                    action_type = interrupt_val.get("action_type")
                    if interrupt_type == "ask_question":
                        logger.warning(" Agent execution suspended for clarification")
                        await self._emit_event(
                            {
                                "type": AgentEventType.CLARIFICATION_REQUIRED.value,
                                "data": interrupt_val,
                                "messageId": ctx.message_id,
                            },
                            ctx,
                        )
                    elif action_type == "swarm_fission":
                        logger.warning(" Agent execution yielded for Swarm Fission")
                        await self._emit_event(
                            {
                                "type": "swarm_fission",
                                "data": interrupt_val,
                                "messageId": ctx.message_id,
                            },
                            ctx,
                        )
                    else:
                        logger.warning(" Agent execution suspended for approval")
                        await self._emit_event(
                            {
                                "type": AgentEventType.APPROVAL_REQUIRED.value,
                                "data": interrupt_val,
                                "messageId": ctx.message_id,
                            },
                            ctx,
                        )
            return

        async for event in process_updates_chunk(
            data_dict,
            ctx.stats,
            ctx.message_id,
            collected_messages=collected_messages,
            source_tracker=ctx.source_tracker,
        ):
            if isinstance(event, dict) and event.get("type") == AgentEventType.TASKS_STEPS.value:
                tool_call_id = event.get("tool_call_id")
                if tool_call_id and hasattr(self, "_slice_tool_call_ids"):
                    self._slice_tool_call_ids.append(str(tool_call_id))
            await self._emit_event(event, ctx)
        async for event in process_realtime_content_events(ctx.message_id):
            await self._emit_event(event, ctx)
        async for event in collect_inline_artifacts(ctx.message_id):
            await self._emit_event(event, ctx)

    async def _dispatch_messages(self, data: object, ctx: StreamContext) -> None:
        """Process 'messages' stream mode chunks."""
        for event, is_tool_start in process_messages_chunk(
            cast("tuple[object, object]", data), ctx.stats, ctx.message_id
        ):
            if not is_tool_start and not self.streaming_final_answer:
                self.streaming_final_answer = True
                logger.info(" 开始流式输出最终答案...")

            if isinstance(event, dict) and event.get("type") == AgentEventType.MESSAGE.value:
                content = event.get("data", "")
                if isinstance(content, str):
                    forwarded = self._escalation_scrubber.process(content)
                    if forwarded is None:
                        continue
                    for scrubbed_type, scrubbed_text in self._reasoning_scrubber.process(forwarded):
                        if scrubbed_text:
                            restored_text = self._restore_pseudonyms(scrubbed_text)
                            event_copy = dict(event)
                            event_copy["type"] = (
                                scrubbed_type.value if hasattr(scrubbed_type, "value") else str(scrubbed_type)
                            )
                            event_copy["data"] = restored_text
                            await self._emit_event(event_copy, ctx)
                else:
                    await self._emit_event(event, ctx)
            else:
                await self._emit_event(event, ctx)

        for token_event in get_pending_token_events():
            await self._emit_event(
                {
                    "type": AgentEventType.TOKEN_USAGE.value,
                    "data": token_event,
                    "messageId": ctx.message_id,
                },
                ctx,
            )

        privacy_event = get_pending_privacy_event()
        if privacy_event is not None:
            await self._emit_event(
                {
                    "type": AgentEventType.PRIVACY_LEVEL.value,
                    "data": privacy_event,
                    "messageId": ctx.message_id,
                },
                ctx,
            )

        route_event = get_pending_route_event()
        if route_event is not None:
            await self._emit_event(
                {
                    "type": AgentEventType.PRIVACY_ROUTE.value,
                    "data": route_event,
                    "messageId": ctx.message_id,
                },
                ctx,
            )

        cache_break = get_pending_cache_break_event()
        if cache_break is not None:
            reasons = cache_break.get("reasons", [])
            reason_text = ", ".join(str(r) for r in reasons) if isinstance(reasons, list) else str(reasons)
            raw_actions = cache_break.get("suggested_actions", [])
            actions_text = (
                ", ".join(str(a) for a in raw_actions) if isinstance(raw_actions, list) and raw_actions else ""
            )
            await self._emit_event(
                {
                    "type": AgentEventType.STATUS.value,
                    "step_key": "cache_break",
                    "data": {
                        "step_key": "cache_break",
                        "reason": reason_text,
                        "raw_reasons": reasons,
                        "suggested_actions": actions_text,
                        "token_drop": cache_break.get("token_drop", 0),
                        "prev_cache_read": cache_break.get("prev_cache_read", 0),
                        "curr_cache_read": cache_break.get("curr_cache_read", 0),
                    },
                    "messageId": ctx.message_id,
                },
                ctx,
            )

    async def _dispatch_custom(self, data: object, ctx: StreamContext) -> None:
        """Process 'custom' stream mode chunks."""
        logger.info(" RECEIVED CUSTOM EVENT: %s", data)
        if not isinstance(data, dict):
            return

        event_name = data.get("name", "")
        if event_name == "tool_stdout_chunk":
            event_data = data.get("data", {})
            chunk_text = event_data.get("chunk", "") if isinstance(event_data, dict) else ""
            if chunk_text:
                await self._emit_event(
                    {
                        "type": AgentEventType.TOOL_STDOUT_CHUNK.value,
                        "data": chunk_text,
                        "messageId": ctx.message_id,
                    },
                    ctx,
                )

        elif event_name == "tasks_steps":
            event_data = data.get("data", {})
            if isinstance(event_data, dict):
                event_dict: dict[str, object] = {
                    "type": AgentEventType.TASKS_STEPS.value,
                    "messageId": ctx.message_id,
                }
                event_dict.update(event_data)
                await self._emit_event(event_dict, ctx)

        elif event_name == "agent_status":
            event_data = data.get("data", {})
            event_dict_2: dict[str, object] = {
                "type": AgentEventType.STATUS.value,
                "data": event_data,
                "messageId": ctx.message_id,
            }
            if isinstance(event_data, dict):
                for field in (
                    "step_key",
                    "tokens_saved",
                    "stripped_count",
                    "attempt",
                    "tool_name",
                    "status",
                    "items",
                    "metadata",
                    "error_kind",
                    "fallback_model",
                ):
                    if field in event_data:
                        event_dict_2[field] = event_data[field]

            await self._emit_event(event_dict_2, ctx)

        elif event_name == "ptc_notify":
            # Real-time progress notifications emitted by PTC scripts via
            # ``tools.notify``. Forwarded as a dedicated event so the
            # frontend can surface them as inline activity cards / progress
            # bars instead of collapsing into the generic STATUS channel.
            event_data = data.get("data", {})
            event_dict_3: dict[str, object] = {
                "type": AgentEventType.PTC_NOTIFY.value,
                "data": event_data,
                "messageId": ctx.message_id,
            }
            if isinstance(event_data, dict):
                for field in (
                    "level",
                    "message",
                    "session_id",
                    "trace_id",
                    "progress",
                    "step_index",
                    "total_steps",
                    "category",
                ):
                    if field in event_data:
                        event_dict_3[field] = event_data[field]
            await self._emit_event(event_dict_3, ctx)

    def _restore_pseudonyms(self, text: str) -> str:
        """Restore pseudonymized placeholders in streamed text chunks.

        Lazily initializes the restorer on first call from the session
        PseudonymStore.  Returns text unchanged if pseudonymization is
        not active.
        """
        if not hasattr(self, "_pseudonym_restorer") or self._pseudonym_restorer is None:
            from myrm_agent_harness.agent.middlewares._session_context import get_pseudonym_store

            store = get_pseudonym_store()
            if store is None:
                return text
            from myrm_agent_harness.agent.security.detection.pseudonymizer import PseudonymRestorer

            self._pseudonym_restorer = PseudonymRestorer(store)

        return self._pseudonym_restorer.process(text)

    async def _emit_event(self, event: dict[str, object] | AgentStreamEvent, ctx: StreamContext) -> None:
        """Put event to output_queue via compactor and optionally log to event journal."""
        if isinstance(event, dict):
            event = AgentStreamEvent.from_dict(event)

        await self._compactor.put(event)

        if ctx.event_logger is not None:
            event_type = event.type.value if hasattr(event.type, "value") else str(event.type)
            event_data = event.to_dict()
            event_data.pop("type", None)
            event_data.pop("messageId", None)
            # Skip tool events without tool_name — those are frontend-only SSE signals,
            # not actionable analytics data. ToolCallBroadcaster handles the real log.
            if event_type.startswith("tool_") and "tool_name" not in event_data:
                return
            await ctx.event_logger.log(event_type, event_data)
