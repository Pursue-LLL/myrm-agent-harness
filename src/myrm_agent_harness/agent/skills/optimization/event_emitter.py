"""Event Emitter System

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- typing.Callable (POS: Python可调用类型)
- asyncio (POS: 异步IO库)
- collections.defaultdict (POS: 默认字典)

[OUTPUT]
- EventEmitter: 事件发射器类（观察者模式）

[POS]
Event system (framework layer). Decouples inter-component notifications via publish-subscribe pattern.

"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

EventCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


class EventEmitter:
    """事件发射器（观察者模式）

    线程安全的异步事件系统，支持多订阅者和错误隔离。

    Examples:
        >>> emitter = EventEmitter()
        >>>
        >>> # 订阅事件
        >>> async def on_completed(event: str, payload: dict):
        ...     print(f"Optimization completed: {payload['skill_id']}")
        >>>
        >>> emitter.on('optimization_completed', on_completed)
        >>>
        >>> # 发射事件
        >>> await emitter.emit('optimization_completed', {
        ...     'skill_id': 'my-skill',
        ...     'quality_score': 0.85
        ... })
        >>>
        >>> # 取消订阅
        >>> emitter.off('optimization_completed', on_completed)
    """

    def __init__(self) -> None:
        self._listeners: dict[str, list[EventCallback]] = defaultdict(list)
        self._lock = asyncio.Lock()

    def on(self, event: str, callback: EventCallback) -> None:
        """订阅事件

        Args:
            event: 事件名称（如'optimization_completed'）
            callback: 异步回调函数（接收event和payload参数）
        """
        if callback not in self._listeners[event]:
            self._listeners[event].append(callback)
            logger.debug(f"Registered listener for event: {event}")

    def off(self, event: str, callback: EventCallback) -> None:
        """取消订阅

        Args:
            event: 事件名称
            callback: 要取消的回调函数
        """
        if callback in self._listeners[event]:
            self._listeners[event].remove(callback)
            logger.debug(f"Unregistered listener for event: {event}")

    def off_all(self, event: str | None = None) -> None:
        """取消所有订阅

        Args:
            event: 事件名称（None表示取消所有事件）
        """
        if event is None:
            self._listeners.clear()
            logger.debug("Unregistered all listeners for all events")
        else:
            self._listeners[event].clear()
            logger.debug(f"Unregistered all listeners for event: {event}")

    async def emit(self, event: str, payload: dict[str, Any] | None = None) -> None:
        """发射事件（异步通知所有订阅者）

        Args:
            event: 事件名称
            payload: 事件数据（dict）

        Note:
            单个订阅者异常不会影响其他订阅者，异常会被记录但不抛出。
        """
        if event not in self._listeners or not self._listeners[event]:
            logger.debug(f"No listeners for event: {event}")
            return

        payload = payload or {}
        listeners = self._listeners[event].copy()
        logger.debug(f"Emitting event '{event}' to {len(listeners)} listeners")

        tasks = []
        for callback in listeners:
            task = asyncio.create_task(self._safe_callback(callback, event, payload))
            tasks.append(task)

        await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_callback(self, callback: EventCallback, event: str, payload: dict[str, Any]) -> None:
        """安全调用回调函数（错误隔离）

        Args:
            callback: 回调函数
            event: 事件名称
            payload: 事件数据
        """
        try:
            await callback(event, payload)
        except Exception as e:
            logger.error(
                f"Event listener error for '{event}': {e}",
                exc_info=True,
                extra={
                    "event": event,
                    "callback": callback.__name__,
                    "error": str(e),
                },
            )

    def listener_count(self, event: str | None = None) -> int:
        """获取订阅者数量

        Args:
            event: 事件名称（None表示统计所有事件）

        Returns:
            订阅者数量
        """
        if event is None:
            return sum(len(listeners) for listeners in self._listeners.values())
        return len(self._listeners.get(event, []))

    def events(self) -> list[str]:
        """获取所有已注册的事件名称

        Returns:
            事件名称列表
        """
        return list(self._listeners.keys())
