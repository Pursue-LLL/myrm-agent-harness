"""工具调用分组

基于 `tool_call_id` 构建压缩与完整性校验所需的最小事务单元。
压缩规划必须围绕 group，而不是依赖 AI/ToolMessage 的相邻位置猜测。

[INPUT]
- (none)

[OUTPUT]
- ToolCallGroup: class — Tool Call Group
- build_tool_call_groups: function — build_tool_call_groups

[POS]
Provides ToolCallGroup, build_tool_call_groups.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolCallGroup:
    """单个工具调用的最小事务单元"""

    ai_index: int
    tool_index: int
    tool_call_id: str
    ai_message: AIMessage
    tool_message: ToolMessage
    tool_call: dict[str, object]


def build_tool_call_groups(messages: list[BaseMessage]) -> list[ToolCallGroup]:
    """按 `tool_call_id` 精确构建工具调用分组

    规则：
    1. 仅为拥有合法 `tool_call_id` 的 tool_call 建组
    2. 仅接受位于对应 AIMessage 之后的 ToolMessage
    3. 若 provider 跨 turn 复用 `tool_call_id`，按“同一 AI 片段内的最后一条结果”
       配对，避免把前一轮 AI 调用绑定到后一轮结果
    """
    tool_positions: dict[str, list[tuple[int, ToolMessage]]] = {}
    for idx, message in enumerate(messages):
        if not isinstance(message, ToolMessage):
            continue
        tool_call_id = getattr(message, "tool_call_id", None)
        if not tool_call_id:
            continue
        positions = tool_positions.setdefault(tool_call_id, [])
        if positions:
            old_idx, _ = positions[-1]
            logger.warning(
                "Duplicate tool_call_id detected during grouping: %s (indices: %d, %d). Segment-aware pairing enabled.",
                tool_call_id,
                old_idx,
                idx,
            )
        positions.append((idx, message))

    ai_occurrence_indices: dict[str, list[int]] = {}
    for ai_index, message in enumerate(messages):
        if not isinstance(message, AIMessage) or not message.tool_calls:
            continue
        for tool_call in message.tool_calls:
            tool_call_id = tool_call.get("id")
            if isinstance(tool_call_id, str) and tool_call_id:
                ai_occurrence_indices.setdefault(tool_call_id, []).append(ai_index)

    ai_occurrence_cursor: dict[str, int] = {}
    used_tool_indices: set[int] = set()

    groups: list[ToolCallGroup] = []
    for ai_index, message in enumerate(messages):
        if not isinstance(message, AIMessage) or not message.tool_calls:
            continue

        for tool_call in message.tool_calls:
            tool_call_id = tool_call.get("id")
            if not isinstance(tool_call_id, str) or not tool_call_id:
                continue

            tool_matches = tool_positions.get(tool_call_id)
            if not tool_matches:
                continue

            occurrence_index = ai_occurrence_cursor.get(tool_call_id, 0)
            ai_occurrence_cursor[tool_call_id] = occurrence_index + 1
            next_ai_indices = ai_occurrence_indices.get(tool_call_id, [])
            next_same_ai_index = (
                next_ai_indices[occurrence_index + 1] if occurrence_index + 1 < len(next_ai_indices) else len(messages)
            )

            candidates = [
                (tool_index, tool_message)
                for tool_index, tool_message in tool_matches
                if ai_index < tool_index < next_same_ai_index and tool_index not in used_tool_indices
            ]
            if not candidates:
                continue
            tool_index, tool_message = candidates[-1]
            used_tool_indices.add(tool_index)

            groups.append(
                ToolCallGroup(
                    ai_index=ai_index,
                    tool_index=tool_index,
                    tool_call_id=tool_call_id,
                    ai_message=message,
                    tool_message=tool_message,
                    tool_call=tool_call,
                )
            )

    return groups
