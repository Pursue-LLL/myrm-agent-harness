"""Resilient stream buffer for SSE reconnection.

[INPUT]

[OUTPUT]
- ResilientStreamBuffer: dynamic sliding window buffer
- GlobalStreamRegistry: manages active stream buffers

[POS]
Harness engine-layer stream state persistence component.

"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import AsyncGenerator
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# 默认 5MB 的内存缓冲上限，足以容纳几十万字的深度长文（纯文本 JSON），极难 OOM
_DEFAULT_MAX_BYTES = 5 * 1024 * 1024


@dataclass
class _BufferItem:
    event_id: str
    payload: str
    timestamp: float
    size: int


class ResilientStreamBuffer:
    """A dynamic sliding window buffer for SSE events based on max bytes."""

    def __init__(self, run_id: str, max_bytes: int = _DEFAULT_MAX_BYTES) -> None:
        self.run_id = run_id
        self.max_bytes = max_bytes
        self._buffer: deque[_BufferItem] = deque()
        self._current_bytes: int = 0
        self._condition = asyncio.Condition()
        self._is_ended = False
        self._next_seq = 0

    def _generate_event_id(self) -> str:
        ts = int(time.time() * 1000)
        seq = self._next_seq
        self._next_seq += 1
        return f"{ts}-{seq}"

    async def append(self, sse_chunk: str) -> str:
        """Append an SSE chunk to the buffer, evicting oldest if max_bytes exceeded."""
        # Ensure chunk is properly formatted as SSE data
        if not sse_chunk.startswith("data: "):
            return ""

        event_id = self._generate_event_id()

        # Inject id into the JSON if possible, or prepend id: field
        # The standard SSE format allows `id: {id}\ndata: {json}\n\n`

        payload = f"id: {event_id}\n{sse_chunk}"
        size = len(payload.encode("utf-8"))

        async with self._condition:
            # Sliding window eviction
            while self._current_bytes + size > self.max_bytes and self._buffer:
                evicted = self._buffer.popleft()
                self._current_bytes -= evicted.size

            self._buffer.append(_BufferItem(event_id, payload, time.time(), size))
            self._current_bytes += size
            self._condition.notify_all()

        return payload

    async def end_stream(self) -> None:
        """Mark the stream as ended, unblocking all waiters."""
        async with self._condition:
            self._is_ended = True
            self._condition.notify_all()

    async def subscribe(
        self, last_event_id: str | None = None, heartbeat_interval: float = 15.0
    ) -> AsyncGenerator[str]:
        """Subscribe to the stream, optionally resuming from a specific event ID.

        If last_event_id is provided, replays all buffered events that occurred AFTER it.
        Then blocks and yields new events as they arrive, until end_stream() is called.
        """
        async with self._condition:
            start_index = 0
            if last_event_id:
                found = False
                for idx, item in enumerate(self._buffer):
                    if item.event_id == last_event_id:
                        start_index = idx + 1
                        found = True
                        break

                if not found and self._buffer:
                    logger.warning(
                        "Last-Event-ID %s not found in buffer for run %s. Replaying from oldest available.",
                        last_event_id,
                        self.run_id,
                    )

            next_index = start_index

        while True:
            async with self._condition:
                if next_index < len(self._buffer):
                    item = self._buffer[next_index]
                    next_index += 1
                    yield item.payload
                    continue

                if self._is_ended:
                    break

                try:
                    await asyncio.wait_for(self._condition.wait(), timeout=heartbeat_interval)
                except TimeoutError:
                    yield "event: heartbeat\ndata: null\n\n"
                    continue


class GlobalStreamRegistry:
    """Manages active stream buffers across the application."""

    _instance: GlobalStreamRegistry | None = None

    @classmethod
    def get(cls) -> GlobalStreamRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self._buffers: dict[str, ResilientStreamBuffer] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, run_id: str) -> ResilientStreamBuffer:
        async with self._lock:
            if run_id not in self._buffers:
                self._buffers[run_id] = ResilientStreamBuffer(run_id)
            return self._buffers[run_id]

    async def has_buffer(self, run_id: str) -> bool:
        async with self._lock:
            return run_id in self._buffers

    async def remove(self, run_id: str) -> None:
        async with self._lock:
            if run_id in self._buffers:
                await self._buffers[run_id].end_stream()
                del self._buffers[run_id]
