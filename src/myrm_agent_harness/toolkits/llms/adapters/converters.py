"""LiteLLM message and tool call converters


[INPUT]
- langchain_core.messages (POS: LangChain message types)
- utils.litellm_utils::parse_tool_call_arguments_with_recovery (POS: schema-aware JSON recovery utility)
- adapters.tool_call_parsers::ToolCallDict, parse_tool_calls, decode_html_entities_in_args (POS: tool call parser + HTML entity decoding)

[OUTPUT]
- lc_tool_call_to_openai_tool_call(): convert LangChain ToolCall to OpenAI format
- convert_lc_messages_to_litellm(): convert LangChain messages to LiteLLM format while preserving explicit message names
- convert_litellm_response_to_lc_message(): convert LiteLLM response to LangChain message
- convert_dict_to_message(): convert DictFormat message to LangChain BaseMessage (preserves reasoning_content for reasoning models; routes unsafe/truncated tool args to invalid_tool_calls, never to dispatchable tool_calls; HTML-decodes tool args only when asked, for xAI Grok)
- _extract_citations(): extract unified citation format from provider annotations

[POS]
LiteLLM message and tool call converter. Provides bidirectional message format conversion
between LangChain and LiteLLM. Supports all message types (System, Human, AI, Tool) and
tool call bidirectional conversion. Preserves explicit message names and automatically
extracts provider citation annotations into unified {url, title} format. As the converter
layer, depended on by ChatLiteLLM for format interop.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    ChatMessage,
    FunctionMessage,
    HumanMessage,
    SystemMessage,
    ToolCall,
    ToolMessage,
)
from langchain_core.messages.ai import UsageMetadata

from myrm_agent_harness.toolkits.llms.adapters.tool_call_parsers import (
    ToolCallDict,
    clean_xml_tool_tags,
    decode_html_entities_in_args,
    parse_tool_calls,
)
from myrm_agent_harness.toolkits.llms.utils.litellm_utils import (
    ToolArgumentRecoveryResult,
    parse_tool_call_arguments_with_recovery,
)

logger = logging.getLogger(__name__)


def lc_tool_call_to_openai_tool_call(tool_call: ToolCall) -> dict[str, Any]:
    """Convert a LangChain ToolCall to the OpenAI tool_call format."""
    return {
        "type": "function",
        "id": tool_call["id"],
        "function": {
            "name": tool_call["name"],
            # sort_keys=True ensures deterministic JSON key order, preserving KV cache hits
            "arguments": json.dumps(tool_call["args"], sort_keys=True),
        },
    }


def ensure_arguments_json_string(
    tool_calls: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Ensure tool_calls arguments are valid JSON strings.

    Handles dict→JSON conversion, None→"{}", and validates existing strings.
    Some providers (MiniMax code model) reject non-JSON arguments with 400.
    """
    result = []
    for tc in tool_calls:
        tc_copy = tc.copy()
        if "function" in tc_copy and isinstance(tc_copy["function"], dict):
            function_copy = tc_copy["function"].copy()
            args = function_copy.get("arguments")
            if isinstance(args, dict):
                function_copy["arguments"] = json.dumps(args, sort_keys=True)
            elif args is None:
                function_copy["arguments"] = "{}"
            elif isinstance(args, str):
                try:
                    json.loads(args)
                except (json.JSONDecodeError, ValueError):
                    function_copy["arguments"] = "{}"
                    logger.warning(
                        " Invalid JSON in tool_call arguments for %s, reset to {}",
                        function_copy.get("name", "?"),
                    )
            else:
                function_copy["arguments"] = json.dumps({"value": args}, sort_keys=True)
            tc_copy["function"] = function_copy
        result.append(tc_copy)
    return result


