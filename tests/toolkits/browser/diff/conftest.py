"""Shared fixtures for browser diff integration tests."""

import asyncio

import pytest
from patchright.async_api import BrowserContext

from myrm_agent_harness.toolkits.browser.pool.browser_pool import ContextType, GlobalBrowserPool

_shared_pool: GlobalBrowserPool | None = None
_shared_context: BrowserContext | None = None
_shared_page_key: tuple | None = None


@pytest.fixture(scope="session")
def browser_context():
    """Shared browser context for all integration tests."""
    global _shared_pool, _shared_context, _shared_page_key

    async def setup():
        global _shared_pool, _shared_context, _shared_page_key
        _shared_pool = GlobalBrowserPool()
        await _shared_pool.warmup(browsers=1, pages_per_context=1)
        page, ctx_key = await _shared_pool.acquire_page(ContextType.AGENT)
        _shared_context = page.context
        _shared_page_key = (page, ctx_key)

    async def teardown():
        global _shared_pool, _shared_page_key
        if _shared_pool and _shared_page_key:
            page, ctx_key = _shared_page_key
            await _shared_pool.release_page(page, ctx_key)
            await _shared_pool.shutdown()

    asyncio.run(setup())
    yield _shared_context
    asyncio.run(teardown())
