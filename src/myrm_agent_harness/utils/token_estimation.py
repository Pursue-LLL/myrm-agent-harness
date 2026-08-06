"""Token 估算工具

[INPUT]
- langchain_core.messages::BaseMessage, AIMessage, ToolMessage (POS: LangChain 消息类)
- langchain_core.tools::BaseTool (POS: LangChain tool definitions)
- utils.text_utils::get_token_count, PLANNING_ENCODING (POS: Token 计数工具)
- utils.image_utils::IMAGE_TOKEN_ESTIMATE, is_image_content_item (POS: 图片 Token 估算)

[OUTPUT]
- estimate_content_tokens(): 估算单条 message content 的 token 数
- estimate_message_tokens(): 估算单条完整 message 的 token 数
- estimate_messages_tokens(): 估算 message 列表总 token 数
- estimate_bound_tools_tokens(): Turn-1 bind_tools description + schema wrapper overhead
- estimate_request_tools_tokens(): Live ModelRequest tools overhead（planning SSOT）
- estimate_context_tokens(): messages + bind-tools overhead，可选 max(provider prompt_tokens)
- SCHEMA_WRAPPER_TOKENS_PER_TOOL: 每个 bound tool 的 JSON schema wrapper 预算

[POS]
Token estimation infrastructure. Covers message-level tokens and bind-tools overhead for
context budget / compress / summarize decisions. Aligns with measure_turn1_token_inventory planning SSOT.

"""

from __future__ import annotations

import json
from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.tools import BaseTool

from myrm_agent_harness.utils.image_utils import (
    IMAGE_TOKEN_ESTIMATE,
    is_image_content_item,
)
from myrm_agent_harness.utils.text_utils import get_token_count

_PER_MESSAGE_OVERHEAD = 4
SCHEMA_WRAPPER_TOKENS_PER_TOOL = 65


def estimate_content_tokens(content: str | Sequence[object]) -> int:
    """Estimate token count for a single message's content field.

    Image items use a fixed token estimate instead of serializing base64 as text,
    which would massively overcount tokens and skew the context budget.
    """
    if isinstance(content, str):
        return get_token_count(content)

    total = 0
    for item in content:
        if is_image_content_item(item):
            total += IMAGE_TOKEN_ESTIMATE
        elif isinstance(item, dict) and item.get("type") == "text":
            total += get_token_count(str(item.get("text", "")))
        else:
            total += get_token_count(json.dumps(item))
    return total


def estimate_message_tokens(msg: BaseMessage) -> int:
    """Estimate token count for a complete message including all token-consuming fields.

    Covers: content, AIMessage.tool_calls args, ToolMessage metadata, and per-message
    framing overhead (~4 tokens for role/separators).
    """
    total = estimate_content_tokens(msg.content) + _PER_MESSAGE_OVERHEAD

    if isinstance(msg, AIMessage) and msg.tool_calls:
        for tc in msg.tool_calls:
            args = tc.get("args")
            if args:
                total += get_token_count(json.dumps(args, ensure_ascii=False))
            name = tc.get("name")
            if name:
                total += get_token_count(name)
            tc_id = tc.get("id")
            if tc_id:
                total += get_token_count(tc_id)

    elif isinstance(msg, ToolMessage):
        if msg.tool_call_id:
            total += get_token_count(msg.tool_call_id)
        if msg.name:
            total += get_token_count(msg.name)

    return total


def estimate_messages_tokens(messages: list[BaseMessage]) -> int:
    """Estimate total token count for a message list."""
    return sum(estimate_message_tokens(msg) for msg in messages)


def _tool_description_text(tool: object) -> str:
    if isinstance(tool, BaseTool):
        return tool.description or ""
    if isinstance(tool, dict):
        fn = tool.get("function")
        if isinstance(fn, dict):
            desc = fn.get("description")
            if isinstance(desc, str):
                return desc
        desc = tool.get("description")
        if isinstance(desc, str):
            return desc
    desc = getattr(tool, "description", "")
    return desc if isinstance(desc, str) else ""


def estimate_bound_tools_tokens(tools: Sequence[BaseTool]) -> int:
    """Estimate bind_tools overhead: tool descriptions + JSON schema wrapper budget.

    Matches ``scripts/measure_turn1_token_inventory.py`` (description-only + ~65/tool).
    """
    if not tools:
        return 0
    description_total = sum(get_token_count(tool.description or "") for tool in tools)
    return description_total + len(tools) * SCHEMA_WRAPPER_TOKENS_PER_TOOL


def estimate_request_tools_tokens(tools: Sequence[object]) -> int:
    """Estimate live request tool overhead using the same planning SSOT as Turn-1 inventory."""
    if not tools:
        return 0
    description_total = sum(
        get_token_count(_tool_description_text(tool)) for tool in tools
    )
    return description_total + len(tools) * SCHEMA_WRAPPER_TOKENS_PER_TOOL


def estimate_context_tokens(
    messages: list[BaseMessage],
    *,
    bound_tool_overhead_tokens: int = 0,
    last_provider_prompt_tokens: int | None = None,
) -> int:
    """Estimate full request context for compress/budget decisions.

    Tool schemas are not part of ``messages`` but are billed on every LLM call.
    When provider-reported ``prompt_tokens`` is available, use max(estimate, API)
    so compress decisions stay aligned with the UI context ring.
    """
    estimated = estimate_messages_tokens(messages) + max(0, bound_tool_overhead_tokens)
    if last_provider_prompt_tokens is not None and last_provider_prompt_tokens > 0:
        return max(estimated, last_provider_prompt_tokens)
    return estimated
