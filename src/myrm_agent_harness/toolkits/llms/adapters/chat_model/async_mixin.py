"""ChatLiteLLM asynchronous generation and streaming mixin.

[INPUT]
- adapters.chat_model.exceptions (POS: EmptyChoicesError / EmptyStreamError / StreamStallTimeoutError)
- adapters.concurrency (POS: per-model semaphores)
- adapters.stream_aggregator / adapters.streaming (POS: stream aggregation)
- utils.token_economics (POS: usage recording for streaming + non-streaming — lazy import)

[OUTPUT]
- ChatLiteLLMAsyncMixin: _agenerate, _astream, empty-response retry, stream stall detection

[POS]
Asynchronous LLM generation and streaming path for ChatLiteLLM with concurrency gate, stream stall
detection, and unified token-usage recording for both streaming and non-streaming calls.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING, Any

from langchain_core.language_models.chat_models import agenerate_from_stream
from langchain_core.messages import (
    AIMessageChunk,
    BaseMessage,
    BaseMessageChunk,
)
from langchain_core.outputs import ChatGenerationChunk, ChatResult

from myrm_agent_harness.toolkits.llms.adapters.chat_model.exceptions import (
    EmptyChoicesError,
    EmptyStreamError,
    StreamStallTimeoutError,
)
from myrm_agent_harness.toolkits.llms.adapters.concurrency import (
    get_semaphores as _get_semaphores,
)
from myrm_agent_harness.toolkits.llms.adapters.metrics import EmptyRetryMetrics
from myrm_agent_harness.toolkits.llms.adapters.stream_aggregator import (
    StreamAggregator,
    XmlStreamBuffer,
    finalize_stream,
)
from myrm_agent_harness.toolkits.llms.adapters.wire.anthropic_params import (
    apply_anthropic_messages_params,
)
from myrm_agent_harness.toolkits.llms.adapters.wire.invocation import (
    invoke_responses_async,
    stream_responses_async,
)

logger = logging.getLogger(__name__)


def _dump_payload_pairing(message_dicts: list[dict[str, Any]]) -> None:
    """Debug aid: log tool_call pairing health for a failed request payload.

    Gated behind MYRM_DEBUG_DUMP_LLM_PAYLOAD=1 so production traces stay clean.
    """
    pending: list[tuple[int, str]] = []
    for i, m in enumerate(message_dicts):
        role = m.get("role")
        if role == "assistant":
            for tc in m.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                tid = tc.get("id")
                fn = tc.get("function")
                if not tid and isinstance(fn, dict):
                    tid = fn.get("id")
                if tid:
                    pending.append((i, tid))
        elif role == "tool":
            tid = m.get("tool_call_id")
            if tid:
                pending = [(idx, p) for idx, p in pending if p != tid]

    def _tc_ids(m: dict[str, Any]) -> list[object]:
        raw = m.get("tool_calls") or []
        return [tc.get("id") for tc in raw if isinstance(tc, dict)]

    lines = [
        f"  [{i}] role={m.get('role')} tool_call_id={m.get('tool_call_id')!r} "
        f"tool_calls={_tc_ids(m)} content={(str(m.get('content'))[:70])!r}"
        for i, m in enumerate(message_dicts)
    ]
    logger.error(
        " LLM_PAYLOAD_DUMP total=%d dangling=%s (last 35 msgs):\n%s",
        len(message_dicts),
        pending,
        "\n".join(lines[-35:]),
    )


class ChatLiteLLMAsyncMixin:
    if TYPE_CHECKING:
        # Attributes and sibling-mixin methods defined on the ChatLiteLLM aggregate
        # root; declared here so mypy understands the composition-mixin pattern.
        client: Any
        model: str
        model_name: str | None
        streaming: bool
        custom_llm_provider: str | None
        empty_retry_enabled: bool
        empty_retry_max_attempts: int
        empty_retry_delay: float
        first_event_timeout: float
        inter_chunk_timeout: float
        _retry_metrics: EmptyRetryMetrics
        _create_chat_result: Callable[..., ChatResult]
        _convert_response_to_dict: Callable[..., dict[str, Any]]
        _extract_tool_context_from_kwargs: Callable[..., tuple[list[str] | None, dict[str, dict[str, Any]] | None]]
        _create_message_dicts: Callable[..., tuple[list[dict[str, Any]], dict[str, Any]]]
        _inject_allowed_params: Callable[..., None]
        _apply_ephemeral_output_override: Callable[..., None]
        _inject_prompt_routing_key: Callable[..., None]
        _process_chunk: Callable[..., tuple[ChatGenerationChunk | None, type[BaseMessageChunk]]]
        _record_usage: Callable[..., None]
        _record_non_stream_usage: Callable[..., None]

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        should_stream = kwargs.get("streaming", self.streaming)
        if should_stream:
            return await self._agenerate_inner(messages, stop, run_manager, **kwargs)

        import contextlib

        global_sem, model_sem = await _get_semaphores(self.model_name or self.model)

        # lock both semaphores (global then model)
        async with (
            global_sem or contextlib.nullcontext(),
            model_sem or contextlib.nullcontext(),
        ):
            return await self._agenerate_inner(messages, stop, run_manager, **kwargs)

    async def _agenerate_inner(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        should_stream = kwargs.pop("streaming", self.streaming)
        if should_stream:
            try:
                stream_iter = self._astream(messages=messages, stop=stop, run_manager=run_manager, **kwargs)
                return await agenerate_from_stream(stream_iter)
            except TypeError as e:
                if "'NoneType' object is not iterable" in str(e):
                    logger.warning(" LangChain agenerate_from_stream bug, falling back to non-streaming")
                    return await self._agenerate(messages, stop, run_manager, stream=False, **kwargs)
                raise
            except Exception:
                logger.error(f" LiteLLM streaming failed (Model: {self.model_name or self.model})")
                raise

        available_tools, tool_schemas = self._extract_tool_context_from_kwargs(kwargs)
        message_dicts, params = self._create_message_dicts(messages, stop)

        # Filter out internal LangChain parameters that shouldn't be passed to LiteLLM
        filtered_kwargs = {
            k: v
            for k, v in kwargs.items()
            if k
            not in (
                "ls_structured_output_format",
                "_json_mode_fallback",
                "_in_fallback",
            )
        }

        params = {**params, **filtered_kwargs}
        self._inject_allowed_params(params)
        self._apply_ephemeral_output_override(params)
        self._inject_prompt_routing_key(params)

        from myrm_agent_harness.infra.tracing import get_tracer
        from myrm_agent_harness.toolkits.llms.utils.logger import (
            log_llm_request,
            log_llm_response,
        )

        tracer = get_tracer("llm.call")
        model_name = self.model_name or self.model

        max_attempts = self.empty_retry_max_attempts if self.empty_retry_enabled else 1
        last_error: Exception | None = None
        for attempt in range(max_attempts):
            try:
                started = time.perf_counter()
                log_llm_request(model_name, message_dicts, params)

                with tracer.start_as_current_span("llm.call") as span:
                    # OpenInference standard attributes
                    span.set_attribute("llm.model_name", model_name)
                    span.set_attribute("llm.request.attempt", attempt + 1)

                    wire_protocol = getattr(self, "wire_protocol", "chat_completions")
                    if wire_protocol == "responses":
                        response = await invoke_responses_async(self.client, message_dicts, params)
                    else:
                        call_params = (
                            apply_anthropic_messages_params(params)
                            if wire_protocol == "anthropic_messages"
                            else params
                        )
                        response = await self.client.acreate(messages=message_dicts, **call_params)
                        response = self._convert_response_to_dict(response)

                    if usage := response.get("usage"):
                        span.set_attribute("llm.token_count.prompt", usage.get("prompt_tokens", 0))
                        span.set_attribute(
                            "llm.token_count.completion",
                            usage.get("completion_tokens", 0),
                        )
                        span.set_attribute("llm.token_count.total", usage.get("total_tokens", 0))

                log_llm_response(response)

                result = self._create_chat_result(response, available_tools, tool_schemas)

                duration_ms = (time.perf_counter() - started) * 1000
                self._record_non_stream_usage(
                    response,
                    model_name=model_name,
                    duration_ms=duration_ms,
                )

                # Update metrics: success after retry
                if attempt > 0:
                    self._retry_metrics.async_success_after_retry += 1

                return result

            except EmptyChoicesError as e:
                last_error = e
                self._retry_metrics.async_retry_count += 1

                if attempt < max_attempts - 1:
                    logger.warning(f" Empty choices (attempt {attempt + 1}), retrying...")
                    delay_ms = self.empty_retry_delay * 1000
                    self._retry_metrics.total_retry_delay_ms += delay_ms
                    await asyncio.sleep(self.empty_retry_delay)
                else:
                    logger.error(f" Empty choices after {max_attempts} attempts.")
            except Exception as e:
                from myrm_agent_harness.toolkits.llms.errors.classifier import (
                    is_context_overflow,
                    parse_available_output_tokens_from_error,
                )

                if is_context_overflow(e):
                    available = parse_available_output_tokens_from_error(e)
                    if available is not None and available >= 500 and attempt < max_attempts - 1:
                        safe_tokens = max(1, available - 64)
                        logger.warning(
                            f" Context overflow, injecting ephemeral max_tokens={safe_tokens} (attempt {attempt + 1})"
                        )
                        params["max_tokens"] = safe_tokens
                        continue
                    else:
                        logger.warning(
                            f" Context overflow (available={available}), fast-failing to trigger compression."
                        )
                        raise e

                logger.error(f" LiteLLM acreate failed (Model: {self.model_name or self.model}): {e!s}")
                raise

        if last_error:
            raise last_error
        raise RuntimeError("Unexpected error in _agenerate retry loop")

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        import contextlib

        global_sem, model_sem = await _get_semaphores(self.model_name or self.model)

        async with (
            global_sem or contextlib.nullcontext(),
            model_sem or contextlib.nullcontext(),
        ):
            async for chunk in self._astream_inner(messages, stop, run_manager, **kwargs):
                yield chunk

    async def _astream_inner(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:

        from myrm_agent_harness.infra.tracing import get_tracer

        tracer = get_tracer("llm.stream")
        model_name = self.model_name or self.model

        available_tools, tool_schemas = self._extract_tool_context_from_kwargs(kwargs)
        message_dicts, params = self._create_message_dicts(messages, stop)

        # Filter out internal LangChain parameters that shouldn't be passed to LiteLLM
        filtered_kwargs = {
            k: v
            for k, v in kwargs.items()
            if k
            not in (
                "ls_structured_output_format",
                "_json_mode_fallback",
                "_in_fallback",
            )
        }

        params = {
            **params,
            **filtered_kwargs,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        self._inject_allowed_params(params)
        self._apply_ephemeral_output_override(params)
        self._inject_prompt_routing_key(params)

        max_attempts = self.empty_retry_max_attempts if self.empty_retry_enabled else 1
        last_error: Exception | None = None

        for attempt in range(max_attempts):
            try:
                with tracer.start_as_current_span("llm.stream_connect") as llm_span:
                    llm_span.set_attribute("llm.model_name", model_name)
                    wire_protocol = getattr(self, "wire_protocol", "chat_completions")
                    if wire_protocol == "responses":
                        stream = stream_responses_async(self.client, message_dicts, params)
                    else:
                        call_params = (
                            apply_anthropic_messages_params(params)
                            if wire_protocol == "anthropic_messages"
                            else params
                        )
                        stream = await self.client.acreate(messages=message_dicts, **call_params)

                agg = StreamAggregator(AIMessageChunk)
                xml_content_buffer = XmlStreamBuffer()
                xml_reasoning_buffer = XmlStreamBuffer()

                stall_phase = "first_event"
                try:
                    loop = asyncio.get_running_loop()
                    async with asyncio.timeout(self.first_event_timeout) as stall_tm:
                        async for chunk in stream:
                            stall_tm.reschedule(loop.time() + self.inter_chunk_timeout)
                            if stall_phase == "first_event":
                                stall_phase = "inter_chunk"

                            chunk_dict = agg.ingest_raw_chunk(chunk)
                            if chunk_dict is None:
                                continue
                            agg.aggregate_tool_calls_from_dict(chunk_dict)

                            cg_chunk, new_class = self._process_chunk(
                                chunk_dict,
                                agg.default_chunk_class,
                                agg.tool_call_id_map,
                                emit_tool_call_chunks=False,
                            )
                            if cg_chunk:
                                agg.on_generation_chunk(cg_chunk, new_class)

                                # Filter content and reasoning_content through DSML buffer before yielding
                                raw_content = str(cg_chunk.message.content) if cg_chunk.message.content else ""
                                safe_content = xml_content_buffer.process(raw_content)

                                additional_kwargs = dict(getattr(cg_chunk.message, "additional_kwargs", {}))
                                raw_reasoning = additional_kwargs.get("reasoning_content", "")
                                safe_reasoning = (
                                    xml_reasoning_buffer.process(str(raw_reasoning)) if raw_reasoning else ""
                                )

                                if safe_content or safe_reasoning or getattr(cg_chunk.message, "tool_call_chunks", []):
                                    msg_dict = dict(cg_chunk.message)
                                    msg_dict.pop("type", None)
                                    msg_dict["content"] = safe_content
                                    if "additional_kwargs" in msg_dict:
                                        ak = dict(msg_dict["additional_kwargs"])
                                        if safe_reasoning:
                                            ak["reasoning_content"] = safe_reasoning
                                        elif "reasoning_content" in ak:
                                            del ak["reasoning_content"]
                                        msg_dict["additional_kwargs"] = ak

                                    safe_chunk = cg_chunk.message.__class__(**msg_dict)
                                    safe_cg_chunk = ChatGenerationChunk(message=safe_chunk)
                                    if run_manager:
                                        await run_manager.on_llm_new_token(safe_content, chunk=safe_cg_chunk)
                                    yield safe_cg_chunk
                except TimeoutError as exc:
                    timeout_val = self.first_event_timeout if stall_phase == "first_event" else self.inter_chunk_timeout
                    logger.warning(
                        " Stream stall detected (phase=%s, model=%s, timeout=%.0fs)",
                        stall_phase,
                        model_name,
                        timeout_val,
                    )
                    raise StreamStallTimeoutError(
                        provider=self.custom_llm_provider or "unknown",
                        model=model_name,
                        phase=stall_phase,
                        elapsed_s=timeout_val,
                    ) from exc

                logger.debug(f" Stream completed: total {agg.chunk_count} chunks")

                if agg.is_empty:
                    raise EmptyStreamError(f"Stream produced no chunks. Model: {model_name}")

                # Flush buffers at the end of the stream
                flushed_content = xml_content_buffer.flush()
                flushed_reasoning = xml_reasoning_buffer.flush()
                if flushed_content or flushed_reasoning:
                    msg_dict = {"content": flushed_content}
                    if flushed_reasoning:
                        msg_dict["additional_kwargs"] = {"reasoning_content": flushed_reasoning}
                    safe_chunk = agg.default_chunk_class(**msg_dict)
                    safe_cg_chunk = ChatGenerationChunk(message=safe_chunk)
                    if run_manager:
                        await run_manager.on_llm_new_token(flushed_content, chunk=safe_cg_chunk)
                    yield safe_cg_chunk

                result = finalize_stream(
                    agg,
                    tool_schemas,
                    model_name,
                    is_async=True,
                    record_usage_fn=self._record_usage,
                    available_tools=available_tools,
                )
                if result.final_tool_chunk:
                    if run_manager:
                        await run_manager.on_llm_new_token("", chunk=result.final_tool_chunk)
                    yield result.final_tool_chunk
                else:
                    # Yield an empty chunk so LangGraph's messages stream triggers
                    # one more dispatch cycle, allowing get_pending_token_events()
                    # to capture the usage recorded by finalize_stream above.
                    sentinel = ChatGenerationChunk(message=AIMessageChunk(content=""))
                    yield sentinel

                if attempt > 0:
                    self._retry_metrics.stream_success_after_retry += 1
                # Success path: clear a stale retry error so the loop-exit raise
                # below only fires when every attempt failed.
                last_error = None
                break

            except EmptyStreamError as e:
                last_error = e
                self._retry_metrics.stream_retry_count += 1
                if attempt < max_attempts - 1:
                    logger.warning(f" Empty stream (attempt {attempt + 1}), retrying...")
                    self._retry_metrics.total_retry_delay_ms += self.empty_retry_delay * 1000
                    await asyncio.sleep(self.empty_retry_delay)
                else:
                    logger.error(f" Empty stream after {max_attempts} attempts.")
            except StreamStallTimeoutError:
                raise
            except Exception as e:
                from myrm_agent_harness.toolkits.llms.adapters.gateway_normalizer import (
                    is_gateway_param_rejection,
                    sanitize_gateway_params_on_400,
                )
                from myrm_agent_harness.toolkits.llms.errors.classifier import (
                    is_context_overflow,
                    parse_available_output_tokens_from_error,
                )

                if is_gateway_param_rejection(e) and attempt < max_attempts - 1:
                    stripped = sanitize_gateway_params_on_400(params, e)
                    if stripped:
                        logger.warning(
                            f" Gateway streaming rejected params {stripped}, retrying without them (attempt {attempt + 1})"
                        )
                        continue

                if is_context_overflow(e):
                    available = parse_available_output_tokens_from_error(e)
                    if available is not None and available >= 500 and attempt < max_attempts - 1:
                        safe_tokens = max(1, available - 64)
                        logger.warning(
                            f" Context overflow, injecting ephemeral max_tokens={safe_tokens} (attempt {attempt + 1})"
                        )
                        params["max_tokens"] = safe_tokens
                        continue
                    else:
                        logger.warning(
                            f" Context overflow (available={available}), fast-failing to trigger compression."
                        )
                        raise e

                logger.error(f" LiteLLM streaming failed (Model: {model_name}): {e!s}")
                if os.environ.get("MYRM_DEBUG_DUMP_LLM_PAYLOAD", "") == "1":
                    _dump_payload_pairing(message_dicts)
                raise

        if last_error:
            raise last_error
