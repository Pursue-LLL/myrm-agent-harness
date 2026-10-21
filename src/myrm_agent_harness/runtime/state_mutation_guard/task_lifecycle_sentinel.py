"""异步 Task 生命周期强绑定上下文管理器模块.

本模块将后台异步执行派发包装进带 finally 兜底强杀与受控管道联动的 TaskLifecycleScope，
确保无论主协程是正常完成、被取消还是抛出未处理异常，均能 100% 自动清理野生孤儿任务并平稳关闭管道。

[INPUT]
- __future__
- asyncio
- logging
- collections
- types
- typing

[OUTPUT]
- logger
- TaskLifecycleScope

[POS]
异步 Task 生命周期强绑定上下文管理器模块.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from types import TracebackType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.runtime.state_mutation_guard.safe_event_channel import (
        SafeEventChannel,
    )

logger = logging.getLogger(__name__)


class TaskLifecycleScope:
    """异步任务生命周期守卫与自闭环上下文管理器."""

    def __init__(self, scope_name: str = "default_scope") -> None:
        self.scope_name: str = scope_name
        self._tracked_tasks: set[asyncio.Task[object]] = set()
        self._bound_channels: list[SafeEventChannel[object]] = []
        self._is_active: bool = False

    async def __aenter__(self) -> TaskLifecycleScope:
        """进入受保护的生命周期范围."""
        self._is_active = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """退出范围时，强制安全清理所有派生的子任务并关闭关联管道."""
        self._is_active = False

        # 1. 扫描未完成的野生任务并发送取消信号
        pending_tasks = [t for t in self._tracked_tasks if not t.done()]
        if pending_tasks:
            logger.info(
                "TaskLifecycleScope [%s]: reaping %d pending orphan tasks",
                self.scope_name,
                len(pending_tasks),
            )
            for t in pending_tasks:
                t.cancel()

            # 等待所有取消操作完成并吸收 CancelledError
            await asyncio.gather(*pending_tasks, return_exceptions=True)

        # 2. 安全关闭关联绑定的管道
        for ch in self._bound_channels:
            if not ch.is_closed:
                await ch.drain_and_close(timeout=1.0)

        self._tracked_tasks.clear()
        self._bound_channels.clear()

    def track_task(self, task: asyncio.Task[object]) -> asyncio.Task[object]:
        """登记一个外部创建的异步任务."""
        self._tracked_tasks.add(task)
        # 任务自然完成后自动移出集合释放引用
        task.add_done_callback(lambda t: self._tracked_tasks.discard(t))
        return task

    def spawn(
        self,
        coro: Coroutine[object, object, object],
        name: str | None = None,
    ) -> asyncio.Task[object]:
        """安全创建并登记一个受管子任务."""
        task_name = name or f"{self.scope_name}_task_{len(self._tracked_tasks) + 1}"
        task = asyncio.create_task(coro, name=task_name)
        return self.track_task(task)

    def bind_channel(self, channel: SafeEventChannel[object]) -> None:
        """绑定一个安全事件管道，在生命周期退出时自动级联关闭."""
        self._bound_channels.append(channel)

    @property
    def active_tasks_count(self) -> int:
        """当前活跃运行的受管任务数."""
        return len([t for t in self._tracked_tasks if not t.done()])