def convert_message_to_dict(message: BaseMessage, *, wire_protocol: str | None = None) -> dict[str, Any]:
    """Convert a LangChain message to the LiteLLM dict format."""
    message_dict: dict[str, Any] = {"content": message.content}
    if isinstance(message, ChatMessage):
        message_dict["role"] = message.role
    elif isinstance(message, HumanMessage):
        message_dict["role"] = "user"
    elif isinstance(message, AIMessage):
        message_dict["role"] = "assistant"
        # ThinkingBlockCleaner has already selectively removed stale reasoning_content by tool_calls
        if "reasoning_content" in message.additional_kwargs:
            message_dict["reasoning_content"] = message.additional_kwargs["reasoning_content"]
        if "responses_reasoning_items" in message.additional_kwargs and (
            wire_protocol is None or wire_protocol == "responses"
        ):
            message_dict["responses_reasoning_items"] = message.additional_kwargs["responses_reasoning_items"]
        # Process function_call (OpenAI deprecated format)
        if "function_call" in message.additional_kwargs:
            message_dict["function_call"] = message.additional_kwargs["function_call"]
        # Process tool_calls (prefer message.tool_calls, fall back to additional_kwargs)
        if message.tool_calls:
            message_dict["tool_calls"] = [lc_tool_call_to_openai_tool_call(tc) for tc in message.tool_calls]
        elif "tool_calls" in message.additional_kwargs:
            # ensure arguments are JSON strings
            message_dict["tool_calls"] = ensure_arguments_json_string(message.additional_kwargs["tool_calls"])
    elif isinstance(message, SystemMessage):
        message_dict["role"] = "system"
    elif isinstance(message, FunctionMessage):
        message_dict["role"] = "function"
        message_dict["name"] = message.name
    elif isinstance(message, ToolMessage):
        message_dict["role"] = "tool"
        message_dict["tool_call_id"] = message.tool_call_id
    else:
        raise ValueError(f"Got unknown type {message}")

    message_name = getattr(message, "name", None)
    if message_name:
        message_dict["name"] = message_name
    elif "name" in message.additional_kwargs:
        message_dict["name"] = message.additional_kwargs["name"]
    return message_dict


def _resolve_tool_schema(
    tool_name: str,
    tool_schemas: Mapping[str, Mapping[str, Any]] | None = None,
) -> Mapping[str, Any] | None:
    if not tool_schemas:
        return None
    if tool_name in tool_schemas:
        return tool_schemas[tool_name]
    if ":" in tool_name:
        stripped_name = tool_name.split(":")[-1]
        return tool_schemas.get(stripped_name)
    return None


def _parse_tool_call_args_result(
    args: str | dict[str, Any],
    tool_name: str,
    tool_schema: Mapping[str, Any] | None = None,
    *,
    stream_complete: bool | None = None,
    decode_html_entities: bool = False,
) -> tuple[dict[str, Any], ToolArgumentRecoveryResult]:
    recovery = parse_tool_call_arguments_with_recovery(args, tool_name, tool_schema, stream_complete=stream_complete)
    parsed: dict[str, Any] = recovery.args if recovery.safe else {}

    if decode_html_entities and parsed:
        decoded = decode_html_entities_in_args(parsed)
        if isinstance(decoded, dict):
            parsed = decoded

    return parsed, recovery


