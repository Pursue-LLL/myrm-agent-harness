"""生命周期受控安全事件管道模块.

本模块对 asyncio.Queue 进行工业级封装，提供 ACTIVE / DRAINING / CLOSED 三态生命周期管理，
并在管道关闭后自动静默丢弃残余异步写入，彻底根除 send on closed channel 崩溃。

[INPUT]
- __future__
- asyncio
- logging
- uuid

[OUTPUT]
- logger
- SafeEventChannel

[POS]
生命周期受控安全事件管道模块.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from myrm_agent_harness.runtime.state_mutation_guard.mutation_guard_types import (
    ChannelLifecycleState,
    ChannelPutResult,
    ChannelPutStatus,
)

logger = logging.getLogger(__name__)


class SafeEventChannel[T]:
    """受控安全事件管道.

    通过显式生命周期状态控制，确保在 Agent 主流程结束后，后台迟滞任务或回调写入不会抛出异常。
    """

    def __init__(self, channel_id: str | None = None, maxsize: int = 1000) -> None:
        self.channel_id: str = channel_id or f"chan_{uuid.uuid4().hex[:8]}"
        self.maxsize: int = maxsize
        self._queue: asyncio.Queue[T] = asyncio.Queue(maxsize=maxsize)
        self._state: ChannelLifecycleState = ChannelLifecycleState.ACTIVE
        self._state_lock: asyncio.Lock = asyncio.Lock()

        # 统计计数器
        self.delivered_count: int = 0
        self.dropped_closed_count: int = 0
        self.dropped_draining_count: int = 0
        self.dropped_full_count: int = 0
        self.consumed_count: int = 0

    @property
    def state(self) -> ChannelLifecycleState:
        """获取当前管道生命周期状态."""
        return self._state

    @property
    def is_closed(self) -> bool:
        """管道是否已彻底关闭."""
        return self._state == ChannelLifecycleState.CLOSED

    @property
    def qsize(self) -> int:
        """当前队列中待处理事件数."""
        return self._queue.qsize()

    async def safe_put(
        self,
        event: T,
        event_id: str | None = None,
        timeout: float = 2.0,
    ) -> ChannelPutResult:
        """向管道安全投递事件.

        在管道关闭或排空时自动丢弃并返回状态，绝不抛出任何异常拖垮调用者.
        """
        eid = event_id or f"evt_{uuid.uuid4().hex[:8]}"

        # 1. 快速检查生命周期状态
        if self._state == ChannelLifecycleState.CLOSED:
            self.dropped_closed_count += 1
            logger.debug(
                "SafeEventChannel [%s]: dropped event '%s' because channel is CLOSED",
                self.channel_id,
                eid,
            )
            return ChannelPutResult(
                status=ChannelPutStatus.DROPPED_CHANNEL_CLOSED,
                event_id=eid,
                dropped_reason=f"Channel '{self.channel_id}' is CLOSED",
            )

        if self._state == ChannelLifecycleState.DRAINING:
            self.dropped_draining_count += 1
            logger.debug(
                "SafeEventChannel [%s]: dropped event '%s' because channel is DRAINING",
                self.channel_id,
                eid,
            )
            return ChannelPutResult(
                status=ChannelPutStatus.DROPPED_DRAINING,
                event_id=eid,
                dropped_reason=f"Channel '{self.channel_id}' is DRAINING",
            )

        # 2. 尝试投递进内部队列，带有界超时保护防死锁
        try:
            await asyncio.wait_for(self._queue.put(event), timeout=timeout)
            self.delivered_count += 1
            return ChannelPutResult(status=ChannelPutStatus.DELIVERED, event_id=eid)
        except TimeoutError:
            self.dropped_full_count += 1
            logger.warning(
                "SafeEventChannel [%s]: dropped event '%s' due to queue full timeout (%ss)",
                self.channel_id,
                eid,
                timeout,
            )
            return ChannelPutResult(
                status=ChannelPutStatus.DROPPED_QUEUE_FULL,
                event_id=eid,
                dropped_reason=f"Queue full timeout after {timeout}s",
            )

    async def get(self, timeout: float | None = None) -> T | None:
        """从管道中读取事件.

        若管道已彻底关闭且内部队列为空，返回 None.
        """
        if self._state == ChannelLifecycleState.CLOSED and self._queue.empty():
            return None

        try:
            if timeout is not None:
                item = await asyncio.wait_for(self._queue.get(), timeout=timeout)
            else:
                item = await self._queue.get()
            self._queue.task_done()
            self.consumed_count += 1
            return item
        except TimeoutError:
            return None

    async def drain_and_close(self, timeout: float = 3.0) -> None:
        """平滑排空管道并转入彻底关闭状态.

        首先将状态设为 DRAINING 拒绝新写入，等待存量事件消费完毕后转为 CLOSED.
        """
        async with self._state_lock:
            if self._state == ChannelLifecycleState.CLOSED:
                return
            self._state = ChannelLifecycleState.DRAINING

        start_time = asyncio.get_running_loop().time()
        while not self._queue.empty():
            if asyncio.get_running_loop().time() - start_time > timeout:
                logger.warning(
                    "SafeEventChannel [%s]: drain timeout reached, forcing close with %d items left",
                    self.channel_id,
                    self._queue.qsize(),
                )
                break
            await asyncio.sleep(0.02)

        async with self._state_lock:
            self._state = ChannelLifecycleState.CLOSED
            logger.info("SafeEventChannel [%s] has transitioned to CLOSED", self.channel_id)

    def close_immediate(self) -> None:
        """立即将管道置为 CLOSED，丢弃所有后续与未决操作."""
        self._state = ChannelLifecycleState.CLOSED
        # 清空内部队列防止内存泄漏
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except (asyncio.QueueEmpty, ValueError):
                break
        logger.info("SafeEventChannel [%s] immediately closed", self.channel_id)
