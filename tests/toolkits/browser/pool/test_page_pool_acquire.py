"""PagePool.acquire hands out only pages that are still usable.

An idle page may have been closed, may have a wedged renderer, or may have lost its target. The
pool replaces such pages instead of returning them, and no page close can hold the pool lock
longer than its bound.
"""

from __future__ import annotations

import asyncio
from typing import Literal
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.pool import page_pool as page_pool_module
from myrm_agent_harness.toolkits.browser.pool.page_pool import PagePool
from myrm_agent_harness.toolkits.browser.utils import page_health

PageState = Literal["healthy", "closed", "reset_hangs", "dead_after_reset", "close_hangs"]


class FakePage:
    """Page double whose behaviour is chosen by `state`."""

    def __init__(self, state: PageState = "healthy") -> None:
        self.state = state
        self.close_calls = 0
        self.reset_calls = 0
        self.context = MagicMock()
        self.context.new_cdp_session = AsyncMock(side_effect=self._new_cdp_session)

    def is_closed(self) -> bool:
        return self.state == "closed"

    async def _new_cdp_session(self, _page: object) -> MagicMock:
        self.reset_calls += 1
        if self.state == "reset_hangs":
            await asyncio.sleep(30)
        cdp = MagicMock()
        cdp.send = AsyncMock()
        cdp.detach = AsyncMock()
        return cdp

    async def goto(self, *_args: object, **_kwargs: object) -> None:
        return None

    async def evaluate(self, _expression: str) -> int:
        if self.state in ("dead_after_reset", "reset_hangs"):
            raise RuntimeError("target closed")
        return 1

    async def close(self) -> None:
        self.close_calls += 1
        if self.state == "close_hangs":
            await asyncio.sleep(30)


def _pool(*pages: FakePage, max_size: int = 5) -> tuple[PagePool, MagicMock]:
    """Pool whose context hands out `pages` in order (then healthy ones)."""
    context = MagicMock()
    queue = list(pages)

    async def new_page() -> FakePage:
        return queue.pop(0) if queue else FakePage()

    context.new_page = AsyncMock(side_effect=new_page)
    return PagePool(context, max_size=max_size), context


@pytest.fixture(autouse=True)
def _short_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(page_pool_module, "_ACQUIRE_RESET_BUDGET_S", 0.2)
    monkeypatch.setattr(page_health, "_PROBE_TIMEOUT_S", 0.2)
    monkeypatch.setattr(page_pool_module, "_CLOSE_TIMEOUT_S", 0.2)


async def test_healthy_idle_page_is_reused() -> None:
    page = FakePage()
    pool, context = _pool(page)

    first = await pool.acquire()
    await pool.release(first)
    second = await pool.acquire()

    assert second is page
    assert context.new_page.await_count == 1


async def test_closed_idle_page_is_skipped() -> None:
    dead, fresh = FakePage(), FakePage()
    pool, _ = _pool(dead, fresh)

    page = await pool.acquire()
    await pool.release(page)
    dead.state = "closed"
    page = await pool.acquire()

    assert page is fresh
    assert page is not dead
    assert dead.close_calls == 0  # nothing to close, the page is already gone


async def test_page_whose_reset_hangs_is_closed_and_replaced() -> None:
    wedged, fresh = FakePage(), FakePage()
    pool, _ = _pool(wedged, fresh)

    page = await pool.acquire()
    await pool.release(page)
    wedged.state = "reset_hangs"
    page = await asyncio.wait_for(pool.acquire(), timeout=5)

    assert page is fresh
    assert wedged.close_calls == 1
    assert wedged not in pool._idle and wedged not in pool._busy


async def test_page_that_dies_during_reset_is_caught_by_the_probe() -> None:
    """Resets swallow their own errors, so only the post-reset probe notices a dead page."""
    dying, fresh = FakePage(), FakePage()
    pool, _ = _pool(dying, fresh)

    page = await pool.acquire()
    await pool.release(page)
    dying.state = "dead_after_reset"
    page = await pool.acquire()

    assert page is fresh
    assert dying.close_calls == 1


async def test_every_bad_idle_page_is_replaced_in_one_acquire() -> None:
    first, second, fresh = FakePage(), FakePage(), FakePage()
    pool, _ = _pool(first, second, fresh)

    a = await pool.acquire()
    b = await pool.acquire()
    await pool.release(a)
    await pool.release(b)
    first.state = "dead_after_reset"
    second.state = "closed"
    page = await pool.acquire()

    assert page is fresh
    assert pool.stats["idle"] == 0
    assert pool.stats["busy"] == 1


async def test_cancellation_during_reset_propagates_instead_of_being_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(page_pool_module, "_ACQUIRE_RESET_BUDGET_S", 30.0)
    wedged = FakePage()
    pool, _ = _pool(wedged)
    page = await pool.acquire()
    await pool.release(page)
    wedged.state = "reset_hangs"

    task = asyncio.create_task(pool.acquire())
    await asyncio.sleep(0.05)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


async def test_overflow_release_close_is_bounded() -> None:
    keep, overflow = FakePage(), FakePage()
    pool, _ = _pool(keep, overflow, max_size=1)
    a = await pool.acquire()
    b = await pool.acquire()
    await pool.release(a)
    overflow.state = "close_hangs"

    await asyncio.wait_for(pool.release(b), timeout=3)

    assert overflow.close_calls == 1


async def test_shutdown_is_bounded_when_a_page_never_closes() -> None:
    stuck, fine = FakePage(), FakePage()
    pool, _ = _pool(stuck, fine)
    await pool.acquire()
    await pool.acquire()
    stuck.state = "close_hangs"

    await asyncio.wait_for(pool.shutdown(), timeout=3)

    assert stuck.close_calls == 1
    assert fine.close_calls == 1


async def test_closed_page_is_dropped_on_release_instead_of_pooled() -> None:
    page = FakePage()
    pool, _ = _pool(page)
    acquired = await pool.acquire()
    acquired.state = "closed"  # e.g. session recovery closed a wedged page before releasing its tab

    await pool.release(acquired)

    assert pool.stats["idle"] == 0
    assert pool.stats["busy"] == 0
    assert page.close_calls == 0
