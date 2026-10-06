"""Tool Call Recovery

[INPUT]
- adapters.tool_call_parsers (POS: Tool call parser module. Unified handling of tool call formats from multiple LLMs.)
- adapters.safety_termination_detector::detect_safety_termination (POS: Safety termination detection)
- utils.litellm_utils::parse_tool_call_arguments_with_recovery (POS: LiteLLM utility functions)
- utils.token_economics.usage_ledger::DROPPED_STREAM_FINISH_REASON (POS: finish_reason telemetry sentinel for dropped streams)
- observability.metrics.registry::metrics_registry (POS: Global metrics registry)

[OUTPUT]
- is_stream_complete(): Map a provider finish_reason to the arg-recovery completeness signal
- has_withheld_tool_calls(): Whether a message records tool calls withheld as unsafe (never executable)
- recover_tool_call_payloads(): Parse and recover tool call arguments with fallback strategies (HTML-entity decoding is opt-in)
- build_final_tool_call_chunk(): Build the final ChatGenerationChunk carrying all safely recovered tool calls; calls withheld as unsafe are recorded in `additional_kwargs["tool_call_recovery"]` on a metadata-only chunk

[POS]
Tool call recovery module. Handles cross-provider argument parsing with multiple
fallback strategies (standard JSON, regex extraction, bracket matching). Produces
LangChain-compatible ToolCallChunk messages for downstream consumption.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from langchain_core.messages import AIMessageChunk, ToolCallChunk
from langchain_core.outputs import ChatGenerationChunk

from myrm_agent_harness.toolkits.llms.adapters.safety_termination_detector import (
    detect_safety_termination,
)
from myrm_agent_harness.toolkits.llms.adapters.tool_call_parsers import decode_html_entities_in_args
from myrm_agent_harness.toolkits.llms.utils.litellm_utils import (
    parse_tool_call_arguments_with_recovery,
)
from myrm_agent_harness.utils.token_economics.usage_ledger import (
    DROPPED_STREAM_FINISH_REASON,
)


def is_stream_complete(finish_reason: str | None) -> bool:
    """Map a finish reason to the arg-recovery completeness signal.

    ``True`` when the model ended the turn normally (``tool_calls``, ``stop``, ...):
    the argument stream is complete. ``False`` when generation stopped abnormally —
    a missing finish reason, the dropped-stream sentinel (the stream ended before
    the final metadata chunk), a length cut (``length``/``max_tokens``), or a
    provider safety termination — so argument text is known to be incomplete and
    must not be closed into a valid-looking object. Well-formed arguments never
    reach the repair gate (they return via the ``standard_json`` fast path), so an
    abnormal-end signal only ever withholds arguments that already need a
    non-standard repair.
    """
    if not finish_reason:
        return False
    if finish_reason == DROPPED_STREAM_FINISH_REASON:
        return False
    if finish_reason == "tool_calls":
        return True
    if finish_reason in ("length", "max_tokens"):
        return False
    return not detect_safety_termination(finish_reason)


def has_withheld_tool_calls(additional_kwargs: Mapping[str, object] | None) -> bool:
    """Whether a message records tool calls withheld as unsafe (``safe=False``).

    Withheld calls never become executable ``tool_calls``, so a turn whose final
    message carries nothing else would end without a word. Recovery layers use
    this to treat such a message as a failed tool call rather than an empty one.
    """
    items = additional_kwargs.get("tool_call_recovery") if additional_kwargs else None
    return isinstance(items, list) and any(isinstance(item, Mapping) and item.get("safe") is False for item in items)


def recover_tool_call_payloads(
    raw_tool_calls: Sequence[Mapping[str, Any]],
    tool_schemas: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    stream_complete: bool | None = None,
    decode_html_entities: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse raw tool calls with recovery strategies and return normalized payloads.

    Only calls whose arguments recovered safely are returned in the first list.
    Calls that failed every repair, or whose arguments are known to be truncated
    (``stream_complete is False``), are excluded from dispatch and reported in
    ``recovery_metadata`` with ``safe=False`` plus a diagnosis, so callers can
    surface them as invalid calls; wrong/empty arguments are never executed.

    Args:
        raw_tool_calls: OpenAI-format tool call dicts.
        tool_schemas: Tool schemas keyed by name, for schema-aware recovery.
        stream_complete: Whether the producing stream ended normally (see
            :func:`parse_tool_call_arguments_with_recovery`).
        decode_html_entities: Whether to HTML-decode argument strings. xAI Grok
            escapes them; every other model's arguments are data.

    Returns:
        (safe_tool_calls, recovery_metadata) where each tool call has normalized
        id/type/function fields and metadata tracks the recovery strategy used.
    """
    recovered_tool_calls: list[dict[str, Any]] = []
    recovery_metadata: list[dict[str, Any]] = []

    for idx, tc in enumerate(raw_tool_calls):
        function_obj = tc.get("function")
        if not isinstance(function_obj, Mapping):
            continue

        raw_tool_name = str(function_obj.get("name", "") or "")
        if not raw_tool_name:
            continue

        tool_schema = None
        if tool_schemas:
            tool_schema = tool_schemas.get(raw_tool_name)
            if tool_schema is None and ":" in raw_tool_name:
                tool_schema = tool_schemas.get(raw_tool_name.split(":")[-1])

        raw_arguments = function_obj.get("arguments", "")
        recovery = parse_tool_call_arguments_with_recovery(
            raw_arguments,
            raw_tool_name,
            tool_schema,
            stream_complete=stream_complete,
        )
        parsed_args: dict[str, Any] = recovery.args if recovery.safe else {}
        if decode_html_entities and parsed_args:
            decoded = decode_html_entities_in_args(parsed_args)
            if isinstance(decoded, dict):
                parsed_args = decoded

        tool_call_id = str(tc.get("id", f"call_{idx}"))
        metadata: dict[str, Any] = {
            "tool_call_id": tool_call_id,
            "tool_name": raw_tool_name.split(":")[-1],
            "strategy": recovery.strategy,
            "degraded": recovery.degraded,
            "safe": recovery.safe,
        }
        if recovery.strategy != "standard_json" or recovery.degraded or not recovery.safe:
            from myrm_agent_harness.observability.metrics.registry import metrics_registry

            metrics_registry.record_tool_arg_recovery(
                agent_id="base_agent",
                tool_name=raw_tool_name.split(":")[-1],
                strategy=recovery.strategy,
                safe=recovery.safe,
            )

        if not recovery.safe:
            metadata["raw_arguments"] = (
                raw_arguments
                if isinstance(raw_arguments, str)
                else json.dumps(raw_arguments, ensure_ascii=False, sort_keys=True)
            )
            metadata["error"] = (
                f"Tool call arguments for '{raw_tool_name.split(':')[-1]}' could not be safely parsed; "
                "the call was NOT executed."
            )
            recovery_metadata.append(metadata)
            continue

        recovery_metadata.append(metadata)
        recovered_tool_calls.append(
            {
                "id": tool_call_id,
                "type": "function",
                "function": {
                    "name": raw_tool_name,
                    "arguments": json.dumps(parsed_args, ensure_ascii=False, sort_keys=True),
                },
            }
        )

    return recovered_tool_calls, recovery_metadata


