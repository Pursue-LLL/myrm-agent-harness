"""Tests for GlobalBrowserPool.health() concurrent optimization."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.pool import GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.pool.browser_launcher import BrowserInstance


@pytest.mark.asyncio
async def test_health_concurrent_browser_checks() -> None:
    """Verify health() checks browsers concurrently without holding lock."""
    pool = GlobalBrowserPool(max_browsers=5)

    mock_browsers = []
    for i in range(5):
        mock_browser = MagicMock()
        mock_browser.version = AsyncMock(return_value=f"v{i}")

        browser_inst = BrowserInstance(browser=mock_browser)
        mock_browsers.append(browser_inst)

    pool._browsers = mock_browsers

    start = asyncio.get_event_loop().time()
    health_status = await pool.health()
    elapsed = asyncio.get_event_loop().time() - start

    assert health_status["browsers_alive"] == 5
    assert health_status["browsers_total"] == 5
    assert health_status["status"] == "healthy"

    assert elapsed < 2.5


@pytest.mark.asyncio
async def test_health_detects_unresponsive_browsers() -> None:
    """Verify health() detects unresponsive browsers."""
    pool = GlobalBrowserPool(max_browsers=3)

    mock_browsers = []
    for i in range(3):
        mock_browser = MagicMock()
        if i == 1:
            mock_browser.version = AsyncMock(side_effect=TimeoutError("Browser hung"))
        else:
            mock_browser.version = AsyncMock(return_value=f"v{i}")

        browser_inst = BrowserInstance(browser=mock_browser)
        mock_browsers.append(browser_inst)

    pool._browsers = mock_browsers

    health_status = await pool.health()

    assert health_status["browsers_alive"] == 2
    assert health_status["browsers_total"] == 3
    assert health_status["status"] == "degraded"
    assert any("Browser #1 unresponsive" in issue for issue in health_status["issues"])


@pytest.mark.asyncio
async def test_health_empty_pool() -> None:
    """Verify health() handles empty pool."""
    pool = GlobalBrowserPool()

    health_status = await pool.health()

    assert health_status["status"] == "healthy"
    assert health_status["browsers_alive"] == 0
    assert health_status["browsers_total"] == 0
    assert health_status["issues"] == []


@pytest.mark.asyncio
async def test_health_high_utilization() -> None:
    """Verify health() detects high utilization."""
    from myrm_agent_harness.toolkits.browser.pool.config import BrowserPoolConfig

    config = BrowserPoolConfig.minimal()
    pool = GlobalBrowserPool(max_browsers=1, config=config)
    pool._current_pages_in_use = 10

    health_status = await pool.health()

    assert health_status["status"] == "degraded"
    assert any("High utilization: 100%" in issue for issue in health_status["issues"])


@pytest.mark.asyncio
async def test_health_handles_unexpected_exception() -> None:
    """Verify health() handles unexpected exceptions gracefully."""
    pool = GlobalBrowserPool(max_browsers=3)

    mock_browsers = []
    for i in range(3):
        mock_browser = MagicMock()
        if i == 0:
            mock_browser.version = AsyncMock(return_value="v1")
        elif i == 1:
            mock_browser.version = AsyncMock(side_effect=AttributeError("Code bug"))
        else:
            mock_browser.version = AsyncMock(side_effect=MemoryError("OOM"))

        browser_inst = BrowserInstance(browser=mock_browser)
        mock_browsers.append(browser_inst)

    pool._browsers = mock_browsers

    health_status = await pool.health()

    assert health_status["browsers_alive"] == 1
    assert health_status["browsers_total"] == 3
    assert health_status["status"] == "degraded"
    assert any("Browser #1 check failed: AttributeError" in issue for issue in health_status["issues"])
    assert any("Browser #2 check failed: MemoryError" in issue for issue in health_status["issues"])
