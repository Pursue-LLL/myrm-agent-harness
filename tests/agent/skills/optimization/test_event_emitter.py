from typing import Any

import pytest

from myrm_agent_harness.agent.skills.optimization.event_emitter import EventEmitter


@pytest.fixture
def emitter() -> EventEmitter:
    return EventEmitter()


@pytest.mark.asyncio
async def test_event_emitter_on_and_emit(emitter: EventEmitter) -> None:
    received = []

    async def callback(event: str, payload: dict[str, Any]) -> None:
        received.append((event, payload))

    emitter.on("test_event", callback)
    assert emitter.listener_count("test_event") == 1
    assert emitter.listener_count() == 1
    assert "test_event" in emitter.events()

    await emitter.emit("test_event", {"key": "value"})

    assert len(received) == 1
    assert received[0] == ("test_event", {"key": "value"})


@pytest.mark.asyncio
async def test_event_emitter_off(emitter: EventEmitter) -> None:
    async def callback(event: str, payload: dict[str, Any]) -> None:
        pass

    emitter.on("test_event", callback)
    assert emitter.listener_count("test_event") == 1

    emitter.off("test_event", callback)
    assert emitter.listener_count("test_event") == 0

    await emitter.emit("test_event", {"key": "value"})


@pytest.mark.asyncio
async def test_event_emitter_off_all(emitter: EventEmitter) -> None:
    async def callback1(event: str, payload: dict[str, Any]) -> None:
        pass

    async def callback2(event: str, payload: dict[str, Any]) -> None:
        pass

    emitter.on("event1", callback1)
    emitter.on("event2", callback2)
    assert emitter.listener_count() == 2

    emitter.off_all("event1")
    assert emitter.listener_count("event1") == 0
    assert emitter.listener_count("event2") == 1

    emitter.off_all()
    assert emitter.listener_count() == 0


@pytest.mark.asyncio
async def test_event_emitter_error_isolation(emitter: EventEmitter) -> None:
    received = []

    async def callback_error(event: str, payload: dict[str, Any]) -> None:
        raise ValueError("Test error")

    async def callback_success(event: str, payload: dict[str, Any]) -> None:
        received.append(payload)

    emitter.on("test_event", callback_error)
    emitter.on("test_event", callback_success)

    # Should not raise exception
    await emitter.emit("test_event", {"data": 1})

    # The successful callback should still run
    assert len(received) == 1
    assert received[0] == {"data": 1}


@pytest.mark.asyncio
async def test_event_emitter_emit_no_listeners(emitter: EventEmitter) -> None:
    # Should just return without error
    await emitter.emit("non_existent_event")
