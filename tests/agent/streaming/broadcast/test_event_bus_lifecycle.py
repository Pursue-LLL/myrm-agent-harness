"""Unit tests for ToolBroadcastBus lifecycle, batch publish, and subscriber isolation."""

from __future__ import annotations

import asyncio
import time

import pytest

from myrm_agent_harness.agent.streaming.broadcast.event_bus import ToolBroadcastBus
from myrm_agent_harness.agent.streaming.broadcast.types import ToolCallEventData


def _event(tool_name: str = "test_tool") -> ToolCallEventData:
    now = time.time()
    return ToolCallEventData(
        tool_name=tool_name,
        status="completed",
        start_time=now,
        end_time=now,
        duration_ms=1,
        result="ok",
    )


@pytest.fixture
async def fresh_bus() -> ToolBroadcastBus:
    ToolBroadcastBus._instance = None
    bus = ToolBroadcastBus(maxsize=2)
    await bus.start()
    yield bus
    await bus.stop()
    ToolBroadcastBus._instance = None


@pytest.mark.asyncio
async def test_start_is_idempotent() -> None:
    ToolBroadcastBus._instance = None
    bus = ToolBroadcastBus()
    await bus.start()
    await bus.start()
    assert bus._running is True
    await bus.stop()
    ToolBroadcastBus._instance = None


@pytest.mark.asyncio
async def test_stop_is_idempotent() -> None:
    ToolBroadcastBus._instance = None
    bus = ToolBroadcastBus()
    await bus.stop()
    await bus.start()
    await bus.stop()
    await bus.stop()
    ToolBroadcastBus._instance = None


@pytest.mark.asyncio
async def test_publish_batch(fresh_bus: ToolBroadcastBus) -> None:
    received: list[str] = []

    async def collector(event: ToolCallEventData) -> None:
        received.append(event.tool_name)

    fresh_bus.subscribe(collector)
    await fresh_bus.publish_batch([_event("a"), _event("b")])
    await asyncio.sleep(0.3)
    fresh_bus.unsubscribe(collector)
    assert "a" in received
    assert "b" in received


@pytest.mark.asyncio
async def test_queue_overflow_increments_dropped_count(fresh_bus: ToolBroadcastBus) -> None:
    assert fresh_bus.get_dropped_count() == 0
    await fresh_bus.publish(_event("fill-1"))
    await fresh_bus.publish(_event("fill-2"))
    await fresh_bus.publish(_event("overflow"))
    assert fresh_bus.get_dropped_count() >= 1


@pytest.mark.asyncio
async def test_failing_subscriber_does_not_break_dispatch(fresh_bus: ToolBroadcastBus) -> None:
    good_events: list[str] = []

    async def bad(_event: ToolCallEventData) -> None:
        raise RuntimeError("subscriber boom")

    async def good(event: ToolCallEventData) -> None:
        good_events.append(event.tool_name)

    fresh_bus.subscribe(bad)
    fresh_bus.subscribe(good)
    await fresh_bus.publish(_event("survives"))
    await asyncio.sleep(0.3)
    fresh_bus.unsubscribe(bad)
    fresh_bus.unsubscribe(good)
    assert good_events == ["survives"]


@pytest.mark.asyncio
async def test_publish_with_no_subscribers(fresh_bus: ToolBroadcastBus) -> None:
    await fresh_bus.publish(_event("no-subscribers"))
