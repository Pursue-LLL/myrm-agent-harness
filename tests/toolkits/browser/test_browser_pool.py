"""Unit tests for GlobalBrowserPool and PagePool"""

import asyncio
import shutil
import signal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.pool import (
    BrowserInstance,
    BrowserLaunchError,
    ContextType,
    GlobalBrowserPool,
)

_HAS_CHROMIUM = shutil.which("chromium") is not None or shutil.which("google-chrome") is not None
requires_browser = pytest.mark.skipif(
    not _HAS_CHROMIUM, reason="Chromium/Patchright not installed in this environment"
)


@pytest.fixture
async def browser_pool() -> GlobalBrowserPool:
    """创建测试用的 GlobalBrowserPool"""
    pool = GlobalBrowserPool(max_browsers=2)
    yield pool
    await pool.shutdown()


@requires_browser
@pytest.mark.asyncio
async def test_acquire_and_release_page(browser_pool: GlobalBrowserPool) -> None:
    """测试 Page 的获取和释放"""
    page1, ctx_key1 = await browser_pool.acquire_page(ContextType.CRAWL)
    assert page1 is not None
    assert ctx_key1.startswith("crawl_")

    page2, ctx_key2 = await browser_pool.acquire_page(ContextType.AGENT)
    assert page2 is not None
    assert ctx_key2.startswith("agent_")

    assert page1 != page2

    await browser_pool.release_page(page1, ctx_key1)
    await browser_pool.release_page(page2, ctx_key2)

    stats = browser_pool.stats
    assert stats["total_acquires"] == 2
    assert stats["total_releases"] == 2


@pytest.mark.asyncio
async def test_page_reuse(browser_pool: GlobalBrowserPool) -> None:
    """测试 Page 复用机制"""
    page1, ctx_key = await browser_pool.acquire_page(ContextType.CRAWL, context_key="test_session")
    await browser_pool.release_page(page1, ctx_key)

    page2, ctx_key2 = await browser_pool.acquire_page(ContextType.CRAWL, context_key="test_session")

    assert ctx_key == ctx_key2
    assert page1 == page2

    await browser_pool.release_page(page2, ctx_key2)


@pytest.mark.asyncio
async def test_warmup(browser_pool: GlobalBrowserPool) -> None:
    """测试预热机制"""
    await browser_pool.warmup(browsers=1, pages_per_context=3)

    stats = browser_pool.stats
    assert stats["total_browsers"] == 1
    assert stats["total_contexts"] >= 2


@pytest.mark.asyncio
async def test_concurrent_acquires(browser_pool: GlobalBrowserPool) -> None:
    """测试并发获取 Page"""

    async def acquire_and_release() -> None:
        page, ctx_key = await browser_pool.acquire_page(ContextType.CRAWL)
        await asyncio.sleep(0.01)
        await browser_pool.release_page(page, ctx_key)

    await asyncio.gather(*(acquire_and_release() for _ in range(10)))

    stats = browser_pool.stats
    assert stats["total_acquires"] == 10
    assert stats["total_releases"] == 10


@pytest.mark.asyncio
async def test_context_isolation(browser_pool: GlobalBrowserPool) -> None:
    """测试不同 ContextType 的隔离"""
    page_crawl, ctx_crawl = await browser_pool.acquire_page(ContextType.CRAWL, context_key="crawl_1")
    page_agent, ctx_agent = await browser_pool.acquire_page(ContextType.AGENT, context_key="agent_1")

    assert ctx_crawl != ctx_agent
    assert page_crawl != page_agent

    await browser_pool.release_page(page_crawl, ctx_crawl)
    await browser_pool.release_page(page_agent, ctx_agent)


# =============================================================================
# Browser creation retry logic
# =============================================================================


