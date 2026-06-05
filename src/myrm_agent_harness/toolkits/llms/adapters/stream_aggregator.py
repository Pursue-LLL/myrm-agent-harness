"""Stream Aggregation

[INPUT]
- adapters.streaming (POS: streaming response processing)
- adapters.tool_recovery (POS: Tool call recovery module)
- adapters.safety_termination_detector (POS: Safety termination detector for truncated tool call suppression)
- utils.cost_engine::compute_cost_by_tokens (POS: token-count-based cost calculation for streaming mode)
- utils.token_tracker (POS: Token tracking API)

[OUTPUT]
- StreamAggregator: Mutable accumulator for stream chunks (content, tool calls, reasoning, timing)
- XmlStreamBuffer: State machine buffer for intercepting DSML tags across streaming chunks.
- finalize_stream(): Build aggregated response, record usage, yield final tool chunk

[POS]
Stream data aggregation module. Eliminates duplication between sync _stream and async
_astream_inner by encapsulating shared chunk aggregation, timing, tool call recovery,
usage recording, and log construction into reusable components.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from typing import Any

from langchain_core.messages import BaseMessageChunk
from langchain_core.outputs import ChatGenerationChunk

from myrm_agent_harness.toolkits.llms.adapters.safety_termination_detector import (
    detect_safety_termination,
    suppress_tool_calls_for_safety,
)
from myrm_agent_harness.toolkits.llms.adapters.streaming import (
    aggregate_tool_call_chunk,
    build_tool_call_chunks,
    extract_chunk_metadata,
    normalize_usage,
    parse_tool_calls_from_reasoning,
)
from myrm_agent_harness.toolkits.llms.adapters.tool_call_parsers import (
    clean_xml_tool_tags,
)
from myrm_agent_harness.toolkits.llms.adapters.tool_recovery import (
    build_final_tool_call_chunk,
)

logger = logging.getLogger(__name__)


class XmlStreamBuffer:
    """State machine buffer for intercepting DSML tags across streaming chunks.

    Prevents DSML tags (like <｜DSML｜tool_calls> or <｜｜DSML｜｜tool_calls>) from
    leaking into the yielded stream by buffering text when a potential tag is detected.
    """

    __slots__ = (
        "buffer",
        "end_tag_pattern",
        "is_swallowing",
        "prefix_pattern",
        "start_tag_pattern",
    )

    def __init__(self) -> None:
        self.buffer: str = ""
        self.is_swallowing: bool = False
        import re

        self.start_tag_pattern = re.compile(
            r"^(?:<[｜|]+DSML[｜|]+tool_calls>|<tool_call>|<invoke(?:\s+name=[\"'][^\"']*[\"'])?>)"
        )
        self.end_tag_pattern = re.compile(r"(?:</[｜|]+DSML[｜|]+tool_calls>|</tool_call>|</invoke>)")

    def _is_prefix_of_start_tag(self, s: str) -> bool:
        if not s.startswith("<"):
            return False
        if s == "<":
            return True

        clean_s = s.replace("｜", "").replace("|", "")
        if "<DSMLtool_calls>".startswith(clean_s):
            return True
        if "<DSMLinvoke".startswith(clean_s):
            return True

        if "<tool_call>".startswith(s):
            return True

        if "<invoke".startswith(s):
            return True

        import re

        return bool(re.match(r"^<invoke(?:\s+(?:n(?:a(?:m(?:e(?:=(?:[\"'][^\"']*[\"']?)?)?)?)?)?)?)?$", s))

    def process(self, text: str) -> str:
        if not text:
            return ""

        if self.is_swallowing:
            self.buffer += text
            match = self.end_tag_pattern.search(self.buffer)
            if match:
                end_pos = match.end()
                remaining = self.buffer[end_pos:]
                self.buffer = ""
                self.is_swallowing = False
                return self.process(remaining)
            return ""

        self.buffer += text
        pos = self.buffer.find("<")

        if pos == -1:
            res = self.buffer
            self.buffer = ""
            return res

        safe_text = self.buffer[:pos]
        potential_tag = self.buffer[pos:]

        match = self.start_tag_pattern.search(potential_tag)
        if match:
            self.is_swallowing = True
            self.buffer = potential_tag
            return safe_text + self.process("")

        if self._is_prefix_of_start_tag(potential_tag):
            self.buffer = potential_tag
            return safe_text

        self.buffer = potential_tag[1:]
        return safe_text + "<" + self.process("")

    def flush(self) -> str:
        res = self.buffer if not self.is_swallowing else ""
        self.buffer = ""
        self.is_swallowing = False
        return res


class StreamAggregator:
    """Mutable accumulator that collects stream chunks and produces an aggregated response."""

    __slots__ = (
        "chunk_count",
        "content",
        "default_chunk_class",
        "finish_reason",
        "first_token_time",
        "last_model",
        "last_usage",
        "reasoning",
        "stream_start",
        "tool_call_id_map",
        "tool_calls",
    )

    def __init__(self, default_chunk_class: type[BaseMessageChunk]) -> None:
        self.content: list[str] = []
        self.tool_calls: list[dict[str, Any]] = []
        self.reasoning: list[str] = []
        self.tool_call_id_map: dict[str, str] = {}
        self.last_model: str = ""
        self.finish_reason: str = ""
        self.last_usage: Any = None
        self.chunk_count: int = 0
        self.first_token_time: float | None = None
        self.stream_start: float = time.monotonic()
        self.default_chunk_class = default_chunk_class

    def ingest_raw_chunk(self, chunk: Any) -> dict[str, Any] | None:
        """Extract metadata from a raw chunk and return its dict form (or None to skip)."""
        self.chunk_count += 1
        chunk_usage, chunk_model, chunk_fr = extract_chunk_metadata(chunk)
        if chunk_usage:
            self.last_usage = chunk_usage
        if chunk_model:
            self.last_model = chunk_model
        if chunk_fr:
            self.finish_reason = chunk_fr

        if isinstance(chunk, dict):
            return chunk
        try:
            return chunk.model_dump()
        except Exception:
            return None

    def aggregate_tool_calls_from_dict(self, chunk_dict: dict[str, Any]) -> None:
        """Extract and aggregate tool call chunks from a chunk dict."""
        raw_tool_calls = chunk_dict.get("choices", [{}])[0].get("delta", {}).get("tool_calls")
        for tc_chunk in build_tool_call_chunks(raw_tool_calls, self.tool_call_id_map):
            aggregate_tool_call_chunk(tc_chunk, self.tool_calls)

    def on_generation_chunk(self, cg_chunk: ChatGenerationChunk, new_class: type[BaseMessageChunk]) -> None:
        """Update aggregator state after a ChatGenerationChunk is produced."""
        if self.first_token_time is None:
            self.first_token_time = time.monotonic()
        self.default_chunk_class = new_class

        if cg_chunk.message.content:
            self.content.append(str(cg_chunk.message.content))

        additional_kwargs = getattr(cg_chunk.message, "additional_kwargs", {})
        if additional_kwargs.get("reasoning_content"):
            self.reasoning.append(str(additional_kwargs["reasoning_content"]))

    @property
    def is_empty(self) -> bool:
        return self.chunk_count == 0 and self.last_usage is None and not self.finish_reason

    @property
    def duration_ms(self) -> float:
        return (time.monotonic() - self.stream_start) * 1000.0

    @property
    def ttft_ms(self) -> float | None:
        if self.first_token_time is None:
            return None
        return (self.first_token_time - self.stream_start) * 1000.0


class StreamFinalization:
    """Result of finalizing a stream: contains the final tool chunk and aggregated response."""

    __slots__ = ("aggregated_response", "final_tool_chunk")

    def __init__(
        self,
        final_tool_chunk: ChatGenerationChunk | None,
        aggregated_response: dict[str, Any],
    ) -> None:
        self.final_tool_chunk = final_tool_chunk
        self.aggregated_response = aggregated_response


def finalize_stream(
    agg: StreamAggregator,
    tool_schemas: Mapping[str, Mapping[str, Any]] | None,
    model_name: str,
    *,
    is_async: bool,
    record_usage_fn: Any,
    available_tools: list[str] | None = None,
) -> StreamFinalization:
    """Build aggregated response, record usage, and return finalization result.

    Args:
        agg: The stream aggregator with accumulated data
        tool_schemas: Tool schemas for recovery
        model_name: Resolved model name for attribution
        is_async: Whether this is an async stream (affects reasoning parser)
        record_usage_fn: Callable to record token usage/cost/latency
        available_tools: Tool names for hallucination filtering in streaming mode
    """
    from myrm_agent_harness.toolkits.llms.utils.logger import log_llm_response

    aggregated_message: dict[str, Any] = {
        "content": "".join(agg.content),
        "role": "assistant",
    }
    valid_tool_calls = [tc for tc in agg.tool_calls if tc["function"]["name"]] if agg.tool_calls else []

    if available_tools and valid_tool_calls:
        before_count = len(valid_tool_calls)
        valid_tool_calls = [tc for tc in valid_tool_calls if tc.get("function", {}).get("name") in available_tools]
        dropped = before_count - len(valid_tool_calls)
        if dropped:
            logger.warning(
                " Stream: filtered %d hallucinated tool call(s) not in available_tools",
                dropped,
            )

    resolved_model = agg.last_model or model_name

    record_usage_fn(
        agg.last_usage,
        model_name=resolved_model,
        duration_ms=agg.duration_ms,
        ttft_ms=agg.ttft_ms,
    )

    if agg.reasoning:
        aggregated_message["reasoning_content"] = "".join(agg.reasoning)

    parsed_tool_calls, _ = parse_tool_calls_from_reasoning(agg.reasoning, valid_tool_calls, is_async=is_async)

    if not parsed_tool_calls and not valid_tool_calls:
        from myrm_agent_harness.toolkits.llms.adapters.tool_call_parsers import (
            parse_tool_calls,
        )

        parsed_tool_calls = parse_tool_calls(aggregated_message)
        if parsed_tool_calls:
            logger.warning(f" Stream: parsed {len(parsed_tool_calls)} tool calls from content/reasoning_content")

            if agg.finish_reason == "stop":
                agg.finish_reason = "tool_calls"
                logger.warning(
                    " Stream: overrode finish_reason from 'stop' to 'tool_calls' due to parsed DSML/Inline tags"
                )

    if aggregated_message.get("content"):
        aggregated_message["content"] = clean_xml_tool_tags(aggregated_message["content"])

    if aggregated_message.get("reasoning_content"):
        aggregated_message["reasoning_content"] = clean_xml_tool_tags(aggregated_message["reasoning_content"])

    tool_call_source = parsed_tool_calls if parsed_tool_calls else valid_tool_calls
    final_tool_chunk, corrected_tool_calls, recovery_metadata = build_final_tool_call_chunk(
        tool_call_source, tool_schemas
    )
    if corrected_tool_calls:
        aggregated_message["tool_calls"] = corrected_tool_calls
    if recovery_metadata:
        aggregated_message["tool_call_recovery"] = [
            item
            for item in recovery_metadata
            if item["strategy"] != "standard_json" or item["degraded"] or not item["safe"]
        ]

    # Safety termination: suppress truncated tool_calls when provider stopped
    # generation for safety reasons, preventing corrupt half-formed arguments
    # from being dispatched.
    safety_reason = agg.finish_reason if agg.finish_reason and detect_safety_termination(agg.finish_reason) else None
    if safety_reason and aggregated_message.get("tool_calls"):
        suppress_tool_calls_for_safety(aggregated_message, safety_reason)
        aggregated_message.pop("tool_call_recovery", None)
        final_tool_chunk = None

    aggregated_response: dict[str, Any] = {
        "model": resolved_model,
        "choices": [
            {
                "message": aggregated_message,
                "finish_reason": agg.finish_reason or "stop",
            }
        ],
        "usage": normalize_usage(agg.last_usage) if agg.last_usage else {},
    }
    log_llm_response(aggregated_response)

    if agg.finish_reason:
        from myrm_agent_harness.utils.token_economics.tracker import (
            record_finish_reason,
        )

        record_finish_reason(agg.finish_reason)

    return StreamFinalization(
        final_tool_chunk=final_tool_chunk,
        aggregated_response=aggregated_response,
    )
