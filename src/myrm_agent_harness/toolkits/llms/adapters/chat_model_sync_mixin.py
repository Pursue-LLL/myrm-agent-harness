"""ChatLiteLLM synchronous generation and streaming mixin.

[INPUT]
- adapters.chat_model_exceptions (POS: EmptyChoicesError / EmptyStreamError)
- adapters.stream_aggregator / adapters.streaming (POS: stream aggregation)
- utils.token_economics (POS: streaming usage recording — lazy import)

[OUTPUT]
- ChatLiteLLMSyncMixin: _generate, _stream, empty-response retry

[POS]
Synchronous LLM generation and streaming path for ChatLiteLLM, including empty-response retry.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from typing import Any

from langchain_core.language_models.chat_models import generate_from_stream
from langchain_core.messages import (
    AIMessageChunk,
    BaseMessage,
    BaseMessageChunk,
    FunctionMessageChunk,
    HumanMessageChunk,
    SystemMessageChunk,
    ToolCallChunk,
)
from langchain_core.outputs import ChatGenerationChunk, ChatResult

from myrm_agent_harness.toolkits.llms.adapters.chat_model_exceptions import (
    EmptyChoicesError,
    EmptyStreamError,
)
from myrm_agent_harness.toolkits.llms.adapters.stream_aggregator import (
    StreamAggregator,
    XmlStreamBuffer,
    finalize_stream,
)
from myrm_agent_harness.toolkits.llms.adapters.streaming import build_tool_call_chunks, normalize_usage

logger = logging.getLogger(__name__)


class ChatLiteLLMSyncMixin:
    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        should_stream = kwargs.pop("streaming", self.streaming)
        if should_stream:
            stream_iter = self._stream(messages, stop=stop, run_manager=run_manager, **kwargs)
            return generate_from_stream(stream_iter)

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

        import time

        max_attempts = self.empty_retry_max_attempts if self.empty_retry_enabled else 1
        last_error: Exception | None = None

        for attempt in range(max_attempts):
            try:
                response = self.client.completion(messages=message_dicts, **params)
                response = self._convert_response_to_dict(response)
                result = self._create_chat_result(response, available_tools, tool_schemas)

                # Update metrics: success after retry
                if attempt > 0:
                    self._retry_metrics.sync_success_after_retry += 1

                return result

            except EmptyChoicesError as e:
                last_error = e
                self._retry_metrics.sync_retry_count += 1

                if attempt < max_attempts - 1:
                    logger.warning(f" Empty choices (attempt {attempt + 1}), retrying...")
                    delay_ms = self.empty_retry_delay * 1000
                    self._retry_metrics.total_retry_delay_ms += delay_ms
                    time.sleep(self.empty_retry_delay)
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

                model_name = self.model_name or self.model
                logger.error(f" LiteLLM call failed: {type(e).__name__} - {e!s} (Model: {model_name})")
                raise

        if last_error:
            raise last_error
        raise RuntimeError("Unexpected error in _generate retry loop")

    def _process_chunk(
        self,
        chunk: Any,
        default_chunk_class: type[BaseMessageChunk],
        tool_call_id_map: dict[str, str] | None = None,
        *,
        emit_tool_call_chunks: bool = True,
    ) -> tuple[ChatGenerationChunk | None, type[BaseMessageChunk]]:
        """Process a single streaming response chunk into a ChatGenerationChunk."""
        if not isinstance(chunk, dict):
            try:
                chunk = chunk.model_dump()
            except Exception:
                return None, default_chunk_class

        if not chunk or len(chunk.get("choices", [])) == 0:
            return None, default_chunk_class

        delta = chunk["choices"][0]["delta"]
        role = delta.get("role")
        content = delta.get("content") or ""

        # Some models (e.g. GLM) put the answer in reasoning_content instead of content
        reasoning_content = delta.get("reasoning_content") or ""
        additional_kwargs: dict[str, str] = {}
        if reasoning_content:
            additional_kwargs["reasoning_content"] = reasoning_content

        # Use keyword argument content= since BaseMessageChunk rejects positional args
        msg_chunk: BaseMessageChunk
        if role == "user" or default_chunk_class == HumanMessageChunk:
            msg_chunk = HumanMessageChunk(content=content)
        elif role == "assistant" or default_chunk_class == AIMessageChunk:
            tool_call_chunks: list[ToolCallChunk] = []
            raw_tool_calls = delta.get("tool_calls")
            if emit_tool_call_chunks:
                tool_call_chunks = build_tool_call_chunks(raw_tool_calls, tool_call_id_map)
            msg_chunk = AIMessageChunk(
                content=content,
                tool_call_chunks=tool_call_chunks,
                additional_kwargs=additional_kwargs if additional_kwargs else {},
            )
        elif role == "system" or default_chunk_class == SystemMessageChunk:
            msg_chunk = SystemMessageChunk(content=content)
        elif role == "function" or default_chunk_class == FunctionMessageChunk:
            function_call = delta.get("function_call")
            func_args = function_call.get("arguments", "") if function_call else ""
            func_name = function_call.get("name", "") if function_call else ""
            msg_chunk = FunctionMessageChunk(content=func_args, name=func_name)
        else:
            # Handle different message chunk types that may require additional parameters
            if default_chunk_class == AIMessageChunk:
                msg_chunk = AIMessageChunk(
                    content=content,
                    additional_kwargs=additional_kwargs if additional_kwargs else {},
                )
            elif default_chunk_class == HumanMessageChunk:
                msg_chunk = HumanMessageChunk(content=content)
            elif default_chunk_class == SystemMessageChunk:
                msg_chunk = SystemMessageChunk(content=content)
            elif default_chunk_class == FunctionMessageChunk:
                msg_chunk = FunctionMessageChunk(content=content, name="")
            else:
                # Fallback: assume it's a standard message chunk that only needs content and type
                msg_chunk = default_chunk_class(content=content, type=default_chunk_class.__name__)

        return ChatGenerationChunk(message=msg_chunk), msg_chunk.__class__

    def _record_stream_usage(
        self,
        usage: Any,
        *,
        model_name: str = "",
        duration_ms: float | None = None,
        ttft_ms: float | None = None,
        finish_reason: str = "",
    ) -> None:
        """Record token usage, cost, and latency for streaming responses.

        In streaming mode LiteLLM callbacks are skipped, so we manually record
        usage, compute cost via token counts, and append to the audit ledger.

        Args:
            usage: LiteLLM usage object from the final stream chunk
            model_name: Model identifier for per-model attribution
            duration_ms: Total stream duration (first request to last chunk)
            ttft_ms: Time to first token (first request to first content chunk)
            finish_reason: Model's finish reason (stop, tool_calls, max_tokens, etc.)
        """
        from myrm_agent_harness.utils.token_economics.cost_engine import (
            compute_cost_by_tokens,
        )
        from myrm_agent_harness.utils.token_economics.tracker import (
            append_to_ledger,
            record_token_usage,
        )

        if not usage:
            logger.warning("[TOKEN_DEBUG] _record_stream_usage called with empty usage")
            return

        from myrm_agent_harness.utils.token_economics.tracker import _current_tracker
        tracker_val = _current_tracker.get()
        logger.warning(
            "[TOKEN_DEBUG] _record_stream_usage: usage=%s, tracker=%s",
            type(usage).__name__, "SET" if tracker_val else "NONE"
        )

        usage_dict = normalize_usage(usage)
        resolved_model = model_name or None

        prompt_tokens = int(usage_dict.get("prompt_tokens", 0) or 0)
        completion_tokens = int(usage_dict.get("completion_tokens", 0) or 0)
        cost_result = compute_cost_by_tokens(resolved_model, prompt_tokens, completion_tokens)

        record_token_usage(
            usage_dict,
            model_name=resolved_model,
            duration_ms=duration_ms,
            ttft_ms=ttft_ms,
            cost_usd=cost_result.usd,
            cost_status=cost_result.status,
        )
        append_to_ledger(
            usage_dict, resolved_model, duration_ms, cost_result.usd,
            ttft_ms=ttft_ms, finish_reason=finish_reason,
        )

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        import time

        available_tools, tool_schemas = self._extract_tool_context_from_kwargs(kwargs)
        message_dicts, params = self._create_message_dicts(messages, stop)
        params = {
            **params,
            **kwargs,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        self._inject_allowed_params(params)
        self._apply_ephemeral_output_override(params)

        max_attempts = self.empty_retry_max_attempts if self.empty_retry_enabled else 1
        last_error: Exception | None = None

        for attempt in range(max_attempts):
            try:
                agg = StreamAggregator(AIMessageChunk)
                xml_content_buffer = XmlStreamBuffer()
                xml_reasoning_buffer = XmlStreamBuffer()

                for chunk in self.client.completion(messages=message_dicts, **params):
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
                        safe_reasoning = xml_reasoning_buffer.process(str(raw_reasoning)) if raw_reasoning else ""

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
                                run_manager.on_llm_new_token(safe_content, chunk=safe_cg_chunk)
                            yield safe_cg_chunk

                if agg.is_empty:
                    raise EmptyStreamError(f"Stream produced no chunks. Model: {self.model_name or self.model}")

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
                        run_manager.on_llm_new_token(flushed_content, chunk=safe_cg_chunk)
                    yield safe_cg_chunk

                result = finalize_stream(
                    agg,
                    tool_schemas,
                    self.model_name or self.model,
                    is_async=False,
                    record_usage_fn=self._record_stream_usage,
                    available_tools=available_tools,
                )
                if result.final_tool_chunk:
                    if run_manager:
                        run_manager.on_llm_new_token("", chunk=result.final_tool_chunk)
                    yield result.final_tool_chunk
                else:
                    # Yield an empty chunk so LangGraph's messages stream triggers
                    # one more dispatch cycle, allowing get_pending_token_events()
                    # to capture the usage recorded by finalize_stream above.
                    sentinel = ChatGenerationChunk(message=AIMessageChunk(content=""))
                    yield sentinel

                if attempt > 0:
                    self._retry_metrics.stream_success_after_retry += 1
                break

            except EmptyStreamError as e:
                last_error = e
                self._retry_metrics.stream_retry_count += 1
                if attempt < max_attempts - 1:
                    logger.warning(f" Empty stream (attempt {attempt + 1}), retrying...")
                    self._retry_metrics.total_retry_delay_ms += self.empty_retry_delay * 1000
                    time.sleep(self.empty_retry_delay)
                else:
                    logger.error(f" Empty stream after {max_attempts} attempts.")

        if last_error:
            raise last_error

