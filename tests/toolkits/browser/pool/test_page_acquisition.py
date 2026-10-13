"""PageAcquisition returns whatever an interrupted acquisition still holds, and never more.

The permit semaphore is process-wide and never reconciled, so every path must leave exactly
the permits it found: a leaked one shrinks the pool for good, a double release grows it.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.pool.page_acquisition import PageAcquisition

_LIMIT = 2
_BOUND_S = 2.0


def _acquisition(semaphore: asyncio.Semaphore, crash_handled: set[int] | None = None) -> PageAcquisition:
    return PageAcquisition(semaphore, set() if crash_handled is None else crash_handled)


def _page_pool() -> MagicMock:
    page_pool = MagicMock()
    page_pool.release = AsyncMock()
    return page_pool


async def test_committed_acquisition_keeps_the_permit_and_the_page() -> None:
    semaphore, page_pool, page = asyncio.Semaphore(_LIMIT), _page_pool(), MagicMock()

    async with _acquisition(semaphore) as claim:
        claim.hold(page_pool, page)
        claim.commit()

    assert semaphore._value == _LIMIT - 1, "release_page owns the permit from here on"
    page_pool.release.assert_not_awaited()


async def test_failure_after_commit_leaves_ownership_with_release_page() -> None:
    semaphore, page_pool, page = asyncio.Semaphore(_LIMIT), _page_pool(), MagicMock()

    with pytest.raises(RuntimeError, match="late"):
        async with _acquisition(semaphore) as claim:
            claim.hold(page_pool, page)
            claim.commit()
            raise RuntimeError("late")

    assert semaphore._value == _LIMIT - 1
    page_pool.release.assert_not_awaited()


async def test_failure_before_any_page_returns_only_the_permit() -> None:
    semaphore = asyncio.Semaphore(_LIMIT)

    with pytest.raises(RuntimeError, match="no page"):
        async with _acquisition(semaphore):
            raise RuntimeError("no page")

    assert semaphore._value == _LIMIT


async def test_uncounted_page_is_handed_back_with_the_permit() -> None:
    semaphore, page_pool, page = asyncio.Semaphore(_LIMIT), _page_pool(), MagicMock()

    with pytest.raises(RuntimeError, match="uncounted"):
        async with _acquisition(semaphore) as claim:
            claim.hold(page_pool, page)
            raise RuntimeError("uncounted")

    page_pool.release.assert_awaited_once_with(page)
    assert semaphore._value == _LIMIT


async def test_cancellation_while_waiting_for_a_permit_takes_and_returns_nothing() -> None:
    semaphore = asyncio.Semaphore(1)
    await semaphore.acquire()  # the pool is full

    async def acquire() -> None:
        async with _acquisition(semaphore):
            pytest.fail("a full pool must not admit the acquisition")

    waiting = asyncio.create_task(acquire())
    await asyncio.sleep(0)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    semaphore.release()

    assert semaphore._value == 1, "returning a permit that was never taken would grow the pool"


async def test_permit_already_returned_by_the_crash_handler_is_not_returned_twice() -> None:
    semaphore, page_pool, page = asyncio.Semaphore(_LIMIT), _page_pool(), MagicMock()
    crash_handled: set[int] = set()

    with pytest.raises(RuntimeError, match="crashed"):
        async with _acquisition(semaphore, crash_handled) as claim:
            claim.hold(page_pool, page)
            crash_handled.add(id(page))  # what the crash handler records ...
            semaphore.release()  # ... after returning the permit itself
            raise RuntimeError("crashed")

    assert semaphore._value == _LIMIT
    assert crash_handled == set(), "the marker is consumed so a reused id cannot skip a later permit"


async def test_pool_that_cannot_take_the_page_back_still_returns_the_permit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    semaphore, page_pool, page = asyncio.Semaphore(_LIMIT), _page_pool(), MagicMock()
    page_pool.release.side_effect = RuntimeError("pool broken")

    with caplog.at_level(logging.WARNING), pytest.raises(ValueError, match="original"):
        async with _acquisition(semaphore) as claim:
            claim.hold(page_pool, page)
            raise ValueError("original")

    assert semaphore._value == _LIMIT
    assert "could not hand back" in caplog.text


async def test_second_cancellation_while_handing_the_page_back_still_returns_the_permit() -> None:
    semaphore, page_pool, page = asyncio.Semaphore(_LIMIT), _page_pool(), MagicMock()
    handing_back = asyncio.Event()

    async def slow_release(_page: object) -> None:
        handing_back.set()
        await asyncio.Event().wait()

    page_pool.release.side_effect = slow_release

    async def acquire() -> None:
        async with _acquisition(semaphore) as claim:
            claim.hold(page_pool, page)
            await asyncio.Event().wait()

    task = asyncio.create_task(acquire())
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.wait_for(handing_back.wait(), timeout=_BOUND_S)
    task.cancel()  # a watchdog cancelling the same task again
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=_BOUND_S)

    assert semaphore._value == _LIMIT
