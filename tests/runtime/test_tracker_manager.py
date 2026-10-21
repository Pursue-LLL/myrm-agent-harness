"""Tests for TrackerManager generic singleton."""

from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.context.tracker_manager import TrackerManager


class FakeTracker:
    def __init__(self, value: int) -> None:
        self.value = value


@pytest.fixture
def call_count() -> list[int]:
    return [0]


@pytest.fixture
def manager(call_count: list[int]) -> TrackerManager[FakeTracker]:
    async def factory() -> FakeTracker:
        call_count[0] += 1
        return FakeTracker(value=42)

    return TrackerManager(factory)


@pytest.mark.asyncio
async def test_get_instance_creates_once(manager: TrackerManager[FakeTracker], call_count: list[int]) -> None:
    instance1 = await manager.get_instance()
    instance2 = await manager.get_instance()

    assert instance1 is instance2
    assert instance1.value == 42
    assert call_count[0] == 1


@pytest.mark.asyncio
async def test_reset_allows_recreation(manager: TrackerManager[FakeTracker], call_count: list[int]) -> None:
    instance1 = await manager.get_instance()
    await manager.reset()
    instance2 = await manager.get_instance()

    assert instance1 is not instance2
    assert call_count[0] == 2


@pytest.mark.asyncio
async def test_concurrent_get_instance(manager: TrackerManager[FakeTracker], call_count: list[int]) -> None:
    import asyncio

    results = await asyncio.gather(*[manager.get_instance() for _ in range(10)])

    assert all(r is results[0] for r in results)
    assert call_count[0] == 1
