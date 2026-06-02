"""Streaming response processing mixin


[INPUT]
- langchain_core.messages::AIMessageChunk, BaseMessageChunk, ToolCallChunk (POS: LangChain message chunk types)
- langchain_core.outputs::ChatGenerationChunk (POS: LangChain generation chunk type)

[OUTPUT]
- LiteLLMStreamMixin: streaming response processing mixin class
- safe_get(), extract_chunk_metadata(), build_tool_call_chunks(), and other stream processing utilities

[POS]
Streaming response processing module. Provides stream response parsing, incremental tool call merging,
metadata extraction, and malformed chunk protection. Used by adapters.chat_model to enhance streaming capability.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any

from langchain_core.messages import AIMessageChunk, ToolCallChunk
from langchain_core.outputs import ChatGenerationChunk

logger = logging.getLogger(__name__)


def safe_get(obj: Any, key: str, default: Any = None) -> Any:
    """Safely get a property from an object or dict."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def extract_chunk_metadata(chunk: Any) -> tuple[Any, str | None, str | None]:
    """Extract usage, model, and finish_reason from a streaming chunk.

    Returns:
        (usage, model, finish_reason)
    """
    usage = safe_get(chunk, "usage")
    model = safe_get(chunk, "model")

    finish_reason = None
    choices = safe_get(chunk, "choices", [])
    if choices and len(choices) > 0:
        finish_reason = safe_get(choices[0], "finish_reason")

    return usage, model, finish_reason


def build_tool_call_chunks(
    raw_tool_calls: Any,
    tool_call_id_map: dict[str, str] | None = None,
) -> list[ToolCallChunk]:
    """Normalize provider tool_call payloads into LangChain ToolCallChunk values."""
    if not isinstance(raw_tool_calls, list):
        return []

    tool_call_chunks: list[ToolCallChunk] = []
    for rtc in raw_tool_calls:
        if not isinstance(rtc, dict):
            continue
        function_obj = rtc.get("function")
        if not isinstance(function_obj, dict):
            continue

        original_id = rtc.get("id")
        mapped_id = original_id if isinstance(original_id, str) else None
        if mapped_id and tool_call_id_map is not None:
            if mapped_id not in tool_call_id_map:
                import uuid

                tool_call_id_map[mapped_id] = f"{mapped_id}_vtx{uuid.uuid4().hex[:4]}"
            mapped_id = tool_call_id_map[mapped_id]

        tool_call_chunks.append(
            ToolCallChunk(
                name=function_obj.get("name"),
                args=function_obj.get("arguments"),
                id=mapped_id,
                index=rtc.get("index"),
            )
        )

    return tool_call_chunks


def aggregate_tool_call_chunk(tc_chunk: Any, aggregated_tool_calls: list[dict[str, Any]]) -> None:
    """Incrementally merge a tool_call chunk into the aggregated list.

    Guards against malformed streaming chunks from OpenAI-compatible backends
    where index/name/args may be None or non-string types.
    """
    tc_index = safe_get(tc_chunk, "index")
    if tc_index is None or not isinstance(tc_index, int):
        tc_index = 0
    tc_name = safe_get(tc_chunk, "name")
    tc_args = safe_get(tc_chunk, "args")
    tc_id = safe_get(tc_chunk, "id")

    while len(aggregated_tool_calls) <= tc_index:
        aggregated_tool_calls.append({"function": {"name": "", "arguments": ""}, "id": ""})

    if isinstance(tc_name, str) and tc_name:
        aggregated_tool_calls[tc_index]["function"]["name"] = tc_name
    if tc_args is not None:
        if isinstance(tc_args, str):
            aggregated_tool_calls[tc_index]["function"]["arguments"] += tc_args
        elif isinstance(tc_args, dict):
            aggregated_tool_calls[tc_index]["function"]["arguments"] += json.dumps(tc_args, ensure_ascii=False)
        else:
            logger.warning("Unexpected tool_call args type: %s", type(tc_args).__name__)
    if isinstance(tc_id, str) and tc_id:
        aggregated_tool_calls[tc_index]["id"] = tc_id


def parse_tool_calls_from_reasoning(
    aggregated_reasoning: list[str],
    aggregated_tool_calls: Sequence[Mapping[str, Any]],
    is_async: bool = False,
) -> tuple[Sequence[Mapping[str, Any]] | None, ChatGenerationChunk | None]:
    """Parse tool calls embedded in reasoning_content (e.g. GLM models).

    Returns:
        (parsed_tool_calls, final_chunk) — extracted tool calls and corresponding chunk
    """
    if not aggregated_reasoning or aggregated_tool_calls:
        return None, None

    from myrm_agent_harness.toolkits.llms.adapters.tool_call_parsers import parse_tool_calls

    reasoning_text = "".join(aggregated_reasoning)
    parsed_tool_calls = parse_tool_calls({"reasoning_content": reasoning_text})

    if not parsed_tool_calls:
        return None, None

    mode_str = "Async" if is_async else "Sync"
    logger.warning(f" Parsed {len(parsed_tool_calls)} tool calls from reasoning_content ({mode_str} streaming mode)")


    tool_call_chunks: list[ToolCallChunk] = []
    for idx, tc in enumerate(parsed_tool_calls):
        tool_call_chunks.append(
            ToolCallChunk(
                name=tc["function"]["name"],
                args=tc["function"]["arguments"],
                id=tc.get("id", f"call_{idx}"),
                index=idx,
            )
        )

    final_chunk = AIMessageChunk(content="", tool_call_chunks=tool_call_chunks)
    final_cg_chunk = ChatGenerationChunk(message=final_chunk)

    return parsed_tool_calls, final_cg_chunk


def normalize_usage(usage: Any) -> dict[str, Any]:
    """Normalize a usage object to a standard dict format."""
    if isinstance(usage, dict):
        return usage
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", 0),
        "completion_tokens": getattr(usage, "completion_tokens", 0),
        "total_tokens": getattr(usage, "total_tokens", 0),
    }