def build_final_tool_call_chunk(
    raw_tool_calls: Sequence[Mapping[str, Any]],
    tool_schemas: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    stream_complete: bool | None = None,
    decode_html_entities: bool = False,
) -> tuple[ChatGenerationChunk | None, list[dict[str, Any]], list[dict[str, Any]]]:
    """Build a final ChatGenerationChunk with all safely recovered tool calls.

    Calls that failed safe parsing are never emitted as executable tool call
    chunks; they are recorded (raw text and a diagnosis) in
    ``additional_kwargs["tool_call_recovery"]``, so a truncated/partial argument
    cannot be aggregated into a dispatchable call.

    Args:
        raw_tool_calls: OpenAI-format tool call dicts.
        tool_schemas: Tool schemas keyed by name, for schema-aware recovery.
        stream_complete: Whether the producing stream ended normally.
        decode_html_entities: Whether to HTML-decode argument strings (xAI Grok).

    Returns:
        (chunk_or_none, recovered_tool_calls, recovery_metadata)
    """
    recovered_tool_calls, recovery_metadata = recover_tool_call_payloads(
        raw_tool_calls, tool_schemas, stream_complete=stream_complete, decode_html_entities=decode_html_entities
    )
    filtered_metadata = [
        item
        for item in recovery_metadata
        if item["strategy"] != "standard_json" or item["degraded"] or not item["safe"]
    ]

    if not recovered_tool_calls:
        # Withheld (unsafe) calls are recorded in recovery_metadata only. They are
        # deliberately NOT placed on the chunk as invalid_tool_calls: LangChain's
        # AIMessageChunk synthesizes tool_call_chunks from invalid_tool_calls, and
        # merging those would re-materialize the withheld call as an executable
        # tool_call with truncated args — exactly what we are preventing. A
        # metadata-only final chunk (when anything was withheld) lets the
        # dangling-repair middleware re-declare the call for retry.
        if not filtered_metadata:
            return None, recovered_tool_calls, recovery_metadata
        metadata_only_chunk = AIMessageChunk(
            content="",
            additional_kwargs={"tool_call_recovery": filtered_metadata},
            chunk_position="last",
        )
        return ChatGenerationChunk(message=metadata_only_chunk), recovered_tool_calls, recovery_metadata

    tool_call_chunks: list[ToolCallChunk] = []
    for idx, tc in enumerate(recovered_tool_calls):
        function_obj = tc.get("function")
        if not isinstance(function_obj, Mapping):
            continue
        tool_call_chunks.append(
            ToolCallChunk(
                name=function_obj.get("name"),
                args=function_obj.get("arguments"),
                id=tc.get("id", f"call_{idx}"),
                index=idx,
            )
        )

    additional_kwargs: dict[str, Any] = {}
    if filtered_metadata:
        additional_kwargs["tool_call_recovery"] = filtered_metadata

    final_chunk = AIMessageChunk(
        content="",
        tool_call_chunks=tool_call_chunks,
        additional_kwargs=additional_kwargs,
        chunk_position="last",
    )
    return ChatGenerationChunk(message=final_chunk), recovered_tool_calls, recovery_metadata
