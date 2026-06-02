"""Session Notes 触发策略

[INPUT]
- schemas::SessionNotesConfig (POS: 笔记配置)
- utils.token_estimation::estimate_messages_tokens (POS: Token 估算)

[OUTPUT]
- SessionNotesTrigger: 触发策略管理器（双阈值门控 + 状态追踪）
- should_update_notes: 便捷函数

[POS]
Dual-threshold trigger strategy: token growth + tool call count. Optimizes for natural breakpoints when the last assistant turn has no tool calls.

"""

from __future__ import annotations

from typing import TYPE_CHECKING

from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .schemas import SessionNotesConfig

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage

logger = get_agent_logger(__name__)


class SessionNotesTrigger:
    """双阈值触发策略

    借鉴 Claude Code 的 shouldExtractMemory：
    - 初始化阈值：总 token 达到 init_token_threshold 才开始
    - 更新阈值：token 增长 ≥ update_token_threshold AND 工具调用 ≥ update_tool_call_threshold
    - 自然断点：最后一轮助手没有工具调用时，只需满足 token 阈值
    """

    def __init__(self, config: SessionNotesConfig | None = None) -> None:
        self._config = config or SessionNotesConfig()
        self._initialized = False
        self._last_token_count = 0
        self._last_tool_call_count = 0

    # Suppress notes updates beyond this tool-call count to avoid
    # prompt cache breaks during unproductive loops.
    _LOOP_SUPPRESS_TOOL_CALLS = 35

    def should_update(self, messages: list[BaseMessage], total_tokens: int, total_tool_calls: int) -> bool:
        """判断是否应该触发笔记更新

        Args:
            messages: 当前消息列表
            total_tokens: 当前总 token 数
            total_tool_calls: 当前总工具调用次数

        Returns:
            是否应该触发更新
        """
        if total_tool_calls > self._LOOP_SUPPRESS_TOOL_CALLS:
            return False

        if not self._initialized:
            if total_tokens < self._config.init_token_threshold:
                return False
            self._initialized = True
            self._last_token_count = total_tokens
            self._last_tool_call_count = total_tool_calls
            return True

        token_growth = total_tokens - self._last_token_count
        tool_call_growth = total_tool_calls - self._last_tool_call_count

        has_met_token_threshold = token_growth >= self._config.update_token_threshold
        has_met_tool_call_threshold = tool_call_growth >= self._config.update_tool_call_threshold

        is_natural_break = not _has_tool_calls_in_last_assistant_turn(messages)

        should = (has_met_token_threshold and has_met_tool_call_threshold) or (
            has_met_token_threshold and is_natural_break
        )

        if should:
            self._last_token_count = total_tokens
            self._last_tool_call_count = total_tool_calls

        return should

    def record_update(self, total_tokens: int, total_tool_calls: int) -> None:
        """记录一次成功的更新（用于外部手动触发后同步状态）"""
        self._last_token_count = total_tokens
        self._last_tool_call_count = total_tool_calls

    def reset(self) -> None:
        """重置状态（用于测试）"""
        self._initialized = False
        self._last_token_count = 0
        self._last_tool_call_count = 0


def should_update_notes(
    trigger: SessionNotesTrigger, messages: list[BaseMessage], total_tokens: int, total_tool_calls: int
) -> bool:
    """便捷函数：判断是否应该触发笔记更新"""
    return trigger.should_update(messages, total_tokens, total_tool_calls)


def _has_tool_calls_in_last_assistant_turn(messages: list[BaseMessage]) -> bool:
    """检查最后一轮助手消息是否包含工具调用"""
    for msg in reversed(messages):
        if msg.type == "ai":
            if isinstance(msg.content, list):
                return any(isinstance(block, dict) and block.get("type") == "tool_use" for block in msg.content)
            return bool(hasattr(msg, "tool_calls") and msg.tool_calls)
        if msg.type == "human":
            break
    return False
