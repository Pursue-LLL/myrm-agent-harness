"""聊天工具函数模块（通用部分）

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- langchain_core.messages::BaseMessage, AIMessage, HumanMessage (POS: LangChain 消息类型)
- utils.text_sanitizer::extract_and_strip_think_blocks (POS: 剥离内联 think/reasoning 标签块)

[OUTPUT]
- ChatHistory, ContentItem, ChatHistoryReq: 聊天历史相关类型定义
- convert_chat_history_simple(): 将聊天历史转换为 LangChain 消息格式（仅文本）
- extract_text_content(): 从字符串 / 多媒体列表 / JSON 中提取纯文本
- extract_answer_text(): 从 LLM 响应提取用户可见答案文本（str / block list / think 剥离 / reasoning 模型回退）
- extract_litellm_answer_text(): 从 litellm 原生响应提取用户可见答案文本（choices[0].message / reasoning_content / block list）

[POS]
Chat utility functions. Provides business-config-independent chat history conversion (generic part).

"""

import json
import logging
from typing import Literal, cast

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from myrm_agent_harness.utils.text_sanitizer import extract_and_strip_think_blocks

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
        return history

    entries = cast("list[ChatHistoryEntry]", history)
    messages: list[BaseMessage] = []
    for item in entries:
        role, content = item[0], item[1]
        meta = item[2] if len(item) > 2 and isinstance(item[2], dict) else {}

        text_content = extract_text_content(cast("ContentItem", content))

        if role == "human":
            messages.append(HumanMessage(content=text_content))
        else:
            additional_kwargs: dict[str, object] = {}
            reasoning_content = meta.get("reasoning_content")
            if isinstance(reasoning_content, str) and reasoning_content:
                additional_kwargs["reasoning_content"] = reasoning_content
            messages.append(AIMessage(content=text_content, additional_kwargs=additional_kwargs))

    return messages


def extract_text_content(content: ContentItem) -> str:
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
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                raw_text = item.get("text", "")
                text_parts.append(str(raw_text) if raw_text is not None else "")
            elif not isinstance(item, dict):
                text_parts.append(str(item))
        return " ".join(text_parts).strip() or str(content)

    return str(content)


def extract_answer_text(response: object) -> str:
    """从 LLM 响应提取用户可见的答案文本。

    兼容三种响应形态：
    - 普通 ``str`` content
    - Anthropic 风格块列表（``[{"type": "text", "text": "..."}]``）
    - reasoning 模型（DeepSeek-R1、Qwen-QwQ、OpenAI o-series 等）返回
      ``content=None``、答案存于 ``additional_kwargs["reasoning_content"]``

    提取前剥离内联 think/reasoning 标签块（Qwen3 等本地模型会把思考
    过程直接写在 content 里），避免思考文本污染脚本/结果。空文本块列表
    不会泄漏 repr（此时回退到 reasoning_content）。
    """
    raw_content = getattr(response, "content", None)
    if raw_content is None or (isinstance(raw_content, list) and not raw_content):
        content = ""
    else:
        content = extract_text_content(cast("ContentItem", raw_content))
        if isinstance(raw_content, list) and content == str(raw_content):
            # extract_text_content 在无文本块时回退到列表 repr，
            # 这里清空以触发 reasoning_content 回退。
            content = ""
    if content:
        clean_content, _ = extract_and_strip_think_blocks(content)
        if clean_content:
            return clean_content
    kwargs = getattr(response, "additional_kwargs", None)
    if isinstance(kwargs, dict):
        reasoning = kwargs.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning:
            return reasoning
    return ""


def extract_litellm_answer_text(response: object) -> str:
    """从 litellm.acompletion 原生响应提取用户可见文本。

    处理形态：
    - ``response.choices[0].message.content`` 为 str
    - Anthropic 风格块列表（``[{"type": "text", "text": "..."}]``）
    - reasoning 模型（DeepSeek-R1/Qwen3 等）content 为空、
      答案存于 ``message.reasoning_content``
    """
    if response is None:
        return ""
    choices = getattr(response, "choices", None)
    if not isinstance(choices, list) or not choices:
        return ""
    message = getattr(choices[0], "message", None)
    if message is None:
        return ""
    content = getattr(message, "content", None)
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                raw_text = item.get("text", "")
                text_parts.append(str(raw_text) if raw_text is not None else "")
            elif not isinstance(item, dict):
                text_parts.append(str(item))
        text = " ".join(text_parts).strip()
    else:
        text = str(content).strip() if content is not None else ""
    if text:
        return text
    reasoning = getattr(message, "reasoning_content", None)
    return reasoning.strip() if isinstance(reasoning, str) and reasoning else ""
