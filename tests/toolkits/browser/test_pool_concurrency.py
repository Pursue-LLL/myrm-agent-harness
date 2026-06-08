"""Integration tests for browser pool concurrency control"""

import asyncio
import contextlib
import shutil
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.pool.config import (
    BrowserPoolConfig,
    ThrottleMode,
)

_HAS_CHROMIUM = shutil.which("chromium") is not None or shutil.which("google-chrome") is not None
requires_browser = pytest.mark.skipif(
    not _HAS_CHROMIUM, reason="Chromium/Patchright not installed in this environment"
)

pytestmark = [pytest.mark.integration, requires_browser]


class TestGlobalConcurrencyLimit:
    """Tests for global concurrency limit via Semaphore"""

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrent_acquires(self):
        """Test global semaphore limits concurrent page acquisitions"""
        config = BrowserPoolConfig(max_concurrent_pages=2)
        pool = GlobalBrowserPool(max_browsers=2, config=config)

        acquired_pages = []
        acquired_keys = []

        try:
            # Acquire 2 pages (should succeed immediately)
            page1, key1 = await pool.acquire_page(ContextType.CRAWL)
            acquired_pages.append(page1)
            acquired_keys.append(key1)

            page2, key2 = await pool.acquire_page(ContextType.CRAWL)
            acquired_pages.append(page2)
            acquired_keys.append(key2)

            # Try to acquire 3rd page (should block until release)
            acquire_started = False

            async def acquire_third():
                nonlocal acquire_started
                acquire_started = True
                page3, key3 = await pool.acquire_page(ContextType.CRAWL)
                acquired_pages.append(page3)
                acquired_keys.append(key3)

            task = asyncio.create_task(acquire_third())

            # Give it time to start
            await asyncio.sleep(0.1)
            assert acquire_started

            # Task should be blocked (not completed)
            assert not task.done()

            # Release one page
            await pool.release_page(page1, key1)

            # Now task should complete
            await asyncio.wait_for(task, timeout=1.0)
            assert task.done()

        finally:
            # Cleanup
            for page, key in zip(acquired_pages[1:], acquired_keys[1:], strict=False):
                with contextlib.suppress(Exception):
                    await pool.release_page(page, key)
            await pool.shutdown()

    @pytest.mark.asyncio
    async def test_semaphore_released_on_acquire_failure(self):
        """Test semaphore is released when acquire fails"""
        config = BrowserPoolConfig(max_concurrent_pages=1)
        pool = GlobalBrowserPool(max_browsers=1, config=config)

        # Mock PagePool.acquire to fail
        with patch("myrm_agent_harness.toolkits.browser.pool.page_pool.PagePool.acquire") as mock_acquire:
            mock_acquire.side_effect = RuntimeError("Acquire failed")

            with contextlib.suppress(RuntimeError):
                await pool.acquire_page(ContextType.CRAWL)

            # Semaphore should be released (available=1)
            assert pool._global_semaphore._value == 1

        await pool.shutdown()


class TestThrottleStrategyIntegration:
    """Tests for throttle strategy integration in pool"""

    @pytest.mark.asyncio
    async def test_pool_provides_throttle_strategy(self):
        """Test pool provides throttle strategy property"""
        config = BrowserPoolConfig.standard()
        pool = GlobalBrowserPool(max_browsers=1, config=config)

        strategy = pool.throttle_strategy
        assert strategy is not None
        assert hasattr(strategy, "before_navigate")
        assert hasattr(strategy, "record_response")

        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_no_throttle_strategy(self):
        """Test NoThrottle strategy is used when mode is MINIMAL"""
        from myrm_agent_harness.toolkits.browser.pool.throttle import NoThrottle

        pool = GlobalBrowserPool(max_browsers=1, config=BrowserPoolConfig.minimal())

        assert isinstance(pool.throttle_strategy, NoThrottle)

        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_domain_throttle_strategy(self):
        """Test DomainThrottle strategy is used when mode is STANDARD"""
        from myrm_agent_harness.toolkits.browser.pool.throttle import DomainThrottle

        config = BrowserPoolConfig.standard()
        pool = GlobalBrowserPool(max_browsers=1, config=config)

        assert isinstance(pool.throttle_strategy, DomainThrottle)

        await pool.shutdown()


class TestNavigatorThrottleIntegration:
    """Tests for Navigator throttle integration"""

    @pytest.mark.asyncio
    async def test_navigator_calls_throttle_before_navigate(self):
        """Test Navigator calls throttle.before_navigate"""
        from myrm_agent_harness.toolkits.browser.navigation import Navigator

        mock_page = AsyncMock()
        mock_response = MagicMock()
        mock_response.status = 200
        mock_page.goto = AsyncMock(return_value=mock_response)
        mock_page.url = "https://example.com"
        mock_page.evaluate = AsyncMock(return_value={"stable": True, "inflightRequests": 0})

        mock_throttle = MagicMock()
        mock_throttle.before_navigate = AsyncMock()
        mock_throttle.record_response = MagicMock()

        navigator = Navigator(mock_page, throttle=mock_throttle)

        await navigator.goto("https://example.com")

        mock_throttle.before_navigate.assert_called_once_with("https://example.com")
        mock_throttle.record_response.assert_called_once_with("https://example.com", True)

    @pytest.mark.asyncio
    async def test_navigator_records_failure(self):
        """Test Navigator records failure on exception"""
        from myrm_agent_harness.toolkits.browser.navigation import Navigator

        mock_page = MagicMock()
        mock_page.goto = AsyncMock(side_effect=RuntimeError("Navigation failed"))

        mock_throttle = MagicMock()
        mock_throttle.before_navigate = AsyncMock()
        mock_throttle.record_response = MagicMock()

        navigator = Navigator(mock_page, throttle=mock_throttle)

        with pytest.raises(RuntimeError):
            await navigator.goto("https://example.com")

        mock_throttle.record_response.assert_called_once_with("https://example.com", False)

    @pytest.mark.asyncio
    async def test_navigator_without_throttle(self):
        """Test Navigator works without throttle"""
        from myrm_agent_harness.toolkits.browser.navigation import Navigator

        mock_page = AsyncMock()
        mock_response = MagicMock()
        mock_response.status = 200
        mock_page.goto = AsyncMock(return_value=mock_response)
        mock_page.url = "https://example.com"
        mock_page.evaluate = AsyncMock(return_value={"stable": True, "inflightRequests": 0})

        navigator = Navigator(mock_page, throttle=None)

        await navigator.goto("https://example.com")


