"""Unit tests for CrashWatchdogMixin: event registration, page crash, lifecycle tick, and close paths.

Covers the error-handling paths of `crash_watchdog.py` that are not exercised by the
pool-level integration tests in `test_browser_launcher_cdp.py`:
- event-registration callbacks (disconnect / page crash)
- idempotent disconnect and circuit-breaker failure recording
- page-crash semaphore release and busy-page cleanup
- lifecycle tick with no browsers, already-disconnected instances, and idle eviction
- liveness-probe CancelledError propagation and top-level fallback
- graceful resource close on browser instances
"""

from __future__ import annotations

import asyncio
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.pool import GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.pool.browser_launcher import BrowserInstance


def _mock_browser() -> MagicMock:
    browser = MagicMock()
    browser.contexts = []
    browser.on = MagicMock()
    browser.close = AsyncMock()
    return browser


def _alive_page() -> MagicMock:
    page = MagicMock()
    page.evaluate = AsyncMock(return_value=True)
    page.on = MagicMock()
    return page


def _browser_mock(inst: BrowserInstance) -> MagicMock:
    return cast(MagicMock, inst.browser)


def _page_pool_mock(inst: BrowserInstance) -> MagicMock:
    return cast(MagicMock, inst.page_pools["agent"])


def _inst_with_pool(
    pool: GlobalBrowserPool,
    is_managed: bool = True,
    load: int = 1,
    busy: set[MagicMock] | None = None,
    idle: list[MagicMock] | None = None,
) -> BrowserInstance:
    browser = _mock_browser()
    inst = BrowserInstance(browser=browser, is_managed=is_managed)
    inst.load = load
    page_pool = MagicMock(shutdown=AsyncMock())
    page_pool._busy = busy if busy is not None else {_alive_page()}
    page_pool._idle = idle if idle is not None else []
    inst.page_pools = {"agent": page_pool}
    pool._browsers.append(inst)
    pool._current_pages_in_use = load
    return inst


@pytest.mark.asyncio
async def test_register_disconnect_handler_invokes_callback() -> None:
    """Registering the disconnect handler must invoke the callback on browser disconnect."""
    pool = GlobalBrowserPool(max_browsers=2)
    inst = _inst_with_pool(pool)

    pool._register_disconnect_handler(inst)
    browser = _browser_mock(inst)
    assert browser.on.call_count == 1
    event, callback = browser.on.call_args.args

    assert event == "disconnected"
    callback(inst.browser)  # sync callback schedules a crash-handling task

    await asyncio.sleep(0.05)  # let the created task run
    assert inst not in pool._browsers
    await pool.shutdown()


@pytest.mark.asyncio
async def test_disconnect_handling_is_idempotent() -> None:
    """A second disconnect call must be a no-op (semaphore released exactly once)."""
    pool = GlobalBrowserPool(max_browsers=2)
    inst = _inst_with_pool(pool, load=2)
    pool._global_semaphore = asyncio.Semaphore(10)

    await pool._handle_browser_disconnected(inst)
    # Mark disconnected now so the second call hits the idempotency guard.
    inst._disconnected = True
    await pool._handle_browser_disconnected(inst)

    assert pool._global_semaphore._value == 12  # exactly one release of 2 slots
    await pool.shutdown()


@pytest.mark.asyncio
async def test_a_close_the_pool_started_is_not_a_crash_but_still_returns_its_slots() -> None:
    """An expected close is routine: no crash count, yet the held permits still come back."""
    pool = GlobalBrowserPool(max_browsers=2)
    pool._global_semaphore = asyncio.Semaphore(10)
    inst = _inst_with_pool(pool, is_managed=True, load=2)
    inst.expected_close = True

    await pool._handle_browser_disconnected(inst)

    assert pool._crash_count_browser == 0
    assert pool._global_semaphore._value == 12
    assert inst not in pool._browsers
    await pool.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("expected_close", [False, True])
