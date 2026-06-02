"""Integration tests for wait strategies with real browser."""

import pytest

from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.pool.config import BrowserConfig, BrowserMode
from myrm_agent_harness.toolkits.browser.session import BrowserSession

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_hybrid_strategy_fast_page():
    """Test hybrid strategy on fast-loading page."""
    config = BrowserConfig.minimal()
    pool = GlobalBrowserPool(config)

    try:
        await pool.warmup(browsers=1, pages_per_context=1)
        session = BrowserSession(pool, ContextType.AGENT)
        await session.new_tab()

        await session.navigate("about:blank")

        await session.close()
    finally:
        await pool.shutdown()


async def test_networkidle_fallback():
    """Test networkidle fallback strategy."""
    from myrm_agent_harness.toolkits.browser.pool.config import NavigationWaitConfig

    config = BrowserConfig(
        mode=BrowserMode.MINIMAL,
        max_concurrent_pages=10,
        navigation_wait=NavigationWaitConfig(
            wait_timeout_ms=1000,
            strategy="networkidle",
            quiet_ms=500,
        ),
    )
    pool = GlobalBrowserPool(config)

    try:
        await pool.warmup(browsers=1, pages_per_context=1)
        session = BrowserSession(pool, ContextType.AGENT)
        await session.new_tab()

        await session.navigate("about:blank")

        await session.close()
    finally:
        await pool.shutdown()


async def test_dom_stable_strategy():
    """Test DOM stable only strategy."""
    from myrm_agent_harness.toolkits.browser.pool.config import NavigationWaitConfig

    config = BrowserConfig(
        mode=BrowserMode.MINIMAL,
        max_concurrent_pages=10,
        navigation_wait=NavigationWaitConfig(
            wait_timeout_ms=2000,
            strategy="dom_stable",
            quiet_ms=500,
        ),
    )
    pool = GlobalBrowserPool(config)

    try:
        await pool.warmup(browsers=1, pages_per_context=1)
        session = BrowserSession(pool, ContextType.AGENT)
        await session.new_tab()

        await session.navigate("about:blank")

        await session.close()
    finally:
        await pool.shutdown()