@pytest.mark.asyncio
async def test_browser_launch_retry_on_timeout() -> None:
    """Test browser launch retries on TimeoutError."""
    pool = GlobalBrowserPool(max_browsers=1)

    attempt_count = 0

    async def mock_launch(**kwargs: object) -> Any:
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count <= 2:
            raise TimeoutError("Launch timeout")
        mock_browser = MagicMock()
        return mock_browser

    mock_playwright = AsyncMock()
    mock_playwright.chromium.launch = mock_launch
    launcher = pool._get_launcher(pool._config.engine)
    launcher._playwright = mock_playwright

    inst = await launcher.create_browser()

    assert attempt_count == 3
    assert inst.browser is not None

    await pool.shutdown()


@pytest.mark.asyncio
async def test_browser_launch_retry_on_connection_error() -> None:
    """Test browser launch retries on ConnectionError."""
    pool = GlobalBrowserPool(max_browsers=1)

    attempt_count = 0

    async def mock_launch(**kwargs: object) -> Any:
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count <= 2:
            raise ConnectionError("Connection failed")
        mock_browser = MagicMock()
        return mock_browser

    mock_playwright = AsyncMock()
    mock_playwright.chromium.launch = mock_launch
    launcher = pool._get_launcher(pool._config.engine)
    launcher._playwright = mock_playwright

    inst = await launcher.create_browser()

    assert attempt_count == 3
    assert inst.browser is not None

    await pool.shutdown()


@pytest.mark.asyncio
async def test_browser_launch_retry_on_generic_exception() -> None:
    """Test browser launch retries on generic Exception."""
    pool = GlobalBrowserPool(max_browsers=1)

    attempt_count = 0

    async def mock_launch(**kwargs: object) -> Any:
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count == 1:
            raise RuntimeError("Launch failed")
        mock_browser = MagicMock()
        return mock_browser

    mock_playwright = AsyncMock()
    mock_playwright.chromium.launch = mock_launch
    launcher = pool._get_launcher(pool._config.engine)
    launcher._playwright = mock_playwright

    await launcher.create_browser()

    assert attempt_count == 2

    await pool.shutdown()


@pytest.mark.asyncio
async def test_browser_launch_all_attempts_fail() -> None:
    """Test browser launch fails after all retries exhausted."""
    pool = GlobalBrowserPool(max_browsers=1)

    async def mock_launch(**kwargs: object) -> Any:
        raise TimeoutError("Always fails")

    mock_playwright = AsyncMock()
    mock_playwright.chromium.launch = mock_launch
    launcher = pool._get_launcher(pool._config.engine)
    launcher._playwright = mock_playwright

    with pytest.raises(BrowserLaunchError, match="Failed to create Browser after 3 attempts"):
        await launcher.create_browser()

    await pool.shutdown()


# =============================================================================
# Browser scaling logic
# =============================================================================


@pytest.mark.asyncio
async def test_browser_scaling_on_high_load() -> None:
    """Test pool creates new browser when load is high."""
    pool = GlobalBrowserPool(max_browsers=3)

    mock_browser = MagicMock()
    mock_context = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)

    launcher = pool._get_launcher(pool._config.engine)
    with patch.object(launcher, "create_browser") as mock_create:
        mock_create.return_value = BrowserInstance(browser=mock_browser)

        launcher = pool._get_launcher(pool._config.engine)
        browser_inst = await launcher.create_browser()
        browser_inst.load = 15
        pool._browsers.append(browser_inst)

        await pool._get_least_loaded_browser()

        assert len(pool._browsers) >= 2

    await pool.shutdown()


# =============================================================================
# Cleanup and error handling
# =============================================================================


@pytest.mark.asyncio
async def test_cleanup_closed_contexts() -> None:
    """Test cleanup of closed contexts."""
    pool = GlobalBrowserPool(max_browsers=1)

    page, ctx_key = await pool.acquire_page(ContextType.CRAWL)
    await pool.release_page(page, ctx_key)

    stats = pool.stats
    assert stats["total_contexts"] >= 1

    await pool.shutdown()


