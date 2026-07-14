"""Comprehensive tests for TabController"""

import asyncio
import shutil
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.session.tab_controller import TabController, TabHandle

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


# =============================================================================
# Popup capture
# =============================================================================


def _make_mock_page(url: str = "about:blank") -> MagicMock:
    """Create a lightweight mock Page for popup tests."""
    page = MagicMock()
    page.url = url
    page.is_closed = MagicMock(return_value=False)
    page.close = AsyncMock()
    page.bring_to_front = AsyncMock()
    page.on = MagicMock()
    return page


def _make_mock_tc() -> TabController:
    """Create a TabController with a mock pool (no real browser)."""
    pool = MagicMock()
    pool.release_page = AsyncMock()
    tc = TabController(pool, ContextType.CRAWL)
    return tc


async def _add_mock_tab(tc: TabController, context_key: str = "default") -> str:
    """Inject a mock tab directly into the controller."""
    page = _make_mock_page()
    tab_id = f"tab{tc._tab_counter}"
    tc._tab_counter += 1
    handle = TabHandle(page=page, tab_id=tab_id, context_key=context_key)
    tc._tabs[tab_id] = handle
    tc._active_tab_id = tab_id
    return tab_id


@pytest.mark.asyncio
async def test_attach_popup_listener_idempotent() -> None:
    """attach_popup_listener is idempotent per page instance."""
    tc = _make_mock_tc()
    page = _make_mock_page()

    tc.attach_popup_listener(page)
    tc.attach_popup_listener(page)

    assert page.on.call_count == 1
    assert id(page) in tc._popup_attached_pages


@pytest.mark.asyncio
async def test_attach_popup_listener_different_pages() -> None:
    """attach_popup_listener registers separately for different pages."""
    tc = _make_mock_tc()
    p1, p2 = _make_mock_page(), _make_mock_page()

    tc.attach_popup_listener(p1)
    tc.attach_popup_listener(p2)

    assert p1.on.call_count == 1
    assert p2.on.call_count == 1
    assert len(tc._popup_attached_pages) == 2


@pytest.mark.asyncio
async def test_on_popup_registers_tab_and_switches() -> None:
    """_on_popup creates a child tab and switches focus to it."""
    tc = _make_mock_tc()
    parent_id = await _add_mock_tab(tc)

    popup_page = _make_mock_page("https://accounts.google.com")
    await tc._on_popup(popup_page)

    assert len(tc._tabs) == 2
    new_tab_id = tc.get_active_tab_id()
    assert new_tab_id != parent_id

    handle = tc._tabs[new_tab_id]
    assert handle.is_popup is True
    assert handle.parent_tab_id == parent_id
    assert handle.page is popup_page
    assert handle.context_key == tc._tabs[parent_id].context_key


@pytest.mark.asyncio
async def test_on_popup_close_switches_to_parent() -> None:
    """_on_popup_close removes popup tab and switches back to parent."""
    tc = _make_mock_tc()
    parent_id = await _add_mock_tab(tc)

    popup_page = _make_mock_page()
    await tc._on_popup(popup_page)
    popup_id = tc.get_active_tab_id()

    tc._on_popup_close(popup_id)

    assert popup_id not in tc._tabs
    assert tc.get_active_tab_id() == parent_id
    assert len(tc._tabs) == 1


@pytest.mark.asyncio
async def test_on_popup_close_fallback_when_parent_gone() -> None:
    """When parent tab is already closed, popup close falls back to another tab."""
    tc = _make_mock_tc()
    t1 = await _add_mock_tab(tc)
    t2 = await _add_mock_tab(tc)

    popup_page = _make_mock_page()
    await tc._on_popup(popup_page)
    popup_id = tc.get_active_tab_id()
    parent_of_popup = tc._tabs[popup_id].parent_tab_id

    tc._tabs.pop(parent_of_popup)

    tc._on_popup_close(popup_id)

    assert popup_id not in tc._tabs
    active = tc._active_tab_id
    assert active is not None
    assert active in tc._tabs


@pytest.mark.asyncio
async def test_close_tab_popup_direct_close() -> None:
    """Closing a popup tab calls page.close() instead of pool.release_page()."""
    tc = _make_mock_tc()
    await _add_mock_tab(tc)

    popup_page = _make_mock_page()
    await tc._on_popup(popup_page)
    popup_id = tc.get_active_tab_id()

    await tc.close_tab(popup_id)

    popup_page.close.assert_awaited_once()
    tc._pool.release_page.assert_not_awaited()


