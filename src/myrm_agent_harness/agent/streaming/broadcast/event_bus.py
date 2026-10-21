"""Async event bus with backpressure for real-time tool call broadcasting.

[INPUT]
- agent.streaming.broadcast.types::EventCallback (POS: Tool call event subscriber callback type.)
- agent.streaming.broadcast.types::ToolCallEventData (POS: Immutable tool call event payload.)

[OUTPUT]
- ToolBroadcastBus: Singleton async event bus
- subscribe() / unsubscribe() / publish() / publish_batch()

[POS]
Framework-level event bus. Business layer subscribes for transport adapters.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Sequence
from typing import ClassVar

from myrm_agent_harness.agent.streaming.broadcast.types import EventCallback, ToolCallEventData, _truncate_for_event
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)


class ToolBroadcastBus:
    """Async event bus with backpressure for real-time broadcasting.

    Features:
    - Async non-blocking publish
    - Backpressure (maxsize=1000, LRU drop)
    - Dropped event metrics
    - Subscriber isolation (single subscriber exception doesn't affect others)

    Performance:
    - Lock-free (asyncio.Queue)
    - Async non-blocking dispatch
    """

    _instance: ClassVar[ToolBroadcastBus | None] = None
    _lock: ClassVar[asyncio.Lock] = asyncio.Lock()

    def __init__(self, maxsize: int = 1000) -> None:
        """Initialize ToolBroadcastBus.

        Args:
            maxsize: Queue max size. When full, oldest events are dropped (LRU).
        """
        self._queue: asyncio.Queue[ToolCallEventData] = asyncio.Queue(maxsize=maxsize)
        self._subscribers: set[EventCallback] = set()
        self._dropped_count: int = 0
        self._dispatch_task: asyncio.Task[None] | None = None
        self._running: bool = False

    @classmethod
    async def get_instance(cls) -> ToolBroadcastBus:
        """Get singleton instance (async-safe lazy init)."""
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
                    await cls._instance.start()
        return cls._instance

    async def start(self) -> None:
        """Start background dispatch loop."""
        if self._running:
            return
        self._running = True
        self._dispatch_task = asyncio.create_task(self._dispatch_loop())
        logger.info("ToolBroadcastBus started")

    async def stop(self) -> None:
        """Stop background dispatch loop gracefully."""
        if not self._running:
            return
        self._running = False
        if self._dispatch_task:
            self._dispatch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._dispatch_task
        logger.info("ToolBroadcastBus stopped (dropped=%d)", self._dropped_count)

    def subscribe(self, callback: EventCallback) -> None:
        """Subscribe to events.

        Args:
            callback: Async function called for each event.
        """
        self._subscribers.add(callback)
        logger.debug("Subscriber added (total=%d)", len(self._subscribers))

    def unsubscribe(self, callback: EventCallback) -> None:
        """Unsubscribe from events.

        Args:
            callback: Previously subscribed callback.
        """
        self._subscribers.discard(callback)
        logger.debug("Subscriber removed (total=%d)", len(self._subscribers))

    async def publish(self, event: ToolCallEventData) -> None:
        """Publish single event (async non-blocking).

        Truncates large result/error fields to prevent memory overflow.
        Original event data is preserved for EventLogger (audit integrity).

        If queue is full, oldest event is dropped (LRU).

        Args:
            event: Tool call event data.
        """
        # Truncate large fields for memory-bound ToolBroadcastBus
        truncated_event = event
        if event.result is not None or event.error is not None:
            truncated_result = _truncate_for_event(event.result, max_bytes=1024) if event.result is not None else None
            truncated_error = _truncate_for_event(event.error, max_bytes=1024) if event.error is not None else None

            # Create truncated copy only if needed
            if truncated_result != event.result or truncated_error != event.error:
                from dataclasses import replace

                truncated_event = replace(event, result=truncated_result, error=truncated_error)

        if self._queue.full():
            try:
                self._queue.get_nowait()
                self._dropped_count += 1
            except asyncio.QueueEmpty:
                pass
        await self._queue.put(truncated_event)

    async def publish_batch(self, events: Sequence[ToolCallEventData]) -> None:
        """Publish multiple events (batch optimization).

        Args:
            events: List of tool call events.
        """
        for event in events:
            await self.publish(event)

    def get_dropped_count(self) -> int:
        """Get total dropped events count (monitoring metric)."""
        return self._dropped_count

    async def _dispatch_loop(self) -> None:
        """Background dispatch loop (runs until stop())."""
        while self._running:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=0.1)
                await self._dispatch_to_subscribers(event)
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Unexpected error in dispatch loop")

    async def _dispatch_to_subscribers(self, event: ToolCallEventData) -> None:
        """Dispatch event to all subscribers (isolated execution).

        Single subscriber exception doesn't affect others.

        Args:
            event: Tool call event data.
        """
        if not self._subscribers:
            return

        tasks = []
        for callback in self._subscribers:
            task = asyncio.create_task(self._safe_call_subscriber(callback, event))
            tasks.append(task)

        await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_call_subscriber(self, callback: EventCallback, event: ToolCallEventData) -> None:
        """Call subscriber with exception isolation.

        Args:
            callback: Subscriber callback.
            event: Tool call event data.
        """
        try:
            await callback(event)
        except Exception:
            logger.exception("Subscriber callback failed (callback=%s)", callback.__name__)
