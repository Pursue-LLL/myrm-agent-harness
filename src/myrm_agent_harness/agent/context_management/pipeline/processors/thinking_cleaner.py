"""Thinking Block 清理处理器

清理历史消息中的 reasoning/thinking 内容，减少 token 消耗并防止签名失效错误。

清理范围（按优先级）：
1. content blocks 中的 thinking/redacted_thinking（Anthropic 格式）
   - 非最新 assistant turn 的 content thinking blocks 被安全剥离
   - 最新 assistant turn 保留（Anthropic API 要求重播时签名完整）
2. additional_kwargs 中的 reasoning_content / thinking_blocks
   - Anthropic 模型：清理 reasoning_content，保留 thinking_blocks
   - DeepSeek/MiMo/Kimi 等：有 tool_calls 时保留 reasoning_content（API 要求），否则清理
   - 其他模型：清理 thinking_blocks，保留 reasoning_content

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
_THINKING_CONTENT_TYPES = frozenset(("thinking", "redacted_thinking"))
_OMITTED_PLACEHOLDER = "[assistant reasoning omitted]"


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


def _find_last_ai_index(messages: list) -> int:
    """Find the index of the last AIMessage. Returns -1 if none found."""
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], AIMessage):
            return i
    return -1


def _has_content_thinking_blocks(msg: AIMessage) -> bool:
    """Check if AIMessage has thinking/redacted_thinking in content blocks."""
    content = msg.content
    if not isinstance(content, list):
        return False
    return any(
        isinstance(b, dict) and b.get("type") in _THINKING_CONTENT_TYPES
        for b in content
    )


class ThinkingBlockCleaner(BaseProcessor):
    """清理 AI 消息中 reasoning_content、thinking_blocks 和 content thinking blocks。

    DeepSeek/MiMo/Kimi API 仅要求 tool_calls 消息保留 reasoning_content，
    纯文本回复的 reasoning_content 在下一轮后即失去价值。
    Anthropic 的 thinking/redacted_thinking content blocks 在非最新 assistant turn 中
    可安全剥离，避免签名因上下文变化而失效导致的 400 错误。
    """

    @property
    def name(self) -> str:
        return "ThinkingBlockCleaner"

    async def should_process(self, context: ProcessorContext) -> bool:
        return any(
            isinstance(m, AIMessage)
            and (
                m.additional_kwargs.get("reasoning_content")
                or m.additional_kwargs.get("thinking_blocks")
                or _has_content_thinking_blocks(m)
            )
            for m in context.messages
        )

    async def process(self, context: ProcessorContext) -> ProcessorContext:
        model_name = ""
        if context.llm is not None:
            model_name = getattr(context.llm, "model_name", "") or getattr(context.llm, "model", "") or ""

        is_anthropic = _is_anthropic_model(model_name)
        cleaned_tb = 0
        cleaned_rc = 0
        cleaned_content_tb = 0
        chars_dropped = 0

        last_human_idx = _find_last_human_index(context.messages)
        last_ai_idx = _find_last_ai_index(context.messages)

        for i, msg in enumerate(context.messages):
            if not isinstance(msg, AIMessage):
                continue

            is_latest_ai = i == last_ai_idx

            # --- Phase 1: Strip content thinking blocks from non-latest assistant ---
            if not is_latest_ai:
                content = msg.content
                if isinstance(content, list):
                    new_content = [
                        b for b in content
                        if not (isinstance(b, dict) and b.get("type") in _THINKING_CONTENT_TYPES)
                    ]
                    if len(new_content) != len(content):
                        dropped_count = len(content) - len(new_content)
                        for b in content:
                            if isinstance(b, dict) and b.get("type") in _THINKING_CONTENT_TYPES:
                                thinking_text = b.get("thinking", "")
                                if isinstance(thinking_text, str):
                                    chars_dropped += len(thinking_text)
                        if not new_content:
                            new_content = [{"type": "text", "text": _OMITTED_PLACEHOLDER}]
                        msg.content = new_content  # type: ignore[assignment]
                        cleaned_content_tb += dropped_count

            # --- Phase 2: Clean additional_kwargs ---
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

        total = cleaned_tb + cleaned_rc + cleaned_content_tb
        if total:
            context.tokens_saved += chars_dropped // 4
            logger.warning(
                " [ThinkingBlockCleaner] cleaned %d items (rc=%d, tb=%d, content_tb=%d, chars=%d, anthropic=%s)",
                total,
                cleaned_rc,
                cleaned_tb,
                cleaned_content_tb,
                chars_dropped,
                is_anthropic,
            )

        return context
