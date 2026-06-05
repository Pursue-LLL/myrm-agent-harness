"""推理文本清洗器 — 拦截并重定向模型泄漏的思考标签
[INPUT]
- agent.streaming.types::AgentEventType (POS: 提供 AgentEventType.REASONING 和 MESSAGE)

[OUTPUT]
- ReasoningScrubber: 状态机，用于在流式管道中剥离 thinking 标签并重定向为 REASONING 事件。
- THINKING_TAG_NAMES: 所有已知 thinking 标签名集合，供渲染层 strip_thinking_tags 复用。

[POS]
流式清洗器。处理非标准模型泄漏在普通 content 流中的思考过程标签，将其跨 Chunk 无损转化为独立事件。
"""

from __future__ import annotations

from myrm_agent_harness.core.events import THINKING_TAG_NAMES
from myrm_agent_harness.core.events.types import AgentEventType


class ReasoningScrubber:
    """Stateful scrubber to intercept and redirect thinking blocks across stream chunks.

    采用 O(N) 滑动窗口前缀探测，支持跨 Chunk 完美截断拦截，对非标签文本 0 延迟。
    """

    START_TAGS = tuple(f"<{name}>" for name in THINKING_TAG_NAMES)
    END_TAGS = tuple(f"</{name}>" for name in THINKING_TAG_NAMES)

    def __init__(self) -> None:
        self.in_think_block = False
        self.buffer = ""
        self.active_end_tag = ""
        # 预计算最大长度以优化前缀检查
        self.max_start_len = max(len(t) for t in self.START_TAGS)
        self.max_end_len = max(len(t) for t in self.END_TAGS)

    def process(self, chunk: str) -> list[tuple[AgentEventType, str]]:
        """处理文本 Chunk，返回 (事件类型, 文本内容) 列表。

        Args:
            chunk: 流式输入文本碎片

        Returns:
            转换后的事件列表，类型为 MESSAGE 或 REASONING
        """
        self.buffer += chunk
        events: list[tuple[AgentEventType, str]] = []

        while self.buffer:
            if not self.in_think_block:
                # 寻找最早出现的完整起始标签
                earliest_idx = -1
                found_tag = None

                for tag in self.START_TAGS:
                    idx = self.buffer.find(tag)
                    if idx != -1 and (earliest_idx == -1 or idx < earliest_idx):
                        earliest_idx = idx
                        found_tag = tag

                if found_tag:
                    # 发现完整起始标签，将前面的内容作为 MESSAGE 释放
                    if earliest_idx > 0:
                        events.append((AgentEventType.MESSAGE, self.buffer[:earliest_idx]))

                    self.in_think_block = True
                    self.active_end_tag = "</" + found_tag[1:]
                    self.buffer = self.buffer[earliest_idx + len(found_tag) :]
                    continue

                # 检查 buffer 结尾是否为某个起始标签的前缀（处理被网络切断的情况）
                matched_prefix = False
                check_len = min(len(self.buffer), self.max_start_len - 1)

                for i in range(1, check_len + 1):
                    suffix = self.buffer[-i:]
                    if any(tag.startswith(suffix) for tag in self.START_TAGS):
                        emit_part = self.buffer[:-i]
                        if emit_part:
                            events.append((AgentEventType.MESSAGE, emit_part))
                        self.buffer = suffix
                        matched_prefix = True
                        break

                if matched_prefix:
                    break  # 命中前缀，等待下一个 chunk 补全
                else:
                    # 未命中任何前缀，安全释放全部 buffer
                    events.append((AgentEventType.MESSAGE, self.buffer))
                    self.buffer = ""
                    break

            else:
                # 在思考状态中，寻找对应的结束标签
                idx = self.buffer.find(self.active_end_tag)
                if idx != -1:
                    if idx > 0:
                        events.append((AgentEventType.REASONING, self.buffer[:idx]))

                    self.in_think_block = False
                    self.buffer = self.buffer[idx + len(self.active_end_tag) :]
                    self.active_end_tag = ""
                    continue

                # 检查 buffer 结尾是否为结束标签的前缀
                matched_prefix = False
                check_len = min(len(self.buffer), self.max_end_len - 1)

                for i in range(1, check_len + 1):
                    suffix = self.buffer[-i:]
                    if self.active_end_tag.startswith(suffix):
                        emit_part = self.buffer[:-i]
                        if emit_part:
                            events.append((AgentEventType.REASONING, emit_part))
                        self.buffer = suffix
                        matched_prefix = True
                        break

                if matched_prefix:
                    break
                else:
                    events.append((AgentEventType.REASONING, self.buffer))
                    self.buffer = ""
                    break

        return events

    def flush(self) -> list[tuple[AgentEventType, str]]:
        """在流结束时清空任何残留在 buffer 中的文本。"""
        if not self.buffer:
            return []

        event_type = AgentEventType.REASONING if self.in_think_block else AgentEventType.MESSAGE
        res = [(event_type, self.buffer)]
        self.buffer = ""
        return res