@pytest.mark.asyncio
async def test_close_tab_normal_uses_pool() -> None:
    """Closing a normal tab uses pool.release_page()."""
    tc = _make_mock_tc()
    tab_id = await _add_mock_tab(tc)

    await tc.close_tab(tab_id)

    tc._pool.release_page.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_popup_discards_from_attached_set() -> None:
    """Closing a popup removes its page id from _popup_attached_pages."""
    tc = _make_mock_tc()
    await _add_mock_tab(tc)

    popup_page = _make_mock_page()
    await tc._on_popup(popup_page)
    popup_id = tc.get_active_tab_id()

    assert id(popup_page) in tc._popup_attached_pages

    await tc.close_tab(popup_id)

    assert id(popup_page) not in tc._popup_attached_pages


@pytest.mark.asyncio
async def test_popup_inherits_parent_context_key() -> None:
    """Popup tab inherits context_key from parent tab."""
    tc = _make_mock_tc()
    await _add_mock_tab(tc, context_key="user-session-123")

    popup_page = _make_mock_page()
    await tc._on_popup(popup_page)

    popup_handle = tc._tabs[tc.get_active_tab_id()]
    assert popup_handle.context_key == "user-session-123"


@pytest.mark.asyncio
async def test_popup_lru_eviction_when_max_tabs() -> None:
    """Popup triggers LRU eviction when MAX_TABS is reached."""
    tc = _make_mock_tc()
    first_tab = await _add_mock_tab(tc)

    for _ in range(9):
        await _add_mock_tab(tc)

    assert len(tc._tabs) == 10

    popup_page = _make_mock_page()
    await tc._on_popup(popup_page)

    assert len(tc._tabs) == 10
    assert first_tab not in tc._tabs


@pytest.mark.asyncio
async def test_on_popup_close_noop_for_unknown_tab() -> None:
    """_on_popup_close is a no-op for an already-removed tab."""
    tc = _make_mock_tc()
    await _add_mock_tab(tc)

    tc._on_popup_close("nonexistent_tab")

    assert len(tc._tabs) == 1


@pytest.mark.asyncio
async def test_recursive_popup_listener() -> None:
    """_on_popup attaches listener to the popup page itself for nested popups."""
    tc = _make_mock_tc()
    await _add_mock_tab(tc)

    popup_page = _make_mock_page()
    await tc._on_popup(popup_page)

    assert id(popup_page) in tc._popup_attached_pages


@pytest.mark.asyncio
async def test_close_tab_popup_already_closed() -> None:
    """Closing a popup whose page is already closed skips page.close()."""
    tc = _make_mock_tc()
    await _add_mock_tab(tc)

    popup_page = _make_mock_page()
    popup_page.is_closed = MagicMock(return_value=True)
    await tc._on_popup(popup_page)
    popup_id = tc.get_active_tab_id()

    await tc.close_tab(popup_id)

    popup_page.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_close_tab_popup_close_exception() -> None:
    """Closing a popup handles page.close() exceptions gracefully."""
    tc = _make_mock_tc()
    parent_id = await _add_mock_tab(tc)

    popup_page = _make_mock_page()
    popup_page.close = AsyncMock(side_effect=RuntimeError("Connection closed"))
    await tc._on_popup(popup_page)
    popup_id = tc.get_active_tab_id()

    await tc.close_tab(popup_id)

    assert popup_id not in tc._tabs
    assert tc.get_active_tab_id() == parent_id


@pytest.mark.asyncio
async def test_on_popup_no_active_tab() -> None:
    """_on_popup with no active tab sets parent_tab_id to None and context_key to empty."""
    tc = _make_mock_tc()
    tc._active_tab_id = None

    popup_page = _make_mock_page()
    await tc._on_popup(popup_page)

    popup_handle = tc._tabs[tc.get_active_tab_id()]
    assert popup_handle.is_popup is True
    assert popup_handle.parent_tab_id is None
    assert popup_handle.context_key == ""


@pytest.mark.asyncio
async def test_close_all_with_popup_tabs() -> None:
    """close_all correctly closes both normal and popup tabs."""
    tc = _make_mock_tc()
    await _add_mock_tab(tc)
    await _add_mock_tab(tc)

    popup_page = _make_mock_page()
    await tc._on_popup(popup_page)

    assert len(tc._tabs) == 3

    await tc.close_all()

    assert len(tc._tabs) == 0
    popup_page.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_tab_popup_switches_to_parent() -> None:
    """close_tab (not _on_popup_close) also switches back to parent tab."""
    tc = _make_mock_tc()
    parent_id = await _add_mock_tab(tc)

    popup_page = _make_mock_page()
    await tc._on_popup(popup_page)
    popup_id = tc.get_active_tab_id()

    assert tc.get_active_tab_id() == popup_id

    await tc.close_tab(popup_id)

    assert tc.get_active_tab_id() == parent_id


