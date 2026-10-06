# [POS] myrm_agent_harness/toolkits/memory/budget_curator/scroll_navigator.py
# [INPUT] ScrollAnchorRequest, ScrollAnchorResult, ScrollMessageItem from .types
# [OUTPUT] SessionScrollNavigator (长程会话回溯锚点与双向滑动翻页导航器)

"""长程会话回溯锚点协议，围绕指定消息 ID 穿透拉取前后连续上下文窗口。"""

from __future__ import annotations

from collections.abc import Sequence

from myrm_agent_harness.toolkits.memory.budget_curator.types import (
    ScrollAnchorRequest,
    ScrollAnchorResult,
    ScrollMessageItem,
)


class SessionScrollNavigator:
    """会话历史双向滑动窗口回溯导航器。"""

    @staticmethod
    def scroll_around_message(
        messages: Sequence[ScrollMessageItem],
        request: ScrollAnchorRequest,
    ) -> ScrollAnchorResult:
        """围绕 request.around_message_id 精准拉取前后各 N 条上下文窗口。"""
        if not messages:
            return ScrollAnchorResult(
                conversation_id=request.conversation_id,
                around_message_id=request.around_message_id,
                messages=[],
                has_more_before=False,
                has_more_after=False,
            )

        anchor_idx: int = -1
        for idx, msg in enumerate(messages):
            if msg.message_id == request.around_message_id:
                anchor_idx = idx
                break

        if anchor_idx == -1:
            raise KeyError(
                f"Anchor message_id '{request.around_message_id}' not found in conversation '{request.conversation_id}'"
            )

        start_idx = max(0, anchor_idx - max(0, request.before_limit))
        end_idx = min(len(messages), anchor_idx + max(0, request.after_limit) + 1)

        window_messages = list(messages[start_idx:end_idx])
        has_more_before = start_idx > 0
        has_more_after = end_idx < len(messages)

        return ScrollAnchorResult(
            conversation_id=request.conversation_id,
            around_message_id=request.around_message_id,
            messages=window_messages,
            has_more_before=has_more_before,
            has_more_after=has_more_after,
        )
