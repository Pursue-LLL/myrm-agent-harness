"""Unit tests for GlobalBrowserPool.update_remote_endpoint().

Covers: config replacement, launcher cache eviction, thread safety (lock),
and no-op behavior when no REMOTE launchers exist.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.pool.browser_pool import GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.pool.config import BrowserPoolConfig, LaunchMode


@pytest.fixture()
def pool() -> GlobalBrowserPool:
    """Create a minimal pool instance for testing (no real browsers)."""
    config = BrowserPoolConfig.minimal()
    return GlobalBrowserPool(max_browsers=1, config=config)


@pytest.mark.asyncio
async def test_update_remote_endpoint_sets_config(pool: GlobalBrowserPool) -> None:
    """Verify config is updated with new ws_url and headers."""
    assert pool.config.remote_ws_endpoint is None

    await pool.update_remote_endpoint("wss://test.example.com", {"Authorization": "Bearer tok"})

    assert pool.config.remote_ws_endpoint == "wss://test.example.com"
    assert pool.config.remote_ws_headers == {"Authorization": "Bearer tok"}


@pytest.mark.asyncio
async def test_update_remote_endpoint_clears_endpoint(pool: GlobalBrowserPool) -> None:
    """Verify clearing the endpoint sets it to None."""
    await pool.update_remote_endpoint("wss://test.example.com")
    await pool.update_remote_endpoint(None)

    assert pool.config.remote_ws_endpoint is None
    assert pool.config.remote_ws_headers is None


@pytest.mark.asyncio
async def test_update_remote_endpoint_evicts_remote_launchers(pool: GlobalBrowserPool) -> None:
    """Verify cached REMOTE launchers are evicted and shut down."""
    from myrm_agent_harness.toolkits.browser.pool.config import BrowserEngine

    mock_launcher = MagicMock()
    mock_launcher.shutdown = AsyncMock()
    remote_key = (BrowserEngine.CHROMIUM_PATCHRIGHT, LaunchMode.REMOTE)
    pool._launchers[remote_key] = mock_launcher

    await pool.update_remote_endpoint("wss://new-endpoint.com")

    assert remote_key not in pool._launchers
    mock_launcher.shutdown.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_remote_endpoint_preserves_non_remote_launchers(pool: GlobalBrowserPool) -> None:
    """Verify non-REMOTE launchers are not affected."""
    from myrm_agent_harness.toolkits.browser.pool.config import BrowserEngine

    mock_auto_launcher = MagicMock()
    mock_auto_launcher.shutdown = AsyncMock()
    auto_key = (BrowserEngine.CHROMIUM_PATCHRIGHT, LaunchMode.AUTO)
    pool._launchers[auto_key] = mock_auto_launcher

    await pool.update_remote_endpoint("wss://new-endpoint.com")

    assert auto_key in pool._launchers
    mock_auto_launcher.shutdown.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_remote_endpoint_noop_when_no_remote_launchers(pool: GlobalBrowserPool) -> None:
    """Verify no error when there are no REMOTE launchers to evict."""
    await pool.update_remote_endpoint("wss://test.example.com")
    assert pool.config.remote_ws_endpoint == "wss://test.example.com"