# =============================================================================
# Context type and proxy configuration
# =============================================================================


@pytest.mark.asyncio
async def test_create_context_stealth() -> None:
    """Test creating STEALTH context with special options."""
    pool = GlobalBrowserPool(max_browsers=1)

    page, ctx_key = await pool.acquire_page(ContextType.STEALTH)

    assert page is not None
    assert ctx_key.startswith("stealth_")

    await pool.release_page(page, ctx_key)
    await pool.shutdown()


@pytest.mark.asyncio
async def test_pool_with_proxy_pool() -> None:
    """Test pool configured with proxy pool."""
    from myrm_agent_harness.toolkits.browser.pool.proxy import ProxyConfig, RoundRobinProxyPool

    proxy_pool = RoundRobinProxyPool([ProxyConfig(server="http://proxy.example.com:8080")])
    pool = GlobalBrowserPool(max_browsers=1, proxy_pool=proxy_pool)

    page, ctx_key = await pool.acquire_page(ContextType.CRAWL)

    assert page is not None

    await pool.release_page(page, ctx_key)
    await pool.shutdown()


@pytest.mark.asyncio
async def test_create_context_with_emulation() -> None:
    """Test _create_context with EmulationConfig."""
    from myrm_agent_harness.toolkits.browser.pool.emulation import EmulationConfig

    pool = GlobalBrowserPool(max_browsers=1)

    launcher = pool._get_launcher(pool._config.engine)
    browser_inst = await launcher.create_browser()

    emulation = EmulationConfig(
        geolocation=(39.9, 116.4),
        timezone="Asia/Shanghai",
        locale="zh-CN",
        permissions=("geolocation",),
        color_scheme="dark",
        offline=False,
    )

    context = await pool._context_factory.create_context(
        browser_inst.browser, ContextType.AGENT.value, emulation=emulation
    )

    assert context is not None

    await context.close()
    await pool.shutdown()


@pytest.mark.asyncio
async def test_create_context_emulation_and_extra_kwargs() -> None:
    """Test emulation + extra_kwargs priority (extra_kwargs overrides)."""
    from myrm_agent_harness.toolkits.browser.pool.emulation import EmulationConfig

    pool = GlobalBrowserPool(max_browsers=1)

    launcher = pool._get_launcher(pool._config.engine)
    browser_inst = await launcher.create_browser()

    emulation = EmulationConfig(locale="zh-CN", color_scheme="light")

    extra_kwargs = {"color_scheme": "dark"}

    context = await pool._context_factory.create_context(
        browser_inst.browser,
        ContextType.AGENT.value,
        emulation=emulation,
        extra_kwargs=extra_kwargs,
    )

    assert context is not None

    await context.close()
    await pool.shutdown()


# =============================================================================
# Shutdown error handling
# =============================================================================


@pytest.mark.asyncio
async def test_shutdown_with_context_close_exception() -> None:
    """Test shutdown handles context.close exception gracefully."""
    pool = GlobalBrowserPool(max_browsers=1)

    _page, _ctx_key = await pool.acquire_page(ContextType.CRAWL)

    for inst in pool._browsers:
        for ctx in inst.contexts.values():
            ctx.close = AsyncMock(side_effect=RuntimeError("Close failed"))

    await pool.shutdown()

    assert len(pool._browsers) == 0


@pytest.mark.asyncio
async def test_shutdown_with_browser_close_exception() -> None:
    """Test shutdown handles browser.close exception gracefully."""
    pool = GlobalBrowserPool(max_browsers=1)

    _page, _ctx_key = await pool.acquire_page(ContextType.CRAWL)

    for inst in pool._browsers:
        inst.browser.close = AsyncMock(side_effect=RuntimeError("Browser close failed"))

    await pool.shutdown()

    assert len(pool._browsers) == 0