async def test_a_disconnected_browser_is_cleaned_up_whether_it_crashed_or_was_closed_on_purpose(
    expected_close: bool,
) -> None:
    pool = GlobalBrowserPool(max_browsers=2)
    inst = _inst_with_pool(pool, is_managed=True)
    inst.expected_close = expected_close

    await pool._handle_browser_disconnected(inst)

    _page_pool_mock(inst).shutdown.assert_awaited_once()
    _browser_mock(inst).close.assert_awaited_once()
    await pool.shutdown()


@pytest.mark.asyncio
async def test_a_managed_disconnect_nobody_asked_for_is_a_crash() -> None:
    pool = GlobalBrowserPool(max_browsers=2)
    inst = _inst_with_pool(pool, is_managed=True)

    await pool._handle_browser_disconnected(inst)

    assert pool._crash_count_browser == 1
    await pool.shutdown()


@pytest.mark.asyncio
async def test_register_page_crash_handler_and_handle_page_crashed() -> None:
    """Page crash handler must release one semaphore slot and drop the page from busy pools."""
    pool = GlobalBrowserPool(max_browsers=2)
    pool._global_semaphore = asyncio.Semaphore(10)
    page = MagicMock()
    page.on = MagicMock()
    inst = _inst_with_pool(pool, busy={page})

    pool._register_page_crash_handler(page, inst)
    assert page.on.call_count == 1
    event, callback = page.on.call_args.args
    assert event == "crash"

    callback(page)
    await asyncio.sleep(0.05)
    assert pool._crash_count_page == 1
    assert inst.load == 0
    assert page not in inst.page_pools["agent"]._busy
    assert pool._global_semaphore._value == 11  # released exactly one slot

    # Second crash callback is idempotent: page_id already handled -> no-op.
    pool._crash_count_page = 0
    callback(page)
    await asyncio.sleep(0.05)
    assert pool._crash_count_page == 0  # not double-counted
    await pool.shutdown()


@pytest.mark.asyncio
async def test_idle_page_crash_is_ignored_because_it_holds_no_permit() -> None:
    """A page crashing while idle in its pool owns no permit: none is returned and no marker is left behind."""
    pool = GlobalBrowserPool(max_browsers=2)
    pool._global_semaphore = asyncio.Semaphore(10)
    idle_page = MagicMock()
    # The default busy page stands for a page a caller holds: it must stay accounted for.
    inst = _inst_with_pool(pool, load=1, idle=[idle_page])

    await pool._handle_page_crashed(idle_page, inst)

    assert pool._crash_count_page == 0
    assert not pool._crash_handled_pages
    assert inst.load == 1
    assert pool._current_pages_in_use == 1
    assert pool._global_semaphore._value == 10
    await pool.shutdown()


@pytest.mark.asyncio
async def test_crash_event_after_release_does_not_return_the_permit_twice() -> None:
    """The owner returned the permit with the page; a crash event reaching the handler later must not return it again."""
    pool = GlobalBrowserPool(max_browsers=2)
    pool._global_semaphore = asyncio.Semaphore(9)  # one of ten permits is held by the page below
    page = MagicMock()
    inst = _inst_with_pool(pool, busy={page})
    page_pool = _page_pool_mock(inst)
    page_pool.release = AsyncMock(side_effect=page_pool._busy.discard)

    await pool.release_page(page, "agent")
    assert pool._global_semaphore._value == 10

    await pool._handle_page_crashed(page, inst)

    assert pool._global_semaphore._value == 10
    assert pool._crash_count_page == 0
    assert not pool._crash_handled_pages
    await pool.shutdown()


@pytest.mark.asyncio
async def test_handle_page_crashed_noop_when_browser_disconnected() -> None:
    """A page crash on an already-disconnected browser must be a no-op."""
    pool = GlobalBrowserPool(max_browsers=2)
    pool._global_semaphore = asyncio.Semaphore(10)
    page = MagicMock()
    inst = _inst_with_pool(pool, busy={page})
    inst._disconnected = True  # browser already handled by the L1 flow

    await pool._handle_page_crashed(page, inst)

    assert pool._crash_count_page == 0
    assert inst.load == 1  # untouched
    assert pool._global_semaphore._value == 10  # no slot released
    await pool.shutdown()


