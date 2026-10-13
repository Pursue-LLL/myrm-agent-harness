"""A cancelled or failed `acquire_page` leaves the pool exactly as it found it.

Each test cancels the acquisition at one named suspension point of the real `GlobalBrowserPool`
(only the browser itself is a double) and then checks conservation: every permit is back, no page
is parked as busy, and no counter claims a page nobody holds. A leak here is permanent, because
the pool is a process-wide singleton whose permit count is never reconciled.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.pool import page_pool as page_pool_module
from myrm_agent_harness.toolkits.browser.pool.browser_launcher import BrowserInstance
from myrm_agent_harness.toolkits.browser.pool.config import BrowserPoolConfig
from myrm_agent_harness.toolkits.browser.pool.page_pool import PagePool
from myrm_agent_harness.toolkits.browser.utils import page_health
from tests.toolkits.browser._fake_pages import FakeCdp, FakePage

_LIMIT = 2
_KEY = "ctx"
_BOUND_S = 2.0


@dataclass
class Rig:
    pool: GlobalBrowserPool
    inst: BrowserInstance
    page_pool: PagePool

    def assert_conserved(self) -> None:
        assert self.pool._global_semaphore._value == _LIMIT, "permit leaked or over-released"
        assert self.pool._current_pages_in_use == 0
        assert self.inst.load == 0
        assert not self.page_pool._busy, "a page is parked as busy that nobody holds"


class GateLock:
    """Pool lock that makes one chosen task wait at `async with`, as under real contention."""

    def __init__(self, inner: asyncio.Lock) -> None:
        self._inner = inner
        self.blocked_task: asyncio.Task[object] | None = None
        self.entered_wait = asyncio.Event()
        self._open = asyncio.Event()

    async def __aenter__(self) -> None:
        if self.blocked_task is asyncio.current_task():
            self.entered_wait.set()
            await self._open.wait()
        await self._inner.acquire()

    async def __aexit__(self, *_exc: object) -> None:
        self._inner.release()


@pytest.fixture(autouse=True)
def _short_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(page_health, "_PROBE_TIMEOUT_S", 0.2)
    monkeypatch.setattr(page_health, "_CLOSE_TIMEOUT_S", 0.2)


@pytest.fixture
def rig(monkeypatch: pytest.MonkeyPatch) -> Rig:
    pool = GlobalBrowserPool(max_browsers=1, config=BrowserPoolConfig(max_concurrent_pages=_LIMIT))
    context = MagicMock()
    context.new_page = AsyncMock(side_effect=lambda: FakePage(cdp=FakeCdp()))
    page_pool = PagePool(context, max_size=5)
    inst = BrowserInstance(browser=MagicMock(), contexts={_KEY: context}, page_pools={_KEY: page_pool})
    pool._browsers.append(inst)
    monkeypatch.setattr(pool, "_get_least_loaded_browser", AsyncMock(return_value=inst))
    monkeypatch.setattr(pool, "_ensure_lifecycle_loop", MagicMock())
    monkeypatch.setattr(pool._memory_guard, "check_memory", AsyncMock())
    return Rig(pool, inst, page_pool)


async def _take(rig: Rig) -> tuple[FakePage, str]:
    """Acquire through the pool under test (its browser is a double, so no real browser starts)."""
    return await rig.pool.acquire_page(ContextType.AGENT, context_key=_KEY)


def _acquire(rig: Rig) -> asyncio.Task[tuple[FakePage, str]]:
    return asyncio.ensure_future(_take(rig))


async def _cancel(task: asyncio.Task[object]) -> None:
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_completed_acquisition_is_counted_and_fully_returned_by_release(rig: Rig) -> None:
    page, key = await _take(rig)

    assert rig.pool._global_semaphore._value == _LIMIT - 1
    assert rig.pool._current_pages_in_use == 1
    assert rig.inst.load == 1

    await rig.pool.release_page(page, key)

    rig.assert_conserved()


async def test_cancellation_while_waiting_for_a_permit_does_not_grow_the_pool(rig: Rig) -> None:
    held = [await _take(rig) for _ in range(_LIMIT)]
    waiting = _acquire(rig)
    await asyncio.sleep(0.05)
    assert not waiting.done(), "the pool is full, so the acquisition must wait"

    await _cancel(waiting)
    for page, key in held:
        await rig.pool.release_page(page, key)

    rig.assert_conserved()


async def test_cancellations_before_a_page_exists_cannot_exhaust_the_pool(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stop during cold start (browser launching) once per permit used to lock the pool for good."""
    launching = asyncio.Event()
    never = asyncio.Event()

    async def launch() -> None:
        launching.set()
        await never.wait()

    monkeypatch.setattr(rig.pool._memory_guard, "check_memory", launch)
    for _ in range(_LIMIT):
        launching.clear()
        task = _acquire(rig)
        await asyncio.wait_for(launching.wait(), timeout=_BOUND_S)
        await _cancel(task)
    never.set()

    page, key = await asyncio.wait_for(_take(rig), timeout=_BOUND_S)
    await rig.pool.release_page(page, key)
    rig.assert_conserved()


