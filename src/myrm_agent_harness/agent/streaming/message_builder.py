"""消息构建器 — 将原始输入转换为 LangChain 消息列表

1. 本文件的 INPUT/OUTPUT/POS 注释
3. agent/context_management/PROMPT_CACHE_PRACTICE.md §2.2 时间戳注入

[INPUT]
- langchain_core.messages::BaseMessage, HumanMessage (POS: LangChain 消息类型)
- agent.streaming.utils::DATETIME_TAG, get_datetime_prompt (POS: 时间戳生成)
- utils.chat_utils::ChatHistoryReq, convert_chat_history_simple (POS: 聊天历史转换)

[OUTPUT]
- build_messages(): 将 query + chat_history 转换为 messages 列表
- inject_datetime_tags(): 就地注入时间戳到 messages 中

[POS]
Pure-function module for message preparation and timestamp injection.

"""

from __future__ import annotations

from datetime import datetime as _dt
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from langchain_core.messages import HumanMessage

from myrm_agent_harness.agent.types import QuoteAttachment
from myrm_agent_harness.utils.chat_utils import convert_chat_history_simple
from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .utils import DATETIME_TAG, datetime_injection_enabled_var, get_datetime_prompt, user_timezone_var

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage

    from myrm_agent_harness.utils.chat_utils import ChatHistoryReq

logger = get_agent_logger(__name__)


def build_messages(
    query: str | list[dict[str, object]], chat_history: ChatHistoryReq | list[BaseMessage] | None
) -> list[BaseMessage]:
    """将 query + chat_history 转换为 LangChain 消息列表。

    Args:
        query: 用户查询（纯文本或 OpenAI Vision content parts）
        chat_history: 聊天历史（原始格式或已转换格式）

    Returns:
        消息列表，末尾为当前用户消息
    """
    messages: list[BaseMessage] = convert_chat_history_simple(chat_history) if chat_history else []
    messages.append(HumanMessage(content=query))  # type: ignore[arg-type]
    return messages


def inject_datetime_tags(
    messages: list[BaseMessage],
    chat_history: ChatHistoryReq | list[BaseMessage] | None,
    query: str | list[dict[str, object]],
) -> None:
    """就地注入时间戳到 messages 中。

    - 历史消息：使用确定性时间戳（sent_at + sent_timezone），保证前缀缓存命中，使用 [Sent at: ...] 标签
    - 当前消息（最后一条）：使用 datetime.now()，使用 <current_datetime>...</current_datetime> 标签

    Args:
        messages: build_messages() 返回的消息列表（就地修改）
        chat_history: 原始聊天历史（用于提取 metadata 中的 sent_at/sent_timezone）
        query: 原始查询（用于判断是否已包含时间戳）
    """
    if not datetime_injection_enabled_var.get():
        return

    current_tz = user_timezone_var.get()

    if chat_history:
        injected = 0
        for idx, entry in enumerate(chat_history):
            if not isinstance(entry, list) or len(entry) < 3 or entry[0] != "human":
                continue
            meta = entry[2]
            if not isinstance(meta, dict):
                continue
            msg = messages[idx]
            if not isinstance(msg, HumanMessage) or not isinstance(msg.content, str):
                continue
            if DATETIME_TAG in msg.content or "[Sent at:" in msg.content:
                continue

            sent_at = meta.get("sent_at")
            if sent_at is not None:
                sent_tz = meta.get("sent_timezone") or current_tz
                dt = _dt.fromtimestamp(float(sent_at), tz=ZoneInfo("UTC"))
                time_str = _format_time_with_timezone(dt, sent_tz)
                prompt = f"[Sent at: {time_str}]"
            elif "ts" in meta:
                ts_val = meta["ts"]
                dt = _dt.fromisoformat(str(ts_val)) if not isinstance(ts_val, _dt) else ts_val
                prompt = get_datetime_prompt(current_tz, dt)
            else:
                continue

            messages[idx] = HumanMessage(content=f"{msg.content}\n\n{prompt}")
            injected += 1
        if injected:
            logger.warning(" 历史消息确定性时间戳已注入 (%d 条)", injected)

    if isinstance(query, str) and DATETIME_TAG not in query:
        datetime_prompt = get_datetime_prompt(current_tz)
        messages[-1] = HumanMessage(content=f"{query}\n\n{datetime_prompt}")
        logger.debug(" 当前消息时间戳已在 Agent 入口处注入")
    elif isinstance(query, list):
        datetime_prompt = get_datetime_prompt(current_tz)
        _inject_datetime_into_multimodal(messages, query, datetime_prompt)


