"""Token 估算工具

[INPUT]
- langchain_core.messages::BaseMessage, AIMessage, ToolMessage (POS: LangChain 消息类)
- utils.text_utils::get_token_count (POS: Token 计数工具)
- utils.image_utils::IMAGE_TOKEN_ESTIMATE, is_image_content_item (POS: 图片 Token 估算)

[OUTPUT]
- estimate_content_tokens(): 估算单条消息 content 字段的 token 数
- estimate_message_tokens(): 估算单条完整消息的 token 数（含 content + tool_calls + 元数据 + framing）
- estimate_messages_tokens(): 估算消息列表的总 token 数

[POS]
Token estimation infrastructure. Covers all token-consuming fields at the message level: content, tool_calls.args, tool_call_id, name, and framing overhead.

"""

import json
from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from myrm_agent_harness.utils.image_utils import IMAGE_TOKEN_ESTIMATE, is_image_content_item
from myrm_agent_harness.utils.text_utils import get_token_count

_PER_MESSAGE_OVERHEAD = 4


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
