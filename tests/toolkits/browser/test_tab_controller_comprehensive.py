"""Comprehensive tests for TabController"""

import asyncio
import shutil
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.session.tab_controller import TabController

_HAS_CHROMIUM = shutil.which("chromium") is not None or shutil.which("google-chrome") is not None
requires_browser = pytest.mark.skipif(
    not _HAS_CHROMIUM, reason="Chromium/Patchright not installed in this environment"
)


@pytest.fixture
async def browser_pool() -> GlobalBrowserPool:
    """Create test browser pool."""
    pool = GlobalBrowserPool(max_browsers=1)
    yield pool
    await pool.shutdown()


@pytest.fixture
def tab_controller(browser_pool: GlobalBrowserPool) -> TabController:
    """Create test tab controller."""
    return TabController(browser_pool, ContextType.CRAWL)


# =============================================================================
# Basic tab operations
# =============================================================================


@requires_browser
@pytest.mark.asyncio
async def test_create_tab(tab_controller: TabController) -> None:
    """Test creating a tab."""
    tab_id = await tab_controller.create_tab()

    assert tab_id.startswith("tab")
    assert tab_id in tab_controller.list_tabs()
    assert tab_controller.get_active_tab_id() == tab_id


@pytest.mark.asyncio
async def test_close_tab(tab_controller: TabController) -> None:
    """Test closing a tab."""
    tab_id = await tab_controller.create_tab()
    await tab_controller.close_tab(tab_id)

    assert tab_id not in tab_controller.list_tabs()


@pytest.mark.asyncio
async def test_close_tab_not_found(tab_controller: TabController) -> None:
    """Test closing non-existent tab raises ValueError."""
    with pytest.raises(ValueError, match="Tab not found: nonexistent"):
        await tab_controller.close_tab("nonexistent")


@pytest.mark.asyncio
async def test_switch_tab(tab_controller: TabController) -> None:
    """Test switching between tabs."""
    tab1 = await tab_controller.create_tab()
    tab2 = await tab_controller.create_tab()

    await tab_controller.switch_tab(tab2)
    assert tab_controller.get_active_tab_id() == tab2

    await tab_controller.switch_tab(tab1)
    assert tab_controller.get_active_tab_id() == tab1


@pytest.mark.asyncio
async def test_switch_tab_not_found(tab_controller: TabController) -> None:
    """Test switching to non-existent tab raises ValueError."""
    with pytest.raises(ValueError, match="Tab not found: nonexistent"):
        await tab_controller.switch_tab("nonexistent")


@pytest.mark.asyncio
async def test_switch_tab_bring_to_front_exception(tab_controller: TabController) -> None:
    """Test switch_tab handles bring_to_front exception gracefully."""
    tab_id = await tab_controller.create_tab()

    handle = tab_controller._tabs[tab_id]
    handle.page.bring_to_front = AsyncMock(side_effect=RuntimeError("Bring to front failed"))

    await tab_controller.switch_tab(tab_id)

    assert tab_controller.get_active_tab_id() == tab_id


@pytest.mark.asyncio
async def test_get_active_page(tab_controller: TabController) -> None:
    """Test getting active page."""
    await tab_controller.create_tab()
    page = tab_controller.get_active_page()

    assert page is not None


@pytest.mark.asyncio
async def test_get_active_page_no_active_tab(tab_controller: TabController) -> None:
    """Test get_active_page raises RuntimeError when no active tab."""
    with pytest.raises(RuntimeError, match="No active tab"):
        tab_controller.get_active_page()


@pytest.mark.asyncio
async def test_get_active_tab_id_no_active_tab(tab_controller: TabController) -> None:
    """Test get_active_tab_id raises RuntimeError when no active tab."""
    with pytest.raises(RuntimeError, match="No active tab"):
        tab_controller.get_active_tab_id()


@pytest.mark.asyncio
async def test_list_tabs(tab_controller: TabController) -> None:
    """Test listing all tabs."""
    tab1 = await tab_controller.create_tab()
    tab2 = await tab_controller.create_tab()

    tab_ids = tab_controller.list_tabs()
    assert len(tab_ids) == 2
    assert tab1 in tab_ids
    assert tab2 in tab_ids


# =============================================================================
# LRU eviction
# =============================================================================


@pytest.mark.asyncio
async def test_evict_lru_when_max_tabs_reached(tab_controller: TabController) -> None:
    """Test LRU eviction when MAX_TABS reached."""
    tab_ids = []
    for _ in range(10):
        tab_id = await tab_controller.create_tab()
        tab_ids.append(tab_id)
        await asyncio.sleep(0.01)

    await tab_controller.switch_tab(tab_ids[-1])

    tab_new = await tab_controller.create_tab()

    assert len(tab_controller.list_tabs()) == 10
    assert tab_ids[0] not in tab_controller.list_tabs()
    assert tab_new in tab_controller.list_tabs()


@pytest.mark.asyncio
async def test_evict_lru_skips_active_tab(tab_controller: TabController) -> None:
    """Test LRU eviction skips active tab when it's the only one."""
    await tab_controller.create_tab()

    for _ in range(10):
        await tab_controller.create_tab()

    assert len(tab_controller.list_tabs()) == 10


@pytest.mark.asyncio
async def test_evict_lru_only_active_tab(tab_controller: TabController) -> None:
    """Test _evict_lru when only active tab exists."""
    tab_id = await tab_controller.create_tab()
    active = tab_controller.get_active_tab_id()

    assert active == tab_id

    for _i in range(9):
        await tab_controller.create_tab()

    tab_controller._tabs = {active: tab_controller._tabs[active]}
    tab_controller._active_tab_id = active

    await tab_controller._evict_lru()

    assert active in tab_controller.list_tabs()


# =============================================================================
# Close all
# =============================================================================


@pytest.mark.asyncio
async def test_close_all(tab_controller: TabController) -> None:
    """Test closing all tabs."""
    await tab_controller.create_tab()
    await tab_controller.create_tab()
    await tab_controller.create_tab()

    assert len(tab_controller.list_tabs()) == 3

    await tab_controller.close_all()

    assert len(tab_controller.list_tabs()) == 0


# =============================================================================
# Stats
# =============================================================================


@pytest.mark.asyncio
async def test_stats(tab_controller: TabController) -> None:
    """Test stats property."""
    tab1 = await tab_controller.create_tab()
    tab2 = await tab_controller.create_tab()

    stats = tab_controller.stats

    assert stats["total_tabs"] == 2
    assert stats["active_tab"] in [tab1, tab2]
    assert set(stats["tab_ids"]) == {tab1, tab2}  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_close_tab_updates_active(tab_controller: TabController) -> None:
    """Test closing active tab updates active_tab_id."""
    await tab_controller.create_tab()
    await tab_controller.create_tab()

    active_before_close = tab_controller.get_active_tab_id()

    await tab_controller.close_tab(active_before_close)

    active_after_close = tab_controller.get_active_tab_id()

    assert active_after_close != active_before_close
    assert active_after_close in tab_controller.list_tabs()


@pytest.mark.asyncio
async def test_last_used_updated_on_get_active_page(tab_controller: TabController) -> None:
    """Test that last_used is updated when get_active_page is called."""
    tab_id = await tab_controller.create_tab()
    handle = tab_controller._tabs[tab_id]

    initial_time = handle.last_used
    await asyncio.sleep(0.01)

    tab_controller.get_active_page()

    assert handle.last_used > initial_time
