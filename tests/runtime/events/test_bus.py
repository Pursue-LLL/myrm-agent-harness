import asyncio

import pytest

from myrm_agent_harness.runtime.events.bus import BaseEvent, EventBus


class MockEventA(BaseEvent):
    def __init__(self, message: str):
        self.message = message


class MockEventB(BaseEvent):
    def __init__(self, value: int):
        self.value = value


@pytest.fixture
def event_bus():
    bus = EventBus()
    bus.start()
    yield bus
    # Ensure it's stopped after test
    asyncio.run(bus.stop(timeout=1.0))


@pytest.mark.asyncio
async def test_event_bus_publish_subscribe(event_bus: EventBus):
    received_a = []
    received_b = []

    async def handler_a(event: MockEventA):
        received_a.append(event.message)

    async def handler_b(event: MockEventB):
        received_b.append(event.value)

    event_bus.subscribe(MockEventA, handler_a)
    event_bus.subscribe(MockEventB, handler_b)

    event_bus.publish(MockEventA("hello"))
    event_bus.publish(MockEventB(42))
    event_bus.publish(MockEventA("world"))

    # Yield control to allow tasks to run
    await asyncio.sleep(0.01)

    assert received_a == ["hello", "world"]
    assert received_b == [42]


@pytest.mark.asyncio
async def test_event_bus_multiple_handlers(event_bus: EventBus):
    count1 = 0
    count2 = 0

    async def handler1(event: MockEventA):
        nonlocal count1
        count1 += 1

    async def handler2(event: MockEventA):
        nonlocal count2
        count2 += 1

    event_bus.subscribe(MockEventA, handler1)
    event_bus.subscribe(MockEventA, handler2)

    event_bus.publish(MockEventA("test"))

    await asyncio.sleep(0.01)

    assert count1 == 1
    assert count2 == 1


@pytest.mark.asyncio
async def test_event_bus_handler_error_isolation(event_bus: EventBus):
    received = []

    async def failing_handler(event: MockEventA):
        raise ValueError("Simulated failure")

    async def successful_handler(event: MockEventA):
        received.append(event.message)

    event_bus.subscribe(MockEventA, failing_handler)
    event_bus.subscribe(MockEventA, successful_handler)

    event_bus.publish(MockEventA("test"))

    await asyncio.sleep(0.01)

    # The successful handler should still run even if the failing one crashes
    assert received == ["test"]


@pytest.mark.asyncio
async def test_event_bus_graceful_shutdown():
    bus = EventBus()
    bus.start()

    completed = False

    async def slow_handler(event: MockEventA):
        nonlocal completed
        await asyncio.sleep(0.1)
        completed = True

    bus.subscribe(MockEventA, slow_handler)
    bus.publish(MockEventA("test"))

    # Stop the bus, it should wait for the slow_handler to complete
    await bus.stop(timeout=1.0)

    assert completed is True


@pytest.mark.asyncio
async def test_event_bus_ignore_publish_when_stopped():
    bus = EventBus()
    bus.start()

    received = []

    async def handler(event: MockEventA):
        received.append(event.message)

    bus.subscribe(MockEventA, handler)

    await bus.stop()

    # This should be ignored
    bus.publish(MockEventA("test"))

    await asyncio.sleep(0.01)
    assert len(received) == 0
