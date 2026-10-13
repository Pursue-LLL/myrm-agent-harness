"""A real renderer crash returns a permit only for a page somebody holds.

A page that crashes while idle in the pool owns no permit, and a page that crashes in a caller's
hands has its permit returned exactly once. Both are checked against a real Chromium, because the
permit count is a process-wide singleton that is never reconciled: one wrong return raises the
concurrency limit for good.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

import pytest

from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.pool.config import BrowserPoolConfig
from tests.toolkits.browser._browser_available import chromium_available
from tests.toolkits.browser._page_crash import crash_page

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.skipif(not chromium_available(), reason="Chromium/Patchright not installed in this environment"),
]

_LIMIT = 3
_CONTEXT_KEY = "crash-accounting"


@contextlib.asynccontextmanager
async def _pool() -> AsyncIterator[GlobalBrowserPool]:
    pool = GlobalBrowserPool(max_browsers=1, config=BrowserPoolConfig(max_concurrent_pages=_LIMIT))
    try:
        yield pool
    finally:
        await pool.shutdown()


async def test_idle_page_crash_leaves_the_permit_count_alone() -> None:
    async with _pool() as pool:
        for _ in range(2):
            page, key = await pool.acquire_page(ContextType.AGENT, context_key=_CONTEXT_KEY)
            await pool.release_page(page, key)
            await crash_page(pool, page)

            assert pool._global_semaphore._value == _LIMIT
            assert not pool._crash_handled_pages
            assert pool._crash_count_page == 0

        fresh, key = await pool.acquire_page(ContextType.AGENT, context_key=_CONTEXT_KEY)
        assert fresh is not page, "a crashed idle page must be replaced, not handed out"
        assert await fresh.evaluate("1 + 1") == 2
        assert pool._global_semaphore._value == _LIMIT - 1

        await pool.release_page(fresh, key)
        assert pool._global_semaphore._value == _LIMIT


async def test_held_page_crash_returns_its_permit_exactly_once() -> None:
    async with _pool() as pool:
        page, key = await pool.acquire_page(ContextType.AGENT, context_key=_CONTEXT_KEY)
        assert pool._global_semaphore._value == _LIMIT - 1

        await crash_page(pool, page)
        assert pool._global_semaphore._value == _LIMIT
        assert pool._crash_count_page == 1

        await pool.release_page(page, key)
        assert pool._global_semaphore._value == _LIMIT, "the owner's release must not return the permit again"
        assert not pool._crash_handled_pages
        assert pool._current_pages_in_use == 0
