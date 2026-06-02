"""LiteLLM message and tool call converters


[INPUT]
- langchain_core.messages (POS: LangChain message types)
- utils.litellm_utils::parse_tool_call_arguments_with_recovery (POS: schema-aware JSON recovery utility)
- adapters.tool_call_parsers::ToolCallDict, parse_tool_calls, decode_html_entities_in_args (POS: tool call parser + HTML entity decoding)

[OUTPUT]
- lc_tool_call_to_openai_tool_call(): convert LangChain ToolCall to OpenAI format
- convert_lc_messages_to_litellm(): convert LangChain messages to LiteLLM format while preserving explicit message names
- convert_litellm_response_to_lc_message(): convert LiteLLM response to LangChain message
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
    HTML_ENTITY_RE,
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


def lc_tool_call_to_openai_tool_call(tool_call: ToolCall) -> dict:
    """将 LangChain   ToolCall Convert is  OpenAI Format"""
    return {
        "type": "function",
        "id": tool_call["id"],
        "function": {
            "name": tool_call["name"],
            # sort_keys=True  ensure  JSON Keysequential确定性， avoid 破坏 KV Cache
            "arguments": json.dumps(tool_call["args"], sort_keys=True),
        },
    }


def ensure_arguments_json_string(tool_calls: list[dict]) -> list[dict]:
    """ ensure  tool_calls  in   arguments 是Valid  JSON string。

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


def convert_message_to_dict(message: BaseMessage) -> dict:
    """将 LangChain 消息Convert is  LiteLLM DictFormat"""
    message_dict: dict[str, Any] = {"content": message.content}
    if isinstance(message, ChatMessage):
        message_dict["role"] = message.role
    elif isinstance(message, HumanMessage):
        message_dict["role"] = "user"
    elif isinstance(message, AIMessage):
        message_dict["role"] = "assistant"
        # ThinkingBlockCleaner 已按 tool_calls 选择性清理历史 reasoning_content
        if "reasoning_content" in message.additional_kwargs:
            message_dict["reasoning_content"] = message.additional_kwargs["reasoning_content"]
        # Process function_call（OpenAI deprecated Format）
        if "function_call" in message.additional_kwargs:
            message_dict["function_call"] = message.additional_kwargs["function_call"]
        # Process tool_calls（优先 using  message.tool_calls，其次 using  additional_kwargs）
        if message.tool_calls:
            message_dict["tool_calls"] = [lc_tool_call_to_openai_tool_call(tc) for tc in message.tool_calls]
        elif "tool_calls" in message.additional_kwargs:
            #  ensure  arguments 是 JSON string
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
) -> tuple[dict[str, Any], ToolArgumentRecoveryResult]:
    has_entities = False
    recovery = parse_tool_call_arguments_with_recovery(args, tool_name, tool_schema)
    parsed: dict[str, Any] = recovery.args if recovery.safe else {}

    if isinstance(args, dict):
        has_entities = True
    elif isinstance(args, str):
        has_entities = bool(HTML_ENTITY_RE.search(args))
    else:
        has_entities = True

    if has_entities and parsed:
        decoded = decode_html_entities_in_args(parsed)
        if isinstance(decoded, dict):
            parsed = decoded

    return parsed, recovery


