"""聊天工具函数模块（通用部分）

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- langchain_core.messages::BaseMessage, AIMessage, HumanMessage (POS: LangChain 消息类型)

[OUTPUT]
- ChatHistory, ContentItem, ChatHistoryReq: 聊天历史相关类型定义
- convert_chat_history_simple(): 将聊天历史转换为 LangChain 消息格式（仅文本）

[POS]
Chat utility functions. Provides business-config-independent chat history conversion (generic part).

"""

import json
import logging
from typing import Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

logger = logging.getLogger(__name__)

ChatHistory = list[BaseMessage]

ContentItem = str | list[dict[str, object]]
# entry 格式: [role, content] 或 [role, content, metadata_dict]
ChatHistoryEntry = list[Literal["human", "assistant"] | ContentItem | dict[str, object]]
ChatHistoryReq = list[ChatHistoryEntry]


def convert_chat_history_simple(history: object) -> ChatHistory:
    """将聊天历史转换为LangChain消息格式，仅处理文本内容，智能判断输入格式

    用于查询改写等不需要处理图片的场景。
    对 __agent_history JSON 格式的 assistant 消息，只提取 content 文本。

    Args:
        history: 原始格式或已转换格式
    """
    if not history:
        return []

    if isinstance(history, list) and history and isinstance(history[0], BaseMessage):
        return history  # type: ignore[return-value]

    messages: list[BaseMessage] = []
    for item in history:  # type: ignore[union-attr]
        role, content = item[0], item[1]
        meta = item[2] if len(item) > 2 and isinstance(item[2], dict) else {}

        text_content = _extract_text_content(content)

        if role == "human":
            messages.append(HumanMessage(content=text_content))
        else:
            additional_kwargs: dict[str, object] = {}
            reasoning_content = meta.get("reasoning_content")
            if isinstance(reasoning_content, str) and reasoning_content:
                additional_kwargs["reasoning_content"] = reasoning_content
            messages.append(AIMessage(content=text_content, additional_kwargs=additional_kwargs))

    return messages


def _extract_text_content(content: ContentItem) -> str:
    """从内容中提取纯文本

    处理三种格式：
    - 普通字符串 → 直接返回
    - __agent_history JSON 字符串 → 提取 content 字段
    - 多媒体内容列表 → 提取 text 类型项
    """
    if isinstance(content, str):
        if content.startswith('{"__agent_history"'):
            try:
                data = json.loads(content)
                if isinstance(data, dict) and data.get("__agent_history"):
                    return str(data.get("content", ""))
            except (json.JSONDecodeError, TypeError):
                pass
        return content

    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))
            elif not isinstance(item, dict):
                text_parts.append(str(item))
        return " ".join(text_parts).strip() or str(content)

    return str(content)
