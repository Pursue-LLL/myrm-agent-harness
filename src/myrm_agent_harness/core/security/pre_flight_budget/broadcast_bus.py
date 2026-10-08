"""Live Spend and Budget Broadcast Bus for real-time notifications."""

from __future__ import annotations

import asyncio
import contextlib
import threading
from collections import deque
from collections.abc import Awaitable, Callable

from .types import BudgetBroadcastEvent


class BudgetBroadcastBus:
    """Thread-safe event broadcast bus for live budget changes and chokepoint events."""

    def __init__(self, max_history: int = 500) -> None:
        self._lock = threading.Lock()
        self._sync_subscribers: list[Callable[[BudgetBroadcastEvent], None]] = []
        self._async_subscribers: list[
            Callable[[BudgetBroadcastEvent], Awaitable[None]]
        ] = []
        self._history: deque[BudgetBroadcastEvent] = deque(maxlen=max_history)
        self._background_tasks: set[asyncio.Task[None]] = set()

    def subscribe_sync(
        self, callback: Callable[[BudgetBroadcastEvent], None]
    ) -> None:
        """Register a synchronous subscriber."""
        with self._lock:
            if callback not in self._sync_subscribers:
                self._sync_subscribers.append(callback)

    def unsubscribe_sync(
        self, callback: Callable[[BudgetBroadcastEvent], None]
    ) -> None:
        """Unregister a synchronous subscriber."""
        with self._lock:
            if callback in self._sync_subscribers:
                self._sync_subscribers.remove(callback)

    def subscribe_async(
        self, callback: Callable[[BudgetBroadcastEvent], Awaitable[None]]
    ) -> None:
        """Register an asynchronous subscriber."""
        with self._lock:
            if callback not in self._async_subscribers:
                self._async_subscribers.append(callback)

    def unsubscribe_async(
        self, callback: Callable[[BudgetBroadcastEvent], Awaitable[None]]
    ) -> None:
        """Unregister an asynchronous subscriber."""
        with self._lock:
            if callback in self._async_subscribers:
                self._async_subscribers.remove(callback)

    def publish(self, event: BudgetBroadcastEvent) -> None:
        """Publish an event to all subscribers and append to bounded history."""
        with self._lock:
            self._history.append(event)
            sync_targets = list(self._sync_subscribers)
            async_targets = list(self._async_subscribers)

        for callback in sync_targets:
            with contextlib.suppress(Exception):
                callback(event)

        if async_targets:
            with contextlib.suppress(RuntimeError):
                loop = asyncio.get_running_loop()
                for async_cb in async_targets:
                    task = loop.create_task(self._safe_async_dispatch(async_cb, event))
                    self._background_tasks.add(task)
                    task.add_done_callback(self._background_tasks.discard)

    async def _safe_async_dispatch(
        self,
        callback: Callable[[BudgetBroadcastEvent], Awaitable[None]],
        event: BudgetBroadcastEvent,
    ) -> None:
        with contextlib.suppress(Exception):
            await callback(event)

    def get_history(
        self, project_id: str | None = None, limit: int = 50
    ) -> list[BudgetBroadcastEvent]:
        """Retrieve recent events, optionally filtered by project_id."""
        with self._lock:
            events = list(self._history)

        if project_id is not None:
            events = [e for e in events if e.project_id == project_id]

        return events[-limit:]

    def clear(self) -> None:
        """Clear all subscribers and history."""
        with self._lock:
            self._sync_subscribers.clear()
            self._async_subscribers.clear()
            self._history.clear()