def _convert_raw_tool_call_to_langchain(
    tc: ToolCallDict,
    tool_schemas: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[ToolCall | None, dict[str, Any] | None]:
    """将originalToolCallConvert is  LangChain ToolCall Object

    Args:
        tc: OpenAI-format tool callDict

    Returns:
        LangChain ToolCall Object，Parsing failedReturn None
    """
    try:
        args = tc["function"]["arguments"]

        #  ensure  args 是 JSON string
        if isinstance(args, dict):
            args = json.dumps(args, sort_keys=True)

        # Get or Generate tool_call_id
        tool_call_id = tc.get("id", "")
        if not tool_call_id:
            tool_call_id = f"call_{uuid4().hex[:24]}"
            logger.warning(f" Generate tool_call_id: {tc['function']['name']} -> {tool_call_id}")

        # ProcessTool名称（移除NamespacePrefix）
        raw_tool_name = tc["function"]["name"]
        tool_name = raw_tool_name
        if ":" in tool_name:
            tool_name = tool_name.split(":")[-1]
            logger.warning(f" 修正Tool名称: {raw_tool_name} -> {tool_name}")

        # ParseParameter JSON
        parsed_args, recovery = _parse_tool_call_args_result(
            args, tool_name, _resolve_tool_schema(raw_tool_name, tool_schemas)
        )

        metadata = {
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "strategy": recovery.strategy,
            "degraded": recovery.degraded,
            "safe": recovery.safe,
        }
        if recovery.strategy != "standard_json" or recovery.degraded or not recovery.safe:
            from myrm_agent_harness.observability.metrics.registry import metrics_registry

            metrics_registry.record_tool_arg_recovery(
                agent_id="base_agent",
                tool_name=tool_name,
                strategy=recovery.strategy,
                safe=recovery.safe,
            )
        if not recovery.safe:
            logger.warning(" Unsafe recovered tool_call args dropped for %s via %s", tool_name, recovery.strategy)
        elif recovery.strategy != "standard_json" or recovery.degraded:
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


def _parse_tool_call_args(
    args: str | dict[str, Any],
    tool_name: str,
    tool_schema: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """ParseToolCallParameter

    xAI/Grok models encode HTML entities in tool call argument values
    (e.g. ``&&`` → ``&amp;&amp;``). After JSON parsing, all string values are
    recursively decoded to restore the original content.

    Args:
        args: ParameterString or Dict
        tool_name: Tool名称（ for Log）

    Returns:
        Parse后 ParameterDict（HTML entities  already Decode）
    """
    parsed, recovery = _parse_tool_call_args_result(args, tool_name, tool_schema)

    if not recovery.safe:
        logger.warning(" Dropped unsafe tool_call args for %s via %s", tool_name, recovery.strategy)
        return {}
    if recovery.strategy != "standard_json" or recovery.degraded:
        logger.warning(" Recovered tool_call args for %s via %s", tool_name, recovery.strategy)
    return parsed


def _extract_citations(message_dict: Mapping[str, Any]) -> list[dict[str, str | int]] | None:
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
) -> BaseMessage:
    """将DictFormat 消息Convert is  LangChain BaseMessage"""
    role = _dict["role"]
    if role == "user":
        return HumanMessage(content=_dict["content"], name=_dict.get("name"))
    elif role == "assistant":
        content = _dict.get("content", "") or ""
        additional_kwargs: dict[str, Any] = {}
        tool_calls: list[ToolCall] = []

        if _dict.get("function_call"):
            additional_kwargs["function_call"] = dict(_dict["function_call"])

        raw_tool_calls = parse_tool_calls(dict(_dict), available_tools)
        recovery_metadata: list[dict[str, Any]] = []

        if raw_tool_calls:
            content = clean_xml_tool_tags(content)
            for tc in raw_tool_calls:
                tool_call, metadata = _convert_raw_tool_call_to_langchain(tc, tool_schemas)
                if tool_call:
                    tool_calls.append(tool_call)
                if metadata and (
                    metadata["strategy"] != "standard_json" or metadata["degraded"] or not metadata["safe"]
                ):
                    recovery_metadata.append(metadata)
            additional_kwargs["tool_calls"] = raw_tool_calls
        if recovery_metadata:
            additional_kwargs["tool_call_recovery"] = recovery_metadata

        citations = _extract_citations(_dict)
        if citations:
            additional_kwargs["citations"] = citations

        return AIMessage(
            content=content,
            additional_kwargs=additional_kwargs,
            tool_calls=tool_calls,
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
