"""Circular event replay buffer with monotonic sequence ordering and gap detection.

Implements high-performance in-memory sliding window event retention for SSE/WS
long-lived agent connections, providing deterministic reconnection catch-up
and buffer overflow eviction safeguards.

[OUTPUT]
- CircularEventReplayBuffer: Thread-safe, bounded circular event replay buffer.

[INPUT]
- __future__
- asyncio
- time
- collections

[OUTPUT]
- CircularEventReplayBuffer

[POS]
Circular event replay buffer with monotonic sequence ordering and gap detection.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import AsyncGenerator

from myrm_agent_harness.agent.streaming.recovery.recovery_types import (
    ReplayBatch,
    StructuredStreamEvent,
)

_DEFAULT_MAX_EVENTS: int = 1000
_DEFAULT_MAX_BYTES: int = 5 * 1024 * 1024  # 5MB


class CircularEventReplayBuffer:
    """Thread-safe bounded circular replay buffer with monotonic sequence IDs."""

    def __init__(
        self,
        stream_id: str,
        *,
        max_events: int = _DEFAULT_MAX_EVENTS,
        max_bytes: int = _DEFAULT_MAX_BYTES,
    ) -> None:
        self.stream_id: str = stream_id
        self.max_events: int = max(1, max_events)
        self.max_bytes: int = max(1, max_bytes)

        self._events: deque[StructuredStreamEvent] = deque()
        self._current_bytes: int = 0
        self._next_seq: int = 1
        self._is_ended: bool = False
        self._condition: asyncio.Condition = asyncio.Condition()

    @property
    def is_ended(self) -> bool:
        """Return True if the underlying stream has terminated."""
        return self._is_ended

    @property
    def latest_sequence_id(self) -> int:
        """Return the latest allocated sequence ID, or 0 if empty."""
        return self._next_seq - 1

    @property
    def retained_count(self) -> int:
        """Return number of events currently retained in the buffer."""
        return len(self._events)

    @property
    def current_bytes(self) -> int:
        """Return estimated byte size of retained events."""
        return self._current_bytes

    def _estimate_event_size(self, payload: dict[str, object] | str) -> int:
        """Estimate payload memory footprint in bytes."""
        base_size = 128
        if isinstance(payload, str):
            return base_size + len(payload.encode("utf-8"))
        return base_size + len(str(payload).encode("utf-8"))

    async def append_event(
        self,
        event_type: str,
        payload: dict[str, object] | str,
        *,
        timestamp: float | None = None,
    ) -> StructuredStreamEvent:
        """Append a new structured event with auto-incremented monotonic sequence ID."""
        ts = timestamp if timestamp is not None else time.time()
        size = self._estimate_event_size(payload)

        async with self._condition:
            seq = self._next_seq
            self._next_seq += 1

            event = StructuredStreamEvent(
                sequence_id=seq,
                event_type=event_type,
                stream_id=self.stream_id,
                payload=payload,
                timestamp=ts,
                estimated_bytes=size,
            )

            # Evict oldest events if capacity or byte limit is exceeded
            while self._events and (
                len(self._events) >= self.max_events
                or (self._current_bytes + size > self.max_bytes)
            ):
                evicted = self._events.popleft()
                self._current_bytes -= evicted.estimated_bytes

            self._events.append(event)
            self._current_bytes += size
            self._condition.notify_all()
            return event

    async def end_stream(self) -> None:
        """Mark the stream as ended and awaken any pending subscriber tasks."""
        async with self._condition:
            self._is_ended = True
            self._condition.notify_all()

    async def replay_since(self, last_sequence_id: int) -> ReplayBatch:
        """Query retained events occurring strictly after last_sequence_id."""
        async with self._condition:
            if not self._events:
                return ReplayBatch(
                    status="EMPTY",
                    events=(),
                    requested_seq=last_sequence_id,
                    oldest_retained_seq=0,
                    latest_retained_seq=0,
                )

            oldest_seq = self._events[0].sequence_id
            latest_seq = self._events[-1].sequence_id

            if last_sequence_id == latest_seq:
                return ReplayBatch(
                    status="UP_TO_DATE",
                    events=(),
                    requested_seq=last_sequence_id,
                    oldest_retained_seq=oldest_seq,
                    latest_retained_seq=latest_seq,
                )

            # Check if requested sequence is too old (gap due to eviction) or future
            if last_sequence_id < (oldest_seq - 1) or last_sequence_id > latest_seq:
                return ReplayBatch(
                    status="GAP_DETECTED",
                    events=(),
                    requested_seq=last_sequence_id,
                    oldest_retained_seq=oldest_seq,
                    latest_retained_seq=latest_seq,
                )

            # Slice events occurring after last_sequence_id
            matched_events = [
                evt for evt in self._events if evt.sequence_id > last_sequence_id
            ]

            return ReplayBatch(
                status="CONTINUOUS",
                events=tuple(matched_events),
                requested_seq=last_sequence_id,
                oldest_retained_seq=oldest_seq,
                latest_retained_seq=latest_seq,
            )

    async def subscribe(
        self,
        *,
        last_sequence_id: int | None = None,
        heartbeat_interval: float = 15.0,
    ) -> AsyncGenerator[StructuredStreamEvent]:
        """Subscribe to live stream with automatic catch-up replay and heartbeats."""
        replay_queue: deque[StructuredStreamEvent] = deque()

        async with self._condition:
            if last_sequence_id is not None and self._events:
                oldest_seq = self._events[0].sequence_id
                latest_seq = self._events[-1].sequence_id

                if (oldest_seq - 1) <= last_sequence_id <= latest_seq:
                    for evt in self._events:
                        if evt.sequence_id > last_sequence_id:
                            replay_queue.append(evt)
                else:
                    # If gap detected or out of bounds, replay all currently retained
                    replay_queue.extend(self._events)

            # Record pointer position for continuing live subscription
            next_seq_target = (
                replay_queue[-1].sequence_id + 1
                if replay_queue
                else (last_sequence_id + 1 if last_sequence_id is not None else self._next_seq)
            )

        # Yield caught-up events outside the condition lock
        while replay_queue:
            yield replay_queue.popleft()

        # Enter live event dispatch loop
        while True:
            evt_to_yield: StructuredStreamEvent | None = None
            is_heartbeat = False

            async with self._condition:
                # Search for target event in buffer
                found = False
                for evt in self._events:
                    if evt.sequence_id == next_seq_target:
                        evt_to_yield = evt
                        next_seq_target += 1
                        found = True
                        break

                if not found:
                    if self._is_ended:
                        break
                    try:
                        await asyncio.wait_for(
                            self._condition.wait(), timeout=heartbeat_interval
                        )
                    except TimeoutError:
                        is_heartbeat = True
                    else:
                        continue

            if is_heartbeat:
                yield StructuredStreamEvent(
                    sequence_id=0,
                    event_type="heartbeat",
                    stream_id=self.stream_id,
                    payload={"status": "alive", "timestamp": time.time()},
                    timestamp=time.time(),
                )
            elif evt_to_yield is not None:
                yield evt_to_yield
