"""Unit tests for ToolProgressSink — queue-backed progress emission.

Covers:
- _QueueSink.emit() pushes event to queue with messageId
- get_tool_progress_sink() / set_tool_progress_sink() ContextVar lifecycle
- create_queue_sink() factory
- Protocol conformance
"""

from __future__ import annotations

import asyncio

import pytest

from myrm_agent_harness.utils.runtime.progress_sink import (
    ToolProgressSink,
    _QueueSink,
    create_queue_sink,
    get_tool_progress_sink,
    set_tool_progress_sink,
)


class TestQueueSink:
    @pytest.mark.asyncio
    async def test_emit_puts_event_on_queue(self):
        q: asyncio.Queue = asyncio.Queue()
        sink = _QueueSink(queue=q, message_id="msg_123")
        await sink.emit({"type": "tool_heartbeat", "elapsed_ms": 3000})
        event = q.get_nowait()
        assert event["type"] == "tool_heartbeat"
        assert event["elapsed_ms"] == 3000
        assert event["messageId"] == "msg_123"

    @pytest.mark.asyncio
    async def test_emit_does_not_overwrite_existing_message_id(self):
        q: asyncio.Queue = asyncio.Queue()
        sink = _QueueSink(queue=q, message_id="msg_default")
        await sink.emit({"type": "status", "messageId": "msg_explicit"})
        event = q.get_nowait()
        assert event["messageId"] == "msg_explicit"

    @pytest.mark.asyncio
    async def test_emit_multiple_events(self):
        q: asyncio.Queue = asyncio.Queue()
        sink = _QueueSink(queue=q, message_id="msg_multi")
        for i in range(5):
            await sink.emit({"type": "tool_heartbeat", "count": i})
        assert q.qsize() == 5


class TestContextVarLifecycle:
    def test_default_is_none(self):
        set_tool_progress_sink(None)
        assert get_tool_progress_sink() is None

    @pytest.mark.asyncio
    async def test_set_and_get(self):
        q: asyncio.Queue = asyncio.Queue()
        sink = create_queue_sink(q, "msg_test")
        set_tool_progress_sink(sink)
        retrieved = get_tool_progress_sink()
        assert retrieved is sink
        set_tool_progress_sink(None)

    @pytest.mark.asyncio
    async def test_clear_sink(self):
        q: asyncio.Queue = asyncio.Queue()
        sink = create_queue_sink(q, "msg_clear")
        set_tool_progress_sink(sink)
        set_tool_progress_sink(None)
        assert get_tool_progress_sink() is None


class TestCreateQueueSink:
    @pytest.mark.asyncio
    async def test_factory_creates_working_sink(self):
        q: asyncio.Queue = asyncio.Queue()
        sink = create_queue_sink(q, "msg_factory")
        assert hasattr(sink, "emit"), "Sink must have emit method"
        await sink.emit({"type": "test"})
        assert q.qsize() == 1
        event = q.get_nowait()
        assert event["messageId"] == "msg_factory"
