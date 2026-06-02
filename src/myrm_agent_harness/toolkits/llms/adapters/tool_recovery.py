"""Tool Call Recovery

[INPUT]
- adapters.tool_call_parsers (POS: Tool call parser module. Unified handling of tool call formats from multiple LLMs.)
- utils.litellm_utils::parse_tool_call_arguments_with_recovery (POS: LiteLLM utility functions)
- observability.metrics.registry::metrics_registry (POS: Global metrics registry)

[OUTPUT]
- recover_tool_call_payloads(): Parse and recover tool call arguments with fallback strategies
- build_final_tool_call_chunk(): Build a final ChatGenerationChunk containing all recovered tool calls

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

from myrm_agent_harness.toolkits.llms.adapters.tool_call_parsers import (
    HTML_ENTITY_RE,
    decode_html_entities_in_args,
)
from myrm_agent_harness.toolkits.llms.utils.litellm_utils import (
    parse_tool_call_arguments_with_recovery,
)


def recover_tool_call_payloads(
    raw_tool_calls: Sequence[Mapping[str, Any]],
    tool_schemas: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse raw tool calls with recovery strategies and return normalized payloads.

    Returns:
        (recovered_tool_calls, recovery_metadata) where each tool call has normalized
        id/type/function fields and metadata tracks recovery strategy used.
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

        recovery = parse_tool_call_arguments_with_recovery(
            function_obj.get("arguments", ""),
            raw_tool_name,
            tool_schema,
        )
        parsed_args: dict[str, Any] = recovery.args if recovery.safe else {}
        raw_arguments = function_obj.get("arguments", "")
        has_entities = isinstance(raw_arguments, dict) or (
            isinstance(raw_arguments, str) and bool(HTML_ENTITY_RE.search(raw_arguments))
        )
        if has_entities and parsed_args:
            decoded = decode_html_entities_in_args(parsed_args)
            if isinstance(decoded, dict):
                parsed_args = decoded

        recovery_metadata.append(
            {
                "tool_call_id": str(tc.get("id", f"call_{idx}")),
                "tool_name": raw_tool_name.split(":")[-1],
                "strategy": recovery.strategy,
                "degraded": recovery.degraded,
                "safe": recovery.safe,
            }
        )
        if recovery.strategy != "standard_json" or recovery.degraded or not recovery.safe:
            from myrm_agent_harness.observability.metrics.registry import metrics_registry

            metrics_registry.record_tool_arg_recovery(
                agent_id="base_agent",
                tool_name=raw_tool_name.split(":")[-1],
                strategy=recovery.strategy,
                safe=recovery.safe,
            )

        arguments_payload = (
            json.dumps(parsed_args, ensure_ascii=False, sort_keys=True)
            if recovery.safe
            else str(function_obj.get("arguments", ""))
        )
        recovered_tool_calls.append(
            {
                "id": str(tc.get("id", f"call_{idx}")),
                "type": "function",
                "function": {
                    "name": raw_tool_name,
                    "arguments": arguments_payload,
                },
            }
        )

    return recovered_tool_calls, recovery_metadata


def build_final_tool_call_chunk(
    raw_tool_calls: Sequence[Mapping[str, Any]],
    tool_schemas: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[ChatGenerationChunk | None, list[dict[str, Any]], list[dict[str, Any]]]:
    """Build a final ChatGenerationChunk with all recovered tool calls.

    Returns:
        (chunk_or_none, recovered_tool_calls, recovery_metadata)
    """
    recovered_tool_calls, recovery_metadata = recover_tool_call_payloads(raw_tool_calls, tool_schemas)
    if not recovered_tool_calls:
        return None, recovered_tool_calls, recovery_metadata

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
    filtered_metadata = [
        item
        for item in recovery_metadata
        if item["strategy"] != "standard_json" or item["degraded"] or not item["safe"]
    ]
    if filtered_metadata:
        additional_kwargs["tool_call_recovery"] = filtered_metadata

    final_chunk = AIMessageChunk(
        content="",
        tool_call_chunks=tool_call_chunks,
        additional_kwargs=additional_kwargs,
        chunk_position="last",
    )
    return ChatGenerationChunk(message=final_chunk), recovered_tool_calls, recovery_metadata