@pytest.mark.asyncio
async def test_on_popup_close_non_active_popup() -> None:
    """_on_popup_close for a non-active popup doesn't change active tab."""
    tc = _make_mock_tc()
    parent_id = await _add_mock_tab(tc)

    popup_page = _make_mock_page()
    await tc._on_popup(popup_page)
    popup_id = tc.get_active_tab_id()

    await tc.switch_tab(parent_id)
    assert tc.get_active_tab_id() == parent_id

    tc._on_popup_close(popup_id)

    assert tc.get_active_tab_id() == parent_id
    assert popup_id not in tc._tabs


# =============================================================================
# Integration: real browser popup via window.open()
# =============================================================================


@pytest.mark.asyncio
async def test_integration_popup_capture_real_browser() -> None:
    """Integration: window.open() triggers popup capture in a real browser."""
    try:
        from patchright.async_api import async_playwright
    except ImportError:
        pytest.skip("patchright not installed")

    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context()
        parent_page = await context.new_page()

        pool = MagicMock()
        pool.release_page = AsyncMock()
        tc = TabController(pool, ContextType.CRAWL)

        parent_handle = TabHandle(
            page=parent_page, tab_id="tab0", context_key="test"
        )
        tc._tabs["tab0"] = parent_handle
        tc._active_tab_id = "tab0"
        tc._tab_counter = 1

        tc.attach_popup_listener(parent_page)

        popup_captured = asyncio.Event()
        captured_tab_id: str | None = None

        original_on_popup = tc._on_popup

        async def _spy_on_popup(popup_page):
            nonlocal captured_tab_id
            await original_on_popup(popup_page)
            captured_tab_id = tc.get_active_tab_id()
            popup_captured.set()

        tc._on_popup = _spy_on_popup
        parent_page.remove_listener("popup", original_on_popup)
        parent_page.on("popup", _spy_on_popup)

        await parent_page.evaluate("() => window.open('about:blank', '_blank')")

        await asyncio.wait_for(popup_captured.wait(), timeout=5.0)

        assert captured_tab_id is not None
        assert captured_tab_id != "tab0"
        assert tc.get_active_tab_id() == captured_tab_id

        popup_handle = tc._tabs[captured_tab_id]
        assert popup_handle.is_popup is True
        assert popup_handle.parent_tab_id == "tab0"

        await tc.close_tab(captured_tab_id)
        assert tc.get_active_tab_id() == "tab0"
    finally:
        await context.close()
        await browser.close()
        await pw.stop()


@pytest.mark.asyncio
async def test_integration_popup_self_close_via_window_close() -> None:
    """Integration: popup closed via window.close() triggers _on_popup_close."""
    try:
        from patchright.async_api import async_playwright
    except ImportError:
        pytest.skip("patchright not installed")

    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context()
        parent_page = await context.new_page()

        pool = MagicMock()
        pool.release_page = AsyncMock()
        tc = TabController(pool, ContextType.CRAWL)

        parent_handle = TabHandle(
            page=parent_page, tab_id="tab0", context_key="test"
        )
        tc._tabs["tab0"] = parent_handle
        tc._active_tab_id = "tab0"
        tc._tab_counter = 1

        tc.attach_popup_listener(parent_page)

        popup_captured = asyncio.Event()
        popup_closed = asyncio.Event()
        captured_tab_id: str | None = None

        original_on_popup = tc._on_popup
        original_on_popup_close = tc._on_popup_close

        async def _spy_on_popup(popup_page):
            nonlocal captured_tab_id
            await original_on_popup(popup_page)
            captured_tab_id = tc.get_active_tab_id()
            popup_captured.set()

        def _spy_on_popup_close(tab_id):
            original_on_popup_close(tab_id)
            popup_closed.set()

        tc._on_popup = _spy_on_popup
        tc._on_popup_close = _spy_on_popup_close
        parent_page.remove_listener("popup", original_on_popup)
        parent_page.on("popup", _spy_on_popup)

        popup_ref = await parent_page.evaluate(
            "() => { const w = window.open('about:blank', '_blank'); return !!w; }"
        )
        assert popup_ref is True

        await asyncio.wait_for(popup_captured.wait(), timeout=5.0)
        assert captured_tab_id is not None

        popup_handle = tc._tabs[captured_tab_id]
        popup_handle.page.on("close", lambda: _spy_on_popup_close(captured_tab_id))

        await popup_handle.page.evaluate("() => window.close()")

        await asyncio.wait_for(popup_closed.wait(), timeout=5.0)

        assert captured_tab_id not in tc._tabs
        assert tc.get_active_tab_id() == "tab0"
    finally:
        await context.close()
        await browser.close()
        await pw.stop()