async def test_cancellation_while_an_idle_page_is_reset_closes_the_page_that_was_taken(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(page_pool_module, "_ACQUIRE_RESET_BUDGET_S", 30.0)
    first, key = await _take(rig)
    await rig.pool.release_page(first, key)
    resetting = asyncio.Event()

    async def slow_reset(_page: object) -> None:
        resetting.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(rig.page_pool, "_reset_page", slow_reset)
    task = _acquire(rig)
    await asyncio.wait_for(resetting.wait(), timeout=_BOUND_S)

    await _cancel(task)

    assert first.close_calls == 1, "the page left the idle list, so nothing else would ever close it"
    assert first not in rig.page_pool._idle
    rig.assert_conserved()


async def test_cancellation_while_waiting_for_the_pool_lock_hands_the_taken_page_back(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = GateLock(rig.pool._lock)
    rig.pool._lock = gate  # type: ignore[assignment]
    real_register = rig.pool._register_page_crash_handler

    def register_then_contend(page: FakePage, inst: BrowserInstance) -> None:
        real_register(page, inst)
        gate.blocked_task = asyncio.current_task()  # the next lock entry (counting the page) must wait

    monkeypatch.setattr(rig.pool, "_register_page_crash_handler", register_then_contend)
    task = _acquire(rig)
    await asyncio.wait_for(gate.entered_wait.wait(), timeout=_BOUND_S)
    assert len(rig.page_pool._busy) == 1, "the page is taken but not yet counted"

    await _cancel(task)

    assert len(rig.page_pool._idle) == 1, "the page returns to its pool for reuse"
    rig.assert_conserved()


async def test_failure_after_the_page_was_taken_hands_it_back_with_the_permit(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rig.pool, "_register_page_crash_handler", MagicMock(side_effect=RuntimeError("no listener")))

    with pytest.raises(RuntimeError, match="no listener"):
        await _take(rig)

    assert len(rig.page_pool._idle) == 1
    rig.assert_conserved()


async def test_page_that_crashed_while_held_does_not_return_its_permit_twice(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = GateLock(rig.pool._lock)
    rig.pool._lock = gate  # type: ignore[assignment]

    def register_then_contend(page: FakePage, _inst: BrowserInstance) -> None:
        gate.blocked_task = asyncio.current_task()

    monkeypatch.setattr(rig.pool, "_register_page_crash_handler", register_then_contend)
    task = _acquire(rig)
    await asyncio.wait_for(gate.entered_wait.wait(), timeout=_BOUND_S)
    (held,) = rig.page_pool._busy
    await rig.pool._handle_page_crashed(held, rig.inst)  # the crash handler returns the permit itself
    held.closed = True

    await _cancel(task)

    assert rig.pool._crash_handled_pages == set()
    rig.assert_conserved()
    assert not rig.page_pool._idle, "a crashed page is dropped, not pooled"