class TestBrowserPoolConfigIntegration:
    """Tests for BrowserPoolConfig integration"""

    @pytest.mark.asyncio
    async def test_pool_initializes_with_config(self):
        """Test pool initializes correctly with config"""
        config = BrowserPoolConfig(
            max_concurrent_pages=30,
        )
        pool = GlobalBrowserPool(max_browsers=2, config=config)

        assert pool._config.max_concurrent_pages == 30
        assert pool._global_semaphore._value == 30

        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_pool_uses_default_config_when_none(self):
        """Test pool uses default config when config=None"""
        pool = GlobalBrowserPool(max_browsers=1, config=None)

        assert pool._config.max_concurrent_pages == 30
        assert pool._config.rate_limiter.mode == ThrottleMode.DOMAIN

        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_pool_passes_default_emulation_to_context_factory(self):
        """Test pool passes default_emulation from config to ContextFactory"""
        config = BrowserPoolConfig.standard()
        pool = GlobalBrowserPool(max_browsers=1, config=config)

        assert pool._context_factory._default_emulation is config.default_emulation
        assert pool._context_factory._default_emulation is not None
        assert pool._context_factory._default_emulation.permissions == (
            "clipboard-read",
            "clipboard-write",
        )

        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_pool_minimal_mode_no_default_emulation(self):
        """Test pool with minimal config has no default_emulation in ContextFactory"""
        config = BrowserPoolConfig.minimal()
        pool = GlobalBrowserPool(max_browsers=1, config=config)

        assert pool._context_factory._default_emulation is None

        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_pool_custom_emulation_passed_through(self):
        """Test pool with custom emulation config passes it to ContextFactory"""
        from myrm_agent_harness.toolkits.browser.pool.emulation import EmulationConfig

        custom = EmulationConfig(permissions=("geolocation", "notifications"))
        config = BrowserPoolConfig(default_emulation=custom)
        pool = GlobalBrowserPool(max_browsers=1, config=config)

        assert pool._context_factory._default_emulation is custom

        await pool.shutdown()


class TestEndToEndConcurrencyControl:
    """End-to-end tests for complete concurrency control flow"""

    @pytest.mark.asyncio
    async def test_complete_flow_with_all_controls(self):
        """Test complete flow: semaphore → throttle → navigate"""
        config = BrowserPoolConfig(max_concurrent_pages=2)
        pool = GlobalBrowserPool(max_browsers=1, config=config)

        try:
            page, ctx_key = await pool.acquire_page(ContextType.CRAWL)
            assert page is not None

            assert pool._global_semaphore._value == 1

            await pool.release_page(page, ctx_key)
            assert pool._global_semaphore._value == 2

        finally:
            await pool.shutdown()

    @pytest.mark.asyncio
    async def test_concurrent_limits_with_multiple_contexts(self):
        """Test concurrent limits apply across different context types"""
        config = BrowserPoolConfig(max_concurrent_pages=3)
        pool = GlobalBrowserPool(max_browsers=2, config=config)

        acquired = []

        try:
            # Acquire pages from different context types
            page1, key1 = await pool.acquire_page(ContextType.CRAWL)
            acquired.append((page1, key1))

            page2, key2 = await pool.acquire_page(ContextType.AGENT)
            acquired.append((page2, key2))

            page3, key3 = await pool.acquire_page(ContextType.STEALTH)
            acquired.append((page3, key3))

            # All should succeed, semaphore exhausted
            assert pool._global_semaphore._value == 0

            # 4th should block
            async def acquire_fourth():
                page4, key4 = await pool.acquire_page(ContextType.CRAWL)
                acquired.append((page4, key4))

            task = asyncio.create_task(acquire_fourth())
            await asyncio.sleep(0.1)

            assert not task.done()

            # Release one
            await pool.release_page(page1, key1)

            await asyncio.wait_for(task, timeout=1.0)

        finally:
            for page, key in acquired[1:]:
                with contextlib.suppress(Exception):
                    await pool.release_page(page, key)
            await pool.shutdown()


class TestBrowserFetcherNavigatorIntegration:
    """Tests for BrowserFetcher using Navigator"""

    @pytest.mark.skip(reason="Network unavailable in test environment")
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_browser_fetcher_uses_navigator(self):
        """Test BrowserFetcher uses Navigator and gets throttle"""
        from myrm_agent_harness.toolkits.web_fetch.fetchers.browser_fetcher import BrowserFetcher

        config = BrowserPoolConfig.minimal()
        pool = GlobalBrowserPool(max_browsers=1, config=config)
        fetcher = BrowserFetcher(browser_pool=pool)

        try:
            result = await fetcher.fetch("https://www.example.com")

            # Should succeed and return result
            assert result is not None
            assert result.url == "https://www.example.com" or "example.com" in result.url
            assert result.status_code == 200

        finally:
            await pool.shutdown()
