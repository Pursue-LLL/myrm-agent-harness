"""Unit tests for emit_tool_heartbeat — periodic heartbeat emission.

Covers:
- Heartbeat fires after 3s initial delay
- Emitted events contain correct tool_name, tool_call_id, elapsed_ms
- Heartbeat continues until cancelled
- Graceful handling when no progress sink is set
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.middlewares._tool_execution_lifecycle import emit_tool_heartbeat
from myrm_agent_harness.utils.runtime.progress_sink import (
    set_tool_progress_sink,
)


class _MockSink:
    def __init__(self):
        self.events: list[dict] = []

    async def emit(self, event: dict) -> None:
        self.events.append(event)


class TestEmitToolHeartbeat:
    @pytest.mark.asyncio
    async def test_emits_heartbeat_event(self):
        """Heartbeat should emit after initial 3s delay with correct fields."""
        sink = _MockSink()
        set_tool_progress_sink(sink)
        start = time.time()
        try:
            task = asyncio.create_task(emit_tool_heartbeat("bash_code_execute_tool", "tc_hb1", start))
            await asyncio.sleep(3.5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            set_tool_progress_sink(None)

        assert len(sink.events) >= 1
        event = sink.events[0]
        assert event["type"] == "tool_heartbeat"
        assert event["tool_name"] == "bash_code_execute_tool"
        assert event["tool_call_id"] == "tc_hb1"
        assert event["elapsed_ms"] >= 2500

    @pytest.mark.asyncio
    async def test_no_sink_does_not_crash(self):
        """When no progress sink is set, heartbeat should silently continue."""
        set_tool_progress_sink(None)
        start = time.time()
        task = asyncio.create_task(emit_tool_heartbeat("no_sink_tool", "tc_nosink", start))
        await asyncio.sleep(3.5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_heartbeat_includes_step_key(self):
        """Heartbeat event must have a step_key for frontend tree rendering."""
        sink = _MockSink()
        set_tool_progress_sink(sink)
        start = time.time()
        try:
            task = asyncio.create_task(emit_tool_heartbeat("web_fetch", "tc_sk", start))
            await asyncio.sleep(3.5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            set_tool_progress_sink(None)

        assert len(sink.events) >= 1
        assert sink.events[0]["step_key"] == "web_fetch_heartbeat"
