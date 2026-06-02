"""Tests for ResilientStreamBuffer and GlobalStreamRegistry.

Validates that SSE reconnection never produces duplicate or missing events,
which is essential for preventing the "dropped repeated characters" bug
that affects competitors using diff-based streaming.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.streaming.stream_buffer import (
    GlobalStreamRegistry,
    ResilientStreamBuffer,
)


@pytest.fixture
def buffer() -> ResilientStreamBuffer:
    return ResilientStreamBuffer("test-run-1")


class TestResilientStreamBuffer:
    @pytest.mark.asyncio
    async def test_append_and_subscribe_basic(
        self, buffer: ResilientStreamBuffer
    ) -> None:
        """Events appended before subscribe are all yielded."""
        await buffer.append('data: {"type":"message","data":"Hello"}\n\n')
        await buffer.append('data: {"type":"message","data":" World"}\n\n')
        await buffer.end_stream()

        events = []
        async for event in buffer.subscribe():
            events.append(event)
        assert len(events) == 2
        assert "Hello" in events[0]
        assert "World" in events[1]

    @pytest.mark.asyncio
    async def test_subscribe_after_last_event_id(
        self, buffer: ResilientStreamBuffer
    ) -> None:
        """Reconnecting with Last-Event-ID only yields events AFTER that ID."""
        payloads = []
        for i in range(5):
            p = await buffer.append(f'data: {{"type":"message","data":"chunk{i}"}}\n\n')
            payloads.append(p)
        await buffer.end_stream()

        # Extract event ID from the 3rd event (index 2)
        # Format: "id: {ts}-{seq}\ndata: ..."
        third_payload = payloads[2]
        event_id = third_payload.split("\n")[0].replace("id: ", "")

        events = []
        async for event in buffer.subscribe(last_event_id=event_id):
            events.append(event)

        # Should get events 3 and 4 (after index 2)
        assert len(events) == 2
        assert "chunk3" in events[0]
        assert "chunk4" in events[1]

    @pytest.mark.asyncio
    async def test_no_duplicate_on_reconnect(
        self, buffer: ResilientStreamBuffer
    ) -> None:
        """Simulates disconnect/reconnect — no event is duplicated."""
        for i in range(10):
            await buffer.append(f'data: {{"data":"token{i}"}}\n\n')

        # First subscriber reads 5 events then "disconnects"
        seen_ids: list[str] = []
        count = 0
        async for event in buffer.subscribe():
            event_id = event.split("\n")[0].replace("id: ", "")
            seen_ids.append(event_id)
            count += 1
            if count == 5:
                break

        last_seen = seen_ids[-1]

        await buffer.end_stream()

        # Reconnect from last seen
        reconnect_events = []
        async for event in buffer.subscribe(last_event_id=last_seen):
            reconnect_events.append(event)

        assert len(reconnect_events) == 5
        for i, ev in enumerate(reconnect_events):
            assert f"token{i + 5}" in ev

    @pytest.mark.asyncio
    async def test_repeated_content_preserved(
        self, buffer: ResilientStreamBuffer
    ) -> None:
        """Repeated identical payloads are NOT deduplicated."""
        for _ in range(3):
            await buffer.append('data: {"data":"the "}\n\n')
        await buffer.end_stream()

        events = []
        async for event in buffer.subscribe():
            events.append(event)

        assert len(events) == 3
        for ev in events:
            assert "the " in ev

    @pytest.mark.asyncio
    async def test_sliding_window_eviction(self) -> None:
        """When max_bytes is exceeded, oldest events are evicted."""
        buf = ResilientStreamBuffer("evict-test", max_bytes=200)
        for i in range(20):
            await buf.append(f'data: {{"data":"chunk{i:04d}"}}\n\n')
        await buf.end_stream()

        events = []
        async for event in buf.subscribe():
            events.append(event)

        # Should have fewer than 20 events due to eviction
        assert len(events) < 20
        assert len(events) > 0
        # Last event should be the most recent
        assert "chunk0019" in events[-1]

    @pytest.mark.asyncio
    async def test_non_sse_data_ignored(self, buffer: ResilientStreamBuffer) -> None:
        """Payloads not starting with 'data: ' are rejected."""
        result = await buffer.append("not-sse-data")
        assert result == ""

    @pytest.mark.asyncio
    async def test_subscribe_unknown_last_event_id_replays_all(
        self, buffer: ResilientStreamBuffer
    ) -> None:
        """Unknown Last-Event-ID replays from the oldest available."""
        await buffer.append('data: {"data":"first"}\n\n')
        await buffer.append('data: {"data":"second"}\n\n')
        await buffer.end_stream()

        events = []
        async for event in buffer.subscribe(last_event_id="nonexistent-id"):
            events.append(event)

        assert len(events) == 2


class TestGlobalStreamRegistry:
    @pytest.mark.asyncio
    async def test_get_or_create(self) -> None:
        registry = GlobalStreamRegistry()
        buf = await registry.get_or_create("run-1")
        assert isinstance(buf, ResilientStreamBuffer)
        buf2 = await registry.get_or_create("run-1")
        assert buf is buf2

    @pytest.mark.asyncio
    async def test_has_buffer(self) -> None:
        registry = GlobalStreamRegistry()
        assert not await registry.has_buffer("run-2")
        await registry.get_or_create("run-2")
        assert await registry.has_buffer("run-2")

    @pytest.mark.asyncio
    async def test_remove(self) -> None:
        registry = GlobalStreamRegistry()
        await registry.get_or_create("run-3")
        await registry.remove("run-3")
        assert not await registry.has_buffer("run-3")
