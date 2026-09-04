"""Unit tests for BrowserTaskSpace and HarnessTaskSpaceManager in Harness layer."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from myrm_agent_harness.toolkits.browser.spaces import (
    BrowserTaskSpace,
    HarnessTaskSpaceManager,
)


@pytest.mark.asyncio
async def test_browser_task_space_lifecycle() -> None:
    mock_context = AsyncMock()
    mock_context.pages = [MagicMock(), MagicMock()]
    mock_session = AsyncMock()

    space = BrowserTaskSpace(
        space_id="space-alpha",
        name="Research Alpha",
        context=mock_context,
        session=mock_session,
    )

    assert space.space_id == "space-alpha"
    assert space.name == "Research Alpha"
    assert space.is_active is True

    # Check to_dict serialization
    data = space.to_dict()
    assert data["space_id"] == "space-alpha"
    assert data["active_pages"] == 2
    assert data["is_active"] is True

    # Test touch
    old_time = space.last_accessed_at
    time.sleep(0.01)
    space.touch()
    assert space.last_accessed_at > old_time

    # Test close
    await space.close()
    assert space.is_active is False
    assert space.context is None
    assert space.session is None
    mock_session.close.assert_awaited_once()
    mock_context.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_space_manager_creation_and_routing() -> None:
    manager = HarnessTaskSpaceManager(max_active_spaces=3)

    mock_ctx1 = AsyncMock()
    mock_ctx2 = AsyncMock()

    space1 = await manager.get_or_create_space(
        "space-1",
        name="Task One",
        context_factory=AsyncMock(return_value=mock_ctx1),
    )
    space2 = await manager.get_or_create_space(
        "space-2",
        name="Task Two",
        context_factory=AsyncMock(return_value=mock_ctx2),
    )

    assert space1.space_id == "space-1"
    assert space2.space_id == "space-2"
    assert len(manager.list_spaces()) == 2

    # Re-getting space-1 should return existing instance without creating new context
    space1_again = await manager.get_or_create_space("space-1")
    assert space1_again is space1

    # Close single space
    closed = await manager.close_space("space-1")
    assert closed is True
    assert len(manager.list_spaces()) == 1
    assert manager.get_space("space-1") is None

    # Close all
    await manager.close_all()
    assert len(manager.list_spaces()) == 0


@pytest.mark.asyncio
async def test_space_manager_quota_limit_and_idle_prune() -> None:
    # Max 2 active spaces
    manager = HarnessTaskSpaceManager(max_active_spaces=2, default_idle_ttl_seconds=1.0)

    await manager.get_or_create_space("s1")
    await manager.get_or_create_space("s2")
    assert len(manager.list_spaces()) == 2

    # Attempting to allocate s3 immediately should raise quota RuntimeError
    with pytest.raises(RuntimeError, match="Active BrowserTaskSpace limit reached"):
        await manager.get_or_create_space("s3")

    # Manually age space s1
    s1 = manager.get_space("s1")
    assert s1 is not None
    s1.last_accessed_at = time.time() - 2.0  # 2 seconds old, exceeds 1.0s TTL

    # Now allocating s3 should automatically prune s1 and succeed
    s3 = await manager.get_or_create_space("s3")
    assert s3.space_id == "s3"
    assert manager.get_space("s1") is None
    assert len(manager.list_spaces()) == 2


@pytest.mark.asyncio
async def test_space_concurrency_lock() -> None:
    space = BrowserTaskSpace(space_id="locked-space")
    execution_order: list[int] = []

    async def worker(worker_id: int, delay: float) -> None:
        async with space.lock:
            execution_order.append(worker_id)
            await asyncio.sleep(delay)

    # Run two workers concurrently on the same space lock
    await asyncio.gather(
        worker(1, 0.05),
        worker(2, 0.01),
    )

    # Worker 1 was scheduled first, so execution should be serialized [1, 2]
    assert execution_order == [1, 2]


@pytest.mark.asyncio
async def test_space_takeover_forwarding() -> None:
    mock_session = AsyncMock()
    space = BrowserTaskSpace(space_id="takeover-space", session=mock_session)

    await space.pause_for_takeover()
    mock_session.pause_for_takeover.assert_awaited_once()

    await space.resume_from_takeover()
    mock_session.resume_from_takeover.assert_awaited_once()

