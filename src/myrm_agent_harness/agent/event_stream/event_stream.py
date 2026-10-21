"""Fine-grained multi-part asynchronous event stream bus with replay buffer.

Enables real-time pub-sub streaming for WebUI, Tauri desktop, and background projectors
with backpressure isolation, historical event replay on reconnect, and strict monotonicity.

[OUTPUT]
- PartEventStream: Async pub-sub broadcaster with replay capabilities.

[INPUT]
- __future__
- asyncio
- contextlib
- time
- uuid
- collections

[OUTPUT]
- PartEventStream

[POS]
Fine-grained multi-part asynchronous event stream bus with replay buffer.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator

from myrm_agent_harness.agent.event_stream.part_types import (
    EventKind,
    PartEvent,
    PartKind,
)


class PartEventStream:
    """Asynchronous multi-subscriber event bus for granular message parts."""

    def __init__(self, replay_buffer_capacity: int = 1000) -> None:
        self.capacity: int = max(100, replay_buffer_capacity)
        self._replay_buffer: deque[PartEvent] = deque(maxlen=self.capacity)
        self._subscribers: set[asyncio.Queue[PartEvent]] = set()
        self._sequence_counter: int = 0
        self._lock: asyncio.Lock = asyncio.Lock()

    @property
    def current_sequence(self) -> int:
        """Return the latest allocated monotonic sequence number."""
        return self._sequence_counter

    @property
    def subscriber_count(self) -> int:
        """Return the count of currently attached active subscribers."""
        return len(self._subscribers)

    async def publish(
        self,
        *,
        session_id: str,
        message_id: str,
        part_id: str,
        part_kind: PartKind,
        event_kind: EventKind,
        delta: str = "",
        payload: dict[str, str | float | bool] | None = None,
    ) -> PartEvent:
        """Publish a granular part event to all active subscribers and append to replay buffer."""
        async with self._lock:
            self._sequence_counter += 1
            event = PartEvent(
                event_id=f"evt_{uuid.uuid4().hex[:12]}",
                session_id=session_id,
                message_id=message_id,
                part_id=part_id,
                part_kind=part_kind,
                event_kind=event_kind,
                sequence_number=self._sequence_counter,
                delta=delta,
                payload=dict(payload) if payload else {},
                timestamp=time.time(),
            )
            self._replay_buffer.append(event)

            # Fan out to all subscribers; discard on full to prevent deadlock
            for queue in list(self._subscribers):
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(event)

            return event

    async def subscribe(
        self,
        since_sequence: int = 0,
        queue_maxsize: int = 500,
    ) -> AsyncIterator[PartEvent]:
        """Subscribe to the event stream, optionally replaying past events since a sequence number."""
        queue: asyncio.Queue[PartEvent] = asyncio.Queue(maxsize=queue_maxsize)

        async with self._lock:
            # 1. Yield replay events if requested
            replay_events = [
                evt for evt in self._replay_buffer if evt.sequence_number > since_sequence
            ]
            for evt in replay_events:
                queue.put_nowait(evt)

            self._subscribers.add(queue)

        try:
            while True:
                event = await queue.get()
                yield event
                queue.task_done()
        finally:
            async with self._lock:
                self._subscribers.discard(queue)

    async def get_recent_events(
        self,
        session_id: str | None = None,
        limit: int = 100,
    ) -> tuple[PartEvent, ...]:
        """Fetch snapshot of recent buffered events, optionally filtered by session ID."""
        async with self._lock:
            events = list(self._replay_buffer)

        if session_id is not None:
            events = [e for e in events if e.session_id == session_id]

        return tuple(events[-limit:])