def _convert_raw_tool_call_to_langchain(
    tc: ToolCallDict,
    tool_schemas: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    stream_complete: bool | None = None,
    decode_html_entities: bool = False,
) -> tuple[ToolCall | None, dict[str, Any] | None]:
    """Convert an OpenAI-format tool call to a LangChain ToolCall object.

    Returns ``(tool_call, recovery_metadata)``. ``tool_call`` is ``None`` when the
    call cannot be safely executed — either its args failed every repair strategy
    or the args are known to be truncated mid-stream. The caller must route such
    calls to ``invalid_tool_calls`` (with the diagnosis) and never dispatch them,
    so a missing/partial argument never becomes a silently-wrong execution.

    Args:
        tc: OpenAI-format tool call dict.
        tool_schemas: Tool schemas keyed by name, for schema-aware recovery.
        stream_complete: Whether the producing stream ended normally. ``False``
            marks truncated args as unsafe even when a close-the-JSON repair
            would otherwise succeed.
        decode_html_entities: Whether to HTML-decode argument strings. xAI Grok
            escapes them; every other model's arguments are data.
    """
    try:
        args = tc["function"]["arguments"]

        # ensure args are a JSON string
        if isinstance(args, dict):
            args = json.dumps(args, sort_keys=True)

        # Get or Generate tool_call_id
        tool_call_id = tc.get("id", "")
        if not tool_call_id:
            tool_call_id = f"call_{uuid4().hex[:24]}"
            logger.warning(f" Generate tool_call_id: {tc['function']['name']} -> {tool_call_id}")

        # Process tool name (strip namespace prefixes)
        raw_tool_name = tc["function"]["name"]
        tool_name = raw_tool_name
        if ":" in tool_name:
            tool_name = tool_name.split(":")[-1]
            logger.warning(f" Corrected tool name: {raw_tool_name} -> {tool_name}")

        # ParseParameter JSON
        parsed_args, recovery = _parse_tool_call_args_result(
            args,
            tool_name,
            _resolve_tool_schema(raw_tool_name, tool_schemas),
            stream_complete=stream_complete,
            decode_html_entities=decode_html_entities,
        )

        metadata = {
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "strategy": recovery.strategy,
            "degraded": recovery.degraded,
            "safe": recovery.safe,
        }
        if recovery.strategy != "standard_json" or recovery.degraded or not recovery.safe:
            from myrm_agent_harness.observability.metrics.registry import (
                metrics_registry,
            )

            metrics_registry.record_tool_arg_recovery(
                agent_id="base_agent",
                tool_name=tool_name,
                strategy=recovery.strategy,
                safe=recovery.safe,
            )
        if not recovery.safe:
            # Hard gate: an unsafe parse must never become an executable tool call.
            # Return no ToolCall so the caller exposes it as an invalid call the
            # model can see and retry; wrong/empty args are never dispatched.
            # The internal strategy name stays in structured metadata (below) and
            # out of the model-facing error text.
            metadata["error"] = (
                f"Tool call arguments for '{tool_name}' could not be safely parsed; the call was NOT executed."
            )
            logger.warning(
                " Unsafe tool_call args withheld from execution for %s via %s",
                tool_name,
                recovery.strategy,
            )
            return None, metadata
        if recovery.strategy != "standard_json" or recovery.degraded:
            logger.warning(" Recovered tool_call args for %s via %s", tool_name, recovery.strategy)

        return (
            ToolCall(
                name=tool_name,
                args=parsed_args,
                id=tool_call_id,
            ),
            metadata,
        )
    except (KeyError, TypeError) as e:
        logger.warning(f" ToolCallConvertFailure: {e}")
        return None, None