@pytest.mark.asyncio
async def test_shutdown_with_playwright_stop_exception() -> None:
    """Test shutdown handles playwright.stop exception gracefully."""
    pool = GlobalBrowserPool(max_browsers=1)

    _page, _ctx_key = await pool.acquire_page(ContextType.CRAWL)

    launcher = pool._get_launcher(pool._config.engine)
    if launcher._playwright:
        launcher._playwright.stop = AsyncMock(side_effect=RuntimeError("Playwright stop failed"))

    await pool.shutdown()

    assert launcher._playwright is None


# =============================================================================
# Global pool cleanup (atexit hook)
# =============================================================================


def test_cleanup_global_pool_no_pool() -> None:
    """Test _cleanup_global_pool handles no global pool."""
    from myrm_agent_harness.toolkits.browser.pool.singleton import _cleanup_global_pool, _global_pool

    original_pool = _global_pool

    try:
        import myrm_agent_harness.toolkits.browser.pool.singleton as pool_module

        pool_module._global_pool = None

        _cleanup_global_pool()

    finally:
        import myrm_agent_harness.toolkits.browser.pool.singleton as pool_module

        pool_module._global_pool = original_pool


def test_cleanup_global_pool_with_running_loop() -> None:
    """Test _cleanup_global_pool with running event loop."""
    from unittest.mock import MagicMock, patch

    from myrm_agent_harness.toolkits.browser.pool.singleton import _cleanup_global_pool

    mock_loop = MagicMock()
    mock_loop.is_running = MagicMock(return_value=True)
    mock_loop.create_task = MagicMock()

    with patch("myrm_agent_harness.toolkits.browser.pool.singleton._global_pool") as mock_pool:
        mock_pool.shutdown = AsyncMock()

        with patch("asyncio.get_running_loop", return_value=mock_loop):
            _cleanup_global_pool()

            mock_loop.create_task.assert_called_once()


def test_cleanup_global_pool_no_running_loop() -> None:
    """Test _cleanup_global_pool with no running loop."""
    from unittest.mock import patch

    from myrm_agent_harness.toolkits.browser.pool.singleton import _cleanup_global_pool

    with patch("myrm_agent_harness.toolkits.browser.pool.singleton._global_pool") as mock_pool:
        mock_pool.shutdown = AsyncMock()

        with patch("asyncio.get_running_loop", side_effect=RuntimeError("No loop")):
            with patch("asyncio.run") as mock_run:
                _cleanup_global_pool()

                mock_run.assert_called_once()


def test_sigterm_handler_calls_cleanup() -> None:
    """Test SIGTERM handler calls _cleanup_global_pool."""
    from myrm_agent_harness.toolkits.browser.pool.singleton import _sigterm_handler

    with patch("myrm_agent_harness.toolkits.browser.pool.singleton._cleanup_global_pool") as mock_cleanup:
        _sigterm_handler(signal.SIGTERM, None)
        mock_cleanup.assert_called_once()


def test_signal_registration_value_error() -> None:
    """测试signal注册ValueError被捕获（覆盖line 392-393）"""
    import sys

    # 保存原始模块
    original_module = sys.modules.get("myrm_agent_harness.toolkits.browser.pool.singleton")

    try:
        if "myrm_agent_harness.toolkits.browser.pool.singleton" in sys.modules:
            del sys.modules["myrm_agent_harness.toolkits.browser.pool.singleton"]

        original_signal = signal.signal

        def mock_signal(sig: int, handler: object) -> object:
            if sig == signal.SIGTERM:
                raise ValueError("Cannot set signal handler")
            return original_signal(sig, handler)

        with patch("signal.signal", side_effect=mock_signal):
            import myrm_agent_harness.toolkits.browser.pool.singleton

            assert myrm_agent_harness.toolkits.browser.pool.singleton is not None

    finally:
        if original_module:
            sys.modules["myrm_agent_harness.toolkits.browser.pool.singleton"] = original_module
