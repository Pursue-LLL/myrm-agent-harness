"""Comprehensive tests for PagePool"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.pool.page_pool import PagePool


@pytest.fixture
def mock_context() -> MagicMock:
    """Create mock BrowserContext."""
    context = MagicMock()
    context.new_page = AsyncMock()
    return context


@pytest.fixture
def mock_page() -> MagicMock:
    """Create mock Page."""
    page = MagicMock()
    page.close = AsyncMock()
    page.goto = AsyncMock()
    page.context = MagicMock()
    return page


# =============================================================================
# Basic operations
# =============================================================================


@pytest.mark.asyncio
async def test_acquire_creates_new_page(mock_context: MagicMock, mock_page: MagicMock) -> None:
    """Test acquire creates new page when pool is empty."""
    mock_context.new_page = AsyncMock(return_value=mock_page)
    pool = PagePool(mock_context, max_size=5)

    page = await pool.acquire()

    assert page == mock_page
    mock_context.new_page.assert_called_once()


@pytest.mark.asyncio
async def test_acquire_reuses_idle_page(mock_context: MagicMock, mock_page: MagicMock) -> None:
    """Test acquire reuses idle page."""
    mock_context.new_page = AsyncMock(return_value=mock_page)

    mock_cdp = AsyncMock()
    mock_cdp.send = AsyncMock()
    mock_cdp.detach = AsyncMock()
    mock_context.new_cdp_session = AsyncMock(return_value=mock_cdp)

    pool = PagePool(mock_context, max_size=5)

    page1 = await pool.acquire()
    await pool.release(page1)

    page2 = await pool.acquire()

    assert page1 == page2
    assert pool.stats["total_resets"] == 1


@pytest.mark.asyncio
async def test_release_exceeds_max_size_closes_page(mock_context: MagicMock, mock_page: MagicMock) -> None:
    """Test release closes page when pool exceeds max_size."""
    pages = [MagicMock() for _ in range(3)]
    for p in pages:
        p.close = AsyncMock()

    mock_context.new_page = AsyncMock(side_effect=pages)

    pool = PagePool(mock_context, max_size=2)

    p1 = await pool.acquire()
    p2 = await pool.acquire()
    p3 = await pool.acquire()

    await pool.release(p1)
    await pool.release(p2)
    await pool.release(p3)

    assert len(pool._idle) == 2
    p3.close.assert_called_once()


@pytest.mark.asyncio
async def test_release_max_size_close_exception() -> None:
    """Test release handles close exception when pool is full."""
    mock_context = MagicMock()

    pages = [MagicMock() for _ in range(3)]
    pages[0].close = AsyncMock()
    pages[1].close = AsyncMock()
    pages[2].close = AsyncMock(side_effect=RuntimeError("Close failed"))

    mock_context.new_page = AsyncMock(side_effect=pages)

    pool = PagePool(mock_context, max_size=2)

    p1 = await pool.acquire()
    p2 = await pool.acquire()
    p3 = await pool.acquire()

    await pool.release(p1)
    await pool.release(p2)
    await pool.release(p3)

    assert len(pool._idle) == 2


@pytest.mark.asyncio
async def test_release_page_close_exception(mock_context: MagicMock, mock_page: MagicMock) -> None:
    """Test release handles page.close exception gracefully."""
    mock_page.close = AsyncMock(side_effect=RuntimeError("Close failed"))
    mock_context.new_page = AsyncMock(return_value=mock_page)

    pool = PagePool(mock_context, max_size=1)

    page = await pool.acquire()
    await pool.release(page)

    page2 = await pool.acquire()

    await pool.release(page2)


@pytest.mark.asyncio
async def test_preserve_session_skips_global_cookie_clear(mock_context: MagicMock, mock_page: MagicMock) -> None:
    """External CDP mode must not wipe browser-wide cookies on page reuse."""
    mock_cdp = AsyncMock()
    mock_cdp.send = AsyncMock()
    mock_cdp.detach = AsyncMock()
    mock_page.context.new_cdp_session = AsyncMock(return_value=mock_cdp)
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_page.goto = AsyncMock()

    pool = PagePool(mock_context, max_size=5, preserve_session=True)

    page = await pool.acquire()
    await pool.release(page)
    await pool.acquire()

    sent_methods = [call.args[0] for call in mock_cdp.send.call_args_list]
    assert "Page.resetNavigationHistory" in sent_methods
    assert "Network.clearBrowserCookies" not in sent_methods
    assert "Storage.clearDataForOrigin" not in sent_methods


@pytest.mark.asyncio
async def test_managed_reset_clears_cookies(mock_context: MagicMock, mock_page: MagicMock) -> None:
    """Managed browser reset still clears global cookies."""
    mock_cdp = AsyncMock()
    mock_cdp.send = AsyncMock()
    mock_cdp.detach = AsyncMock()
    mock_page.context.new_cdp_session = AsyncMock(return_value=mock_cdp)
    mock_context.new_page = AsyncMock(return_value=mock_page)

    pool = PagePool(mock_context, max_size=5, preserve_session=False)

    page = await pool.acquire()
    await pool.release(page)
    await pool.acquire()

    sent_methods = [call.args[0] for call in mock_cdp.send.call_args_list]
    assert "Network.clearBrowserCookies" in sent_methods


# =============================================================================
# Fast reset failure and fallback
# =============================================================================


@pytest.mark.asyncio
async def test_fast_reset_cdp_exception(mock_context: MagicMock, mock_page: MagicMock) -> None:
    """Test fast reset CDP exception triggers fallback."""
    mock_cdp = AsyncMock()
    mock_cdp.send = AsyncMock(side_effect=RuntimeError("CDP failed"))
    mock_context.new_cdp_session = AsyncMock(return_value=mock_cdp)
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_page.goto = AsyncMock()

    pool = PagePool(mock_context, max_size=5)

    page = await pool.acquire()
    await pool.release(page)

    await pool.acquire()

    assert pool.stats["fast_reset_failures"] == 1
    assert pool.stats["total_resets"] == 1
    mock_page.goto.assert_called_once_with("about:blank", wait_until="domcontentloaded")


@pytest.mark.asyncio
async def test_fallback_reset_exception(mock_context: MagicMock, mock_page: MagicMock) -> None:
    """Test fallback reset handles goto exception gracefully."""
    mock_cdp = AsyncMock()
    mock_cdp.send = AsyncMock(side_effect=RuntimeError("CDP failed"))
    mock_context.new_cdp_session = AsyncMock(return_value=mock_cdp)
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_page.goto = AsyncMock(side_effect=TimeoutError("Goto timeout"))

    pool = PagePool(mock_context, max_size=5)

    page = await pool.acquire()
    await pool.release(page)

    await pool.acquire()

    assert pool.stats["fast_reset_failures"] == 1


# =============================================================================
# Shutdown
# =============================================================================


@pytest.mark.asyncio
async def test_shutdown_closes_all_pages(mock_context: MagicMock) -> None:
    """Test shutdown closes all idle and busy pages."""
    pages = [MagicMock() for _ in range(5)]
    for p in pages:
        p.close = AsyncMock()

    mock_context.new_page = AsyncMock(side_effect=pages)

    pool = PagePool(mock_context, max_size=10)

    p1 = await pool.acquire()
    p2 = await pool.acquire()
    await pool.acquire()

    await pool.release(p1)
    await pool.release(p2)

    await pool.shutdown()

    assert len(pool._idle) == 0
    assert len(pool._busy) == 0


@pytest.mark.asyncio
async def test_shutdown_page_close_exception(mock_context: MagicMock) -> None:
    """Test shutdown handles page.close exception gracefully."""
    mock_page1 = MagicMock()
    mock_page1.close = AsyncMock(side_effect=RuntimeError("Close failed"))

    mock_page2 = MagicMock()
    mock_page2.close = AsyncMock()

    mock_context.new_page = AsyncMock(side_effect=[mock_page1, mock_page2])

    pool = PagePool(mock_context, max_size=10)

    p1 = await pool.acquire()
    p2 = await pool.acquire()

    await pool.release(p1)
    await pool.release(p2)

    await pool.shutdown()

    assert len(pool._idle) == 0
    mock_page2.close.assert_called_once()


# =============================================================================
# Stats
# =============================================================================


@pytest.mark.asyncio
async def test_stats_property(mock_context: MagicMock, mock_page: MagicMock) -> None:
    """Test stats property returns correct metrics."""
    mock_context.new_page = AsyncMock(return_value=mock_page)

    pool = PagePool(mock_context, max_size=5)

    page = await pool.acquire()
    stats = pool.stats

    assert stats["idle"] == 0
    assert stats["busy"] == 1
    assert stats["total_acquires"] == 1
    assert stats["total_resets"] == 0

    await pool.release(page)
    stats = pool.stats

    assert stats["idle"] == 1
    assert stats["busy"] == 0