def _build_invalid_tool_call(
    tc: ToolCallDict,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Build an ``invalid_tool_call`` declaration for a call that failed safe parsing.

    The raw argument text is preserved so the dangling-call repair pipeline can
    quarantine it (never replaying malformed text) and so the model receives a
    structured diagnosis; a wrong/empty call is never executed.
    """
    function_obj = tc.get("function") or {}
    raw_args = function_obj.get("arguments", "")
    if isinstance(raw_args, dict):
        raw_args = json.dumps(raw_args, sort_keys=True)
    elif not isinstance(raw_args, str):
        raw_args = "" if raw_args is None else str(raw_args)
    return {
        "type": "invalid_tool_call",
        "id": str(metadata.get("tool_call_id") or tc.get("id", "")),
        "name": str(metadata.get("tool_name") or function_obj.get("name", "")),
        "args": raw_args,
        "error": str(metadata.get("error") or "Unsafe tool call arguments"),
    }


def _parse_tool_call_args(
    args: str | dict[str, Any],
    tool_name: str,
    tool_schema: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Parse tool call parameters, returning ``{}`` when no safe parse exists.

    HTML entities stay verbatim: decoding is opt-in per model through
    ``_parse_tool_call_args_result(..., decode_html_entities=True)``.

    Args:
        args: Parameter string or dict
        tool_name: Tool name (for logging)

    Returns:
        Parsed parameter dict
    """
    parsed, recovery = _parse_tool_call_args_result(args, tool_name, tool_schema)

    if not recovery.safe:
        logger.warning(" Dropped unsafe tool_call args for %s via %s", tool_name, recovery.strategy)
        return {}
    if recovery.strategy != "standard_json" or recovery.degraded:
        logger.warning(" Recovered tool_call args for %s via %s", tool_name, recovery.strategy)
    return parsed


def _extract_citations(
    message_dict: Mapping[str, Any],
) -> list[dict[str, str | int]] | None:
    """Extract and normalize citations from provider-specific annotations.

    Handles OpenAI url_citation, xAI annotations, and other providers.
    Returns a unified list of {url, title, start_index?, end_index?} dicts,
    or None if no citations found.
    """
    annotations = message_dict.get("annotations")
    if not annotations or not isinstance(annotations, list):
        return None

    citations: list[dict[str, str | int]] = []
    for ann in annotations:
        if not isinstance(ann, dict):
            continue
        url = ann.get("url", "")
        if not url:
            continue
        entry: dict[str, str | int] = {
            "url": url,
            "title": ann.get("title", ""),
        }
        if isinstance(ann.get("start_index"), int):
            entry["start_index"] = ann["start_index"]
        if isinstance(ann.get("end_index"), int):
            entry["end_index"] = ann["end_index"]
        citations.append(entry)

    return citations if citations else None


def convert_dict_to_message(
    _dict: Mapping[str, Any],
    available_tools: list[str] | None = None,
    tool_schemas: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    stream_complete: bool | None = None,
    decode_html_entities: bool = False,
) -> BaseMessage:
    """Convert a dict-format message to a LangChain BaseMessage.

    Args:
        _dict: Provider message dict (OpenAI/LiteLLM shape).
        available_tools: Names used to filter hallucinated tool calls.
        tool_schemas: Tool schemas keyed by name, for schema-aware arg recovery.
        stream_complete: Whether the producing stream ended normally. ``False``
            (provider stopped mid-generation) marks truncated args unsafe, and
            the affected calls are surfaced as ``invalid_tool_calls`` and never
            dispatched with silently-incomplete arguments.
        decode_html_entities: Whether to HTML-decode tool-call argument strings
            (xAI Grok escapes them; every other model's arguments are data).
    """
    role = _dict["role"]
    if role == "user":
        return HumanMessage(content=_dict["content"], name=_dict.get("name"))
    elif role == "assistant":
        content = _dict.get("content", "") or ""
        additional_kwargs: dict[str, Any] = {}
        tool_calls: list[ToolCall] = []
        invalid_tool_calls: list[dict[str, Any]] = []

        # Non-streaming path reasoning fallback: reasoning_content, reasoning, thinking, thoughts, etc.
        from myrm_agent_harness.toolkits.llms.adapters.streaming import extract_reasoning_payload

        reasoning_val = extract_reasoning_payload(_dict)
        if reasoning_val:
            additional_kwargs["reasoning_content"] = reasoning_val

        if _dict.get("function_call"):
            additional_kwargs["function_call"] = dict(_dict["function_call"])

        raw_tool_calls = parse_tool_calls(dict(_dict), available_tools)
        recovery_metadata: list[dict[str, Any]] = []

        if raw_tool_calls:
            content = clean_xml_tool_tags(content)
            for tc in raw_tool_calls:
                tool_call, metadata = _convert_raw_tool_call_to_langchain(
                    tc, tool_schemas, stream_complete=stream_complete, decode_html_entities=decode_html_entities
                )
                if tool_call:
                    tool_calls.append(tool_call)
                elif metadata:
                    # Unsafe parse: keep the call as an invalid declaration so the
                    # model sees the failure and retries; wrong/empty arguments
                    # are never executed.
                    invalid_tool_calls.append(_build_invalid_tool_call(tc, metadata))
                if metadata and (
                    metadata["strategy"] != "standard_json" or metadata["degraded"] or not metadata["safe"]
                ):
                    recovery_metadata.append(metadata)
            additional_kwargs["tool_calls"] = raw_tool_calls
        if recovery_metadata:
            additional_kwargs["tool_call_recovery"] = recovery_metadata
        if invalid_tool_calls:
            additional_kwargs["invalid_tool_calls"] = invalid_tool_calls

        reasoning_items = _dict.get("responses_reasoning_items")
        if isinstance(reasoning_items, list) and reasoning_items:
            additional_kwargs["responses_reasoning_items"] = reasoning_items

        citations = _extract_citations(_dict)
        if citations:
            additional_kwargs["citations"] = citations

        return AIMessage(
            content=content,
            additional_kwargs=additional_kwargs,
            tool_calls=tool_calls,
            invalid_tool_calls=invalid_tool_calls,
            name=_dict.get("name"),
        )
    elif role == "system":
        return SystemMessage(content=_dict["content"], name=_dict.get("name"))
    elif role == "function":
        return FunctionMessage(content=_dict["content"], name=_dict["name"])
    elif role == "tool":
        return ToolMessage(
            content=_dict["content"],
            tool_call_id=_dict["tool_call_id"],
            name=_dict.get("name"),
        )
    else:
        return ChatMessage(content=_dict["content"], role=role, name=_dict.get("name"))


def create_usage_metadata(token_usage: Mapping[str, Any]) -> UsageMetadata:
    """Create UsageMetadata"""
    input_tokens = token_usage.get("prompt_tokens", 0)
    output_tokens = token_usage.get("completion_tokens", 0)
    return UsageMetadata(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
    )