@pytest.mark.asyncio
async def test_lifecycle_tick_with_no_browsers_is_noop() -> None:
    """Lifecycle tick with an empty pool must return immediately."""
    pool = GlobalBrowserPool(max_browsers=2)
    await pool._lifecycle_tick()  # no browsers -> early return
    await pool.shutdown()


@pytest.mark.asyncio
async def test_lifecycle_tick_skips_disconnected_and_evicts_idle() -> None:
    """Lifecycle tick must skip already-disconnected instances and evict idle browsers."""
    import dataclasses

    pool = GlobalBrowserPool(max_browsers=4)
    pool._config = dataclasses.replace(pool._config, idle_timeout_seconds=1)

    dead = _inst_with_pool(pool, is_managed=False, load=1)
    dead._disconnected = True  # already handled elsewhere -> skipped

    idle = _inst_with_pool(pool, load=0)
    idle.last_active_at = 0.0  # older than the 1s timeout -> idle eviction

    ext_dead = _inst_with_pool(pool, is_managed=False, load=1)
    page = next(iter(_page_pool_mock(ext_dead)._busy))
    page.evaluate = AsyncMock(side_effect=RuntimeError("target closed"))

    await pool._lifecycle_tick()

    assert dead in pool._browsers  # skipped (already disconnected)
    assert idle not in pool._browsers  # evicted for idle
    assert ext_dead not in pool._browsers  # external dead browser removed
    await pool.shutdown()


@pytest.mark.asyncio
async def test_lifecycle_tick_managed_dead_is_counted_as_a_crash() -> None:
    """A managed browser that fails liveness during the tick is a crash and leaves the pool."""
    pool = GlobalBrowserPool(max_browsers=2)

    page = MagicMock()
    page.evaluate = AsyncMock(side_effect=RuntimeError("target closed"))
    inst = _inst_with_pool(pool, is_managed=True, busy={page})

    before = pool._crash_count_browser

    await pool._lifecycle_tick()

    assert pool._crash_count_browser == before + 1
    assert inst not in pool._browsers
    await pool.shutdown()


@pytest.mark.asyncio
async def test_check_browser_alive_propagates_cancelled_error() -> None:
    """Cancellation during a liveness probe must propagate, never be swallowed."""
    pool = GlobalBrowserPool(max_browsers=2)
    page = MagicMock()
    page.evaluate = AsyncMock(side_effect=asyncio.CancelledError())
    inst = _inst_with_pool(pool, busy={page})

    with pytest.raises(asyncio.CancelledError):
        await pool._check_browser_alive(inst)
    await pool.shutdown()


@pytest.mark.asyncio
async def test_check_browser_alive_falls_back_false_on_outer_error() -> None:
    """Any unexpected error while iterating pools must degrade to 'not alive' (False)."""
    pool = GlobalBrowserPool(max_browsers=2)
    inst = _inst_with_pool(pool)
    bad_pool = MagicMock()
    bad_pool._busy = None  # unpacking raises TypeError -> outer fallback
    bad_pool._idle = None
    inst.page_pools = {"agent": bad_pool}

    assert await pool._check_browser_alive(inst) is False
    await pool.shutdown()


@pytest.mark.asyncio
async def test_pool_close_browser_instance_graceful() -> None:
    """Closing a pool browser instance shuts down pools, contexts, and the browser.

    Exercises ``GlobalBrowserPool._close_browser_instance`` (browser_pool.py),
    the pool-owned close path used by all crash-handling flows.
    """
    pool = GlobalBrowserPool(max_browsers=2)
    inst = _inst_with_pool(pool)
    ctx = AsyncMock()
    inst.contexts = {"default": ctx}

    await pool._close_browser_instance(inst)

    _page_pool_mock(inst).shutdown.assert_called_once()
    ctx.close.assert_awaited_once()
    _browser_mock(inst).close.assert_awaited_once()
    await pool.shutdown()
