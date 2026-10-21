"""Tool-level progress sink — lets tools emit progress events directly to the Agent SSE stream.

Uses ContextVar so that any tool running inside BaseAgent.run() can push events
into the Agent's output_queue without explicit parameter passing.

[INPUT]

[OUTPUT]
- ToolProgressSink: Protocol for emitting progress events
- get_tool_progress_sink() / set_tool_progress_sink(): ContextVar accessors
- create_queue_sink(): Factory to create a queue-backed sink

[POS]
Progress event push mechanism. Tools implicitly obtain a sink via ContextVar to push intermediate progress events to the Agent SSE stream.

"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from typing import Protocol

type _EventDict = dict[str, object]


class ToolProgressSink(Protocol):
    """Allows a tool to push intermediate events directly into the Agent SSE stream."""

    async def emit(self, event: _EventDict) -> None: ...


class _QueueSink:
    """Default sink implementation backed by an asyncio.Queue."""

    __slots__ = ("_message_id", "_queue")

    def __init__(self, queue: asyncio.Queue[_EventDict | object], message_id: str) -> None:
        self._queue = queue
        self._message_id = message_id

    async def emit(self, event: _EventDict) -> None:
        import logging

        logger = logging.getLogger(__name__)
        logger.info("ToolProgressSink emitting event: %s", event.get("type", "unknown"))
        event.setdefault("messageId", self._message_id)
        await self._queue.put(event)


_tool_progress_sink: ContextVar[ToolProgressSink | None] = ContextVar("_tool_progress_sink", default=None)


def get_tool_progress_sink() -> ToolProgressSink | None:
    """Retrieve the current progress sink (None when outside BaseAgent.run)."""
    return _tool_progress_sink.get()


def set_tool_progress_sink(sink: ToolProgressSink | None) -> None:
    """Set or clear the progress sink for the current async context."""
    _tool_progress_sink.set(sink)


def create_queue_sink(
    queue: asyncio.Queue[_EventDict | object],
    message_id: str,
) -> ToolProgressSink:
    """Create a ToolProgressSink backed by the given output queue."""
    return _QueueSink(queue, message_id)
