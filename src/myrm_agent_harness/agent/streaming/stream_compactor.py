"""[INPUT]
- (none)

[OUTPUT]
- StreamCompactor: class — Stream Compactor

[POS]
Provides StreamCompactor.
"""

import asyncio
from typing import Any

from myrm_agent_harness.agent.streaming.types import AgentEventType, AgentStreamEvent


class StreamCompactor:
    """流式压实器 (Stream Compactor)

    拦截并缓冲高频流式事件（如 MESSAGE、REASONING 和 ARTIFACT_CONTENT）的文本片段。
    采用后台看门狗机制，彻底解决慢推理导致的幽灵延迟。

    Flush 策略：
    1. 容量阈值：缓冲区超过 max_chars
    2. 时间阈值：距离上次 Flush 超过 max_wait_ms（由后台 asyncio.Task 保证）
    3. 事件类型变更：遇到非目标事件或事件类型发生变化
    4. 显式 Flush：流结束或异常时
    """

    def __init__(self, output_queue: asyncio.Queue[Any], max_wait_ms: int = 50, max_chars: int = 50):
        self._queue = output_queue
        self._max_wait_ms = max_wait_ms
        self._max_chars = max_chars

        self._buffer: list[str] = []
        self._buffer_size = 0

        # 记录当前正在缓冲的事件类型（MESSAGE 或 ARTIFACT_CONTENT）
        self._current_event_type: str | None = None
        self._message_id: str | None = None
        self._metadata: dict[str, Any] | None = None

        # 后台看门狗任务
        self._watchdog_task: asyncio.Task[None] | None = None

    async def put(self, event: Any) -> None:
        # Convert dict to AgentStreamEvent internally for processing if needed, or extract
        event_type = event.get("type") if hasattr(event, "get") else getattr(event, "type", None)

        # 目标事件类型
        if event_type in (
            AgentEventType.MESSAGE.value,
            AgentEventType.ARTIFACT_CONTENT.value,
            AgentEventType.REASONING.value,
            AgentEventType.MESSAGE,
            AgentEventType.ARTIFACT_CONTENT,
            AgentEventType.REASONING,
        ):
            data = event.get("data") if hasattr(event, "get") else getattr(event, "data", None)
            if isinstance(data, str) and data:
                event_type_str = event_type.value if isinstance(event_type, AgentEventType) else event_type
                # 如果事件类型发生变化，先 flush 旧数据
                if self._current_event_type and self._current_event_type != event_type_str:
                    await self.flush()

                self._current_event_type = event_type_str
                self._buffer.append(data)
                self._buffer_size += len(data)

                # 提取元数据（以第一个到达的 chunk 为准）
                if self._message_id is None:
                    self._message_id = (
                        event.get("messageId") if hasattr(event, "get") else getattr(event, "messageId", None)
                    )
                if self._metadata is None:
                    self._metadata = (
                        event.get("metadata") if hasattr(event, "get") else getattr(event, "data", None)
                    )  # metadata was in data in some versions, or raw. Let's keep it safe.

                # 如果达到容量阈值，立即 flush
                if self._buffer_size >= self._max_chars:
                    await self.flush()
                # 否则，如果看门狗未启动，则启动看门狗
                elif self._watchdog_task is None or self._watchdog_task.done():
                    self._watchdog_task = asyncio.create_task(self._watchdog())
                return

        # 非目标事件，立即 flush 缓冲区以保证时序
        await self.flush()

        # Ensure we pass the strongly typed event forward
        if isinstance(event, dict):
            typed_event = AgentStreamEvent.from_dict(event)
            await self._queue.put(typed_event.to_dict())
        elif hasattr(event, "to_dict"):
            await self._queue.put(event.to_dict())
        else:
            await self._queue.put(event)

    async def _watchdog(self) -> None:
        """后台看门狗：休眠 max_wait_ms 后自动 flush 缓冲区"""
        try:
            await asyncio.sleep(self._max_wait_ms / 1000.0)
            if self._buffer:
                await self.flush()
        except asyncio.CancelledError:
            pass

    async def flush(self) -> None:
        # 取消看门狗任务，但如果当前是在看门狗任务内部调用的 flush，则不取消自己
        if self._watchdog_task and not self._watchdog_task.done():
            current_task = asyncio.current_task()
            if current_task != self._watchdog_task:
                self._watchdog_task.cancel()
                self._watchdog_task = None

        if not self._buffer or not self._current_event_type:
            return

        merged_text = "".join(self._buffer)

        event = AgentStreamEvent(type=self._current_event_type, data=merged_text, messageId=self._message_id)

        if self._metadata is not None:
            event.extra_data["metadata"] = self._metadata

        # 清空缓冲区
        self._buffer.clear()
        self._buffer_size = 0
        self._current_event_type = None
        self._message_id = None
        self._metadata = None

        await self._queue.put(event.to_dict())