def _inject_datetime_into_multimodal(
    messages: list[BaseMessage],
    query: list[dict[str, object]],
    datetime_prompt: str,
) -> None:
    """Append datetime to the text part of a multimodal query."""
    updated_parts: list[dict[str, object]] = []
    text_injected = False
    for part in query:
        if part.get("type") == "text" and isinstance(part.get("text"), str) and not text_injected:
            original_text = str(part["text"])
            if DATETIME_TAG not in original_text:
                updated_parts.append({"type": "text", "text": f"{original_text}\n\n{datetime_prompt}"})
                text_injected = True
                continue
        updated_parts.append(part)

    if text_injected:
        messages[-1] = HumanMessage(content=updated_parts)  # type: ignore[arg-type]
        logger.warning(" 多模态消息时间戳已在 Agent 入口处注入")


def _format_time_with_timezone(dt: _dt, timezone: str | None) -> str:
    """Format datetime with timezone for deterministic timestamp rendering.

    Args:
        dt: UTC datetime object
        timezone: IANA timezone string (e.g., "Asia/Shanghai"), None for UTC

    Returns:
        Formatted time string like "2026-04-13 17:13:38 Monday (UTC+8)"
    """
    if timezone:
        try:
            tz = ZoneInfo(timezone)
            local_dt = dt.astimezone(tz)
            utc_offset = local_dt.utcoffset()
            if utc_offset is not None:
                total_seconds = int(utc_offset.total_seconds())
                sign = "+" if total_seconds >= 0 else "-"
                hours, remainder = divmod(abs(total_seconds), 3600)
                mins = remainder // 60
                offset_str = f"{sign}{hours}:{mins:02d}" if mins else f"{sign}{hours}"
                tz_label = f" (UTC{offset_str})"
            else:
                tz_label = ""
        except Exception:
            logger.warning("Invalid timezone: %s, using UTC", timezone)
            local_dt = dt
            tz_label = ""
    else:
        local_dt = dt
        tz_label = ""

    return local_dt.strftime("%Y-%m-%d %H:%M:%S") + tz_label


def inject_ephemeral_quote(messages: list[BaseMessage]) -> None:
    """就地将划词引用内容内联到当前用户消息中（阅后即焚）。

    当最新的 HumanMessage 的 additional_kwargs 中包含 QuoteAttachment 时，
    将引用原文以 <quoted_context> 标签包裹后前置到消息 content 中。

    **阅后即焚机制**：DB 保存的是用户原始文本（不含 quoted_context），
    下一轮从 DB 重建 chat_history 时引用文本自然消失，无需额外清理。

    **Prompt Cache 安全**：仅修改 messages[-1]（当前轮次），
    历史消息零修改，前缀 100% 命中。符合 PROMPT_CACHE_PRACTICE.md 规范
    （动态内容必须使用 HumanMessage，不额外插入 SystemMessage）。

    Args:
        messages: build_messages() 返回的消息列表（就地修改）。
    """
    if not messages:
        return

    last_msg = messages[-1]
    if not isinstance(last_msg, HumanMessage):
        return

    quote_attachment = last_msg.additional_kwargs.get("quote_attachment")
    if not isinstance(quote_attachment, QuoteAttachment):
        return

    original_content = last_msg.content
    if not isinstance(original_content, str):
        return

    wrapped_content = (
        f'<quoted_context source="{quote_attachment.source_message_id}">\n'
        f"{quote_attachment.quoted_text}\n"
        f"</quoted_context>\n\n"
        f"{original_content}"
    )

    messages[-1] = HumanMessage(content=wrapped_content, additional_kwargs=last_msg.additional_kwargs)

    logger.info(
        "Ephemeral quote injected (source_id=%s, %d chars)",
        quote_attachment.source_message_id,
        len(quote_attachment.quoted_text),
    )
