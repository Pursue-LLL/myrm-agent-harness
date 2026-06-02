"""Thinking Block 清理处理器

清理历史消息中的 reasoning_content / thinking_blocks，
减少内存占用和 token 消耗。

根据当前 LLM provider 决定保留策略：
- Anthropic：保留 thinking_blocks，清理 reasoning_content
- MiMo/DeepSeek/Kimi 等 thinking 模型：
  - 有 tool_calls 的 assistant 消息：保留 reasoning_content（API 要求）
  - 无 tool_calls 的历史 assistant 消息（last user 之前）：安全删除 reasoning_content
- 其他：清理 thinking_blocks，保留 reasoning_content

[INPUT]
- (none)

[OUTPUT]
- ThinkingBlockCleaner: class — Thinking Block Cleaner

[POS]
Provides ThinkingBlockCleaner.
"""

from langchain_core.messages import AIMessage, HumanMessage

from myrm_agent_harness.utils.logger_utils import get_agent_logger

from ..base import BaseProcessor, ProcessorContext

logger = get_agent_logger(__name__)

_ANTHROPIC_PREFIXES = ("anthropic/", "claude")


def _is_anthropic_model(model_name: str) -> bool:
    lower = model_name.lower()
    return any(lower.startswith(p) or f"/{p}" in lower for p in _ANTHROPIC_PREFIXES)


def _has_tool_calls(msg: AIMessage) -> bool:
    """Check if an AIMessage contains tool calls."""
    if msg.tool_calls:
        return True
    tc = msg.additional_kwargs.get("tool_calls")
    return bool(tc and isinstance(tc, list) and len(tc) > 0)


def _find_last_human_index(messages: list) -> int:
    """Find the index of the last HumanMessage. Returns -1 if none found."""
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            return i
    return -1


class ThinkingBlockCleaner(BaseProcessor):
    """清理 AI 消息中 reasoning_content 和 thinking_blocks

    DeepSeek/MiMo/Kimi API 仅要求 tool_calls 消息保留 reasoning_content，
    纯文本回复的 reasoning_content 在下一轮后即失去价值。
    Reasonix（DeepSeek 官方）和 OpenClaw 均采用相同策略。
    """

    @property
    def name(self) -> str:
        return "ThinkingBlockCleaner"

    async def should_process(self, context: ProcessorContext) -> bool:
        return any(
            isinstance(m, AIMessage)
            and (m.additional_kwargs.get("reasoning_content") or m.additional_kwargs.get("thinking_blocks"))
            for m in context.messages
        )

    async def process(self, context: ProcessorContext) -> ProcessorContext:
        model_name = ""
        if context.llm is not None:
            model_name = getattr(context.llm, "model_name", "") or getattr(context.llm, "model", "") or ""

        is_anthropic = _is_anthropic_model(model_name)
        cleaned_tb = 0
        cleaned_rc = 0
        chars_dropped = 0

        last_human_idx = _find_last_human_index(context.messages)

        for i, msg in enumerate(context.messages):
            if not isinstance(msg, AIMessage):
                continue
            kwargs = msg.additional_kwargs
            if not kwargs:
                continue

            rc = kwargs.get("reasoning_content")
            tb = kwargs.get("thinking_blocks")

            if is_anthropic:
                if rc:
                    chars_dropped += len(rc) if isinstance(rc, str) else 0
                    del kwargs["reasoning_content"]
                    cleaned_rc += 1
            else:
                if tb:
                    del kwargs["thinking_blocks"]
                    cleaned_tb += 1

                if rc and isinstance(rc, str) and i < last_human_idx and not _has_tool_calls(msg):
                    chars_dropped += len(rc)
                    del kwargs["reasoning_content"]
                    cleaned_rc += 1

        total = cleaned_tb + cleaned_rc
        if total:
            context.tokens_saved += chars_dropped // 4
            logger.warning(
                " [ThinkingBlockCleaner] cleaned %d items "
                "(rc=%d, tb=%d, chars_dropped=%d, anthropic=%s)",
                total,
                cleaned_rc,
                cleaned_tb,
                chars_dropped,
                is_anthropic,
            )

        return context
