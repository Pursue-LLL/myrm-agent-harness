"""Real-Chromium proof that a browser the pool closes itself is not counted as a crash.

Idle eviction, shutdown and an engine switch all close a browser on purpose, and each close makes the
browser emit `disconnected`, exactly as a dead one does. The control group kills a browser for real
and must still be counted. Run with:
`pytest -m integration tests/toolkits/browser/pool/test_expected_close_accounting.py`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator

import pytest

from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.pool.browser_launcher import BrowserInstance
from myrm_agent_harness.toolkits.browser.session import BrowserSession
from tests.toolkits.browser._browser_available import chromium_available

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.asyncio,
    pytest.mark.skipif(not chromium_available(), reason="Chromium not available"),
]

_CONTEXT_KEY = "expected-close"
_DISCONNECT_TIMEOUT_S = 15.0
_LONG_IDLE_S = 100_000.0


@pytest.fixture
async def pool() -> AsyncIterator[GlobalBrowserPool]:
    browser_pool = GlobalBrowserPool(max_browsers=1)
    yield browser_pool
    with contextlib.suppress(Exception):
        await asyncio.wait_for(browser_pool.shutdown(), timeout=20.0)


async def _open_browser(pool: GlobalBrowserPool) -> BrowserInstance:
    """Launch a browser and leave it idle (its page released)."""
    page, key = await pool.acquire_page(ContextType.AGENT, context_key=_CONTEXT_KEY)
    await pool.release_page(page, key)
    return pool._browsers[0]


async def _disconnect_handled(pool: GlobalBrowserPool, inst: BrowserInstance) -> None:
    """Wait until the pool's `disconnected` handler has run for `inst`."""
    async with asyncio.timeout(_DISCONNECT_TIMEOUT_S):
        while not inst._disconnected:
            await asyncio.sleep(0.05)
        await asyncio.gather(*pool._crash_tasks)


async def test_idle_eviction_is_not_a_crash(pool: GlobalBrowserPool, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    inst = await _open_browser(pool)
    inst.last_active_at = time.monotonic() - _LONG_IDLE_S

    await pool._lifecycle_tick()
    await _disconnect_handled(pool, inst)

    assert inst not in pool._browsers
    assert pool._crash_count_browser == 0
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING and "crashed" in r.getMessage()]


async def test_shutdown_is_not_a_crash(pool: GlobalBrowserPool) -> None:
    inst = await _open_browser(pool)

    await pool.shutdown()
    await _disconnect_handled(pool, inst)

    assert pool._crash_count_browser == 0


async def test_an_engine_restart_that_empties_a_browser_is_not_a_crash(pool: GlobalBrowserPool) -> None:
    session = BrowserSession(pool, ContextType.AGENT, context_key=_CONTEXT_KEY, allow_private_networks=True)
    await session.new_tab()
    inst = pool._browsers[0]

    await session.restart(restore_url=False)
    await _disconnect_handled(pool, inst)

    assert pool._crash_count_browser == 0
    await session.close()


async def test_control_a_browser_that_really_dies_is_counted_as_a_crash(pool: GlobalBrowserPool) -> None:
    inst = await _open_browser(pool)
    cdp = await inst.browser.new_browser_cdp_session()

    killer = asyncio.create_task(cdp.send("Browser.crash"))  # never answered: the browser dies mid-command
    await _disconnect_handled(pool, inst)
    killer.cancel()
    with contextlib.suppress(BaseException):
        await killer

    assert pool._crash_count_browser == 1
