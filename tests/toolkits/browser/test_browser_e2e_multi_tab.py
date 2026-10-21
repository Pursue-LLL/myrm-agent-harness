"""E2E tests for multi-tab operations and coordination.

Tests complex multi-tab scenarios:
- Tab creation and management
- Cross-tab data coordination
- Tab isolation and context switching
- Resource sharing between tabs

Run with: pytest -m e2e tests/toolkits/browser/test_browser_e2e_multi_tab.py
"""

from __future__ import annotations

import asyncio

import pytest

from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.session import BrowserSession


@pytest.fixture
async def browser_pool() -> GlobalBrowserPool:
    """Real browser pool for E2E tests."""
    pool = GlobalBrowserPool(max_browsers=1)
    await pool.warmup(browsers=1, pages_per_context=2)
    yield pool
    await pool.shutdown()


@pytest.fixture
async def browser_session(browser_pool: GlobalBrowserPool) -> BrowserSession:
    """BrowserSession for multi-tab tests."""
    session = BrowserSession(browser_pool, ContextType.AGENT)
    yield session
    await session.close()


# =============================================================================
# Multi-Tab 1: Create and switch between tabs
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_multitab_create_and_switch(browser_session: BrowserSession) -> None:
    """Create multiple tabs and switch between them."""
    # Create 3 tabs with different content
    tabs = []
    for i in range(3):
        tab_id = await browser_session.new_tab("about:blank")
        page = browser_session._tab_controller._tabs[tab_id].page
        await page.set_content(f"<html><body><h1>Tab {i + 1}</h1></body></html>")
        await asyncio.sleep(0.2)
        tabs.append(tab_id)

    # Verify tab count
    assert len(browser_session.list_tabs()) == 3

    # Switch to each tab and verify content
    for i, tab_id in enumerate(tabs):
        await browser_session.switch_tab(tab_id)
        await asyncio.sleep(0.2)
        text = await browser_session.extract_text()
        assert f"Tab {i + 1}" in text


# =============================================================================
# Multi-Tab 2: Parallel form filling
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_multitab_parallel_form_filling(browser_session: BrowserSession) -> None:
    """Fill forms in multiple tabs."""
    # Create 2 tabs with forms
    tab1 = await browser_session.new_tab("about:blank")
    page1 = browser_session._tab_controller._tabs[tab1].page
    await page1.set_content("""
        <html><body>
            <h1>Form A</h1>
            <input type="text" id="field" placeholder="Field A"/>
            <div id="display"></div>
            <script>
                document.getElementById('field').addEventListener('input', (e) => {
                    document.getElementById('display').innerText = 'Value: ' + e.target.value;
                });
            </script>
        </body></html>
    """)
    await asyncio.sleep(0.3)

    # Fill form A
    await page1.fill("#field", "Data A")
    await asyncio.sleep(0.3)
    text1 = await browser_session.extract_text()
    assert "Value: Data A" in text1

    # Create tab 2
    tab2 = await browser_session.new_tab("about:blank")
    page2 = browser_session._tab_controller._tabs[tab2].page
    await page2.set_content("""
        <html><body>
            <h1>Form B</h1>
            <input type="text" id="field" placeholder="Field B"/>
            <div id="display"></div>
            <script>
                document.getElementById('field').addEventListener('input', (e) => {
                    document.getElementById('display').innerText = 'Value: ' + e.target.value;
                });
            </script>
        </body></html>
    """)
    await asyncio.sleep(0.3)

    # Fill form B
    await page2.fill("#field", "Data B")
    await asyncio.sleep(0.3)
    text2 = await browser_session.extract_text()
    assert "Value: Data B" in text2

    # Switch back to tab 1 and verify data persisted
    await browser_session.switch_tab(tab1)
    await asyncio.sleep(0.2)
    text1_again = await browser_session.extract_text()
    assert "Value: Data A" in text1_again


# =============================================================================
# Multi-Tab 3: Close tab and verify cleanup
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_multitab_close_and_cleanup(browser_session: BrowserSession) -> None:
    """Close tabs and verify proper cleanup."""
    # Create 3 tabs
    tabs = []
    for i in range(3):
        tab_id = await browser_session.new_tab("about:blank")
        page = browser_session._tab_controller._tabs[tab_id].page
        await page.set_content(f"<html><body><h1>Tab {i + 1}</h1></body></html>")
        tabs.append(tab_id)

    assert len(browser_session.list_tabs()) == 3

    # Close middle tab
    await browser_session.close_tab(tabs[1])
    await asyncio.sleep(0.2)

    assert len(browser_session.list_tabs()) == 2

    # Verify remaining tabs still work
    await browser_session.switch_tab(tabs[0])
    text0 = await browser_session.extract_text()
    assert "Tab 1" in text0

    await browser_session.switch_tab(tabs[2])
    text2 = await browser_session.extract_text()
    assert "Tab 3" in text2


# =============================================================================
# Multi-Tab 4: Independent JavaScript contexts
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_multitab_independent_js_contexts(browser_session: BrowserSession) -> None:
    """Verify each tab has independent JavaScript context."""
    # Create 2 tabs with same variable name but different values
    tab1 = await browser_session.new_tab("about:blank")
    page1 = browser_session._tab_controller._tabs[tab1].page
    await page1.set_content("""
        <html><body>
            <h1>Tab 1</h1>
            <div id="data" data-value="Tab1Value">Tab 1 Content</div>
            <script>window.myVar = 'Tab1Value';</script>
        </body></html>
    """)
    await asyncio.sleep(0.5)

    # Set variable and verify immediately
    await page1.evaluate("window.myVar = 'Tab1Value'")
    value1_check = await page1.evaluate("window.myVar")
    assert value1_check == "Tab1Value"

    tab2 = await browser_session.new_tab("about:blank")
    page2 = browser_session._tab_controller._tabs[tab2].page
    await page2.set_content("""
        <html><body>
            <h1>Tab 2</h1>
            <div id="data" data-value="Tab2Value">Tab 2 Content</div>
            <script>window.myVar = 'Tab2Value';</script>
        </body></html>
    """)
    await asyncio.sleep(0.5)

    await page2.evaluate("window.myVar = 'Tab2Value'")
    value2_check = await page2.evaluate("window.myVar")
    assert value2_check == "Tab2Value"

    # Verify tabs have different content
    text1 = await page1.evaluate("document.getElementById('data').innerText")
    text2 = await page2.evaluate("document.getElementById('data').innerText")
    assert text1 != text2
    assert "Tab 1" in text1 and "Tab 2" in text2


# =============================================================================
# Multi-Tab 5: Concurrent screenshot capture
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_multitab_concurrent_screenshots(browser_session: BrowserSession) -> None:
    """Capture screenshots from multiple tabs."""
    # Create 2 tabs with different content
    tab1 = await browser_session.new_tab("about:blank")
    page1 = browser_session._tab_controller._tabs[tab1].page
    await page1.set_content("<html><body style='background:red'><h1>Red Tab</h1></body></html>")
    await asyncio.sleep(0.3)

    tab2 = await browser_session.new_tab("about:blank")
    page2 = browser_session._tab_controller._tabs[tab2].page
    await page2.set_content("<html><body style='background:blue'><h1>Blue Tab</h1></body></html>")
    await asyncio.sleep(0.3)

    # Capture screenshot from tab 2
    await browser_session.switch_tab(tab2)
    screenshot2 = await browser_session.extract_screenshot()
    assert len(screenshot2) > 1000

    # Switch to tab 1 and capture
    await browser_session.switch_tab(tab1)
    screenshot1 = await browser_session.extract_screenshot()
    assert len(screenshot1) > 1000

    # Screenshots should be different (different content)
    assert screenshot1 != screenshot2


# =============================================================================
# Multi-Tab 6: Tab with error doesn't affect others
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_multitab_error_isolation(browser_session: BrowserSession) -> None:
    """Error in one tab should not affect others."""
    # Create healthy tab
    tab1 = await browser_session.new_tab("about:blank")
    page1 = browser_session._tab_controller._tabs[tab1].page
    await page1.set_content("<html><body><h1>Healthy Tab</h1></body></html>")
    await asyncio.sleep(0.3)

    # Create tab with JS error
    tab2 = await browser_session.new_tab("about:blank")
    page2 = browser_session._tab_controller._tabs[tab2].page
    await page2.set_content("""
        <html><body>
            <h1>Error Tab</h1>
            <script>throw new Error('Intentional error');</script>
        </body></html>
    """)
    await asyncio.sleep(0.3)

    # Tab 2 may have error, but tab 1 should still work
    await browser_session.switch_tab(tab1)
    text1 = await browser_session.extract_text()
    assert "Healthy Tab" in text1

    # Can still take snapshot of healthy tab
    result = await browser_session.snapshot(scope="content", diff=False)
    assert result.meta is not None


# =============================================================================
# Multi-Tab 7: Navigate all tabs
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_multitab_navigate_all(browser_session: BrowserSession) -> None:
    """Navigate multiple tabs to different URLs."""
    # Create 2 tabs and navigate each
    tab1 = await browser_session.new_tab("about:blank")
    page1 = browser_session._tab_controller._tabs[tab1].page
    await page1.set_content("<html><body><h1>Page A</h1></body></html>")
    await asyncio.sleep(0.3)

    tab2 = await browser_session.new_tab("about:blank")
    page2 = browser_session._tab_controller._tabs[tab2].page
    await page2.set_content("<html><body><h1>Page B</h1></body></html>")
    await asyncio.sleep(0.3)

    # Navigate tab 1 to new content
    await browser_session.switch_tab(tab1)
    await page1.set_content("<html><body><h1>Page A Updated</h1></body></html>")
    await asyncio.sleep(0.3)

    text1 = await browser_session.extract_text()
    assert "Page A Updated" in text1

    # Tab 2 should still have original content
    await browser_session.switch_tab(tab2)
    text2 = await browser_session.extract_text()
    assert "Page B" in text2


# =============================================================================
# Multi-Tab 8: List tabs operation
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_multitab_list_tabs(browser_session: BrowserSession) -> None:
    """Test listing all open tabs."""
    # Create 4 tabs
    tabs = []
    for _i in range(4):
        tab_id = await browser_session.new_tab("about:blank")
        tabs.append(tab_id)
        await asyncio.sleep(0.1)

    # List tabs
    tab_list = browser_session.list_tabs()
    assert len(tab_list) == 4

    # All created tabs should be in list
    for tab_id in tabs:
        assert tab_id in tab_list


# =============================================================================
# Multi-Tab 9: Get active tab info
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_multitab_get_active_tab(browser_session: BrowserSession) -> None:
    """Test getting active tab information."""
    tab1 = await browser_session.new_tab("about:blank")
    assert browser_session.get_active_tab_id() == tab1

    tab2 = await browser_session.new_tab("about:blank")
    assert browser_session.get_active_tab_id() == tab2

    await browser_session.switch_tab(tab1)
    assert browser_session.get_active_tab_id() == tab1


# =============================================================================
# Multi-Tab 10: Close all tabs except one
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_multitab_close_all_except_one(browser_session: BrowserSession) -> None:
    """Close multiple tabs, keeping one active."""
    # Create 4 tabs
    tabs = []
    for i in range(4):
        tab_id = await browser_session.new_tab("about:blank")
        page = browser_session._tab_controller._tabs[tab_id].page
        await page.set_content(f"<html><body><h1>Tab {i + 1}</h1></body></html>")
        tabs.append(tab_id)
        await asyncio.sleep(0.1)

    # Close first 3 tabs
    for tab_id in tabs[:3]:
        await browser_session.close_tab(tab_id)
        await asyncio.sleep(0.1)

    # Only last tab should remain
    assert len(browser_session.list_tabs()) == 1
    assert tabs[3] in browser_session.list_tabs()

    # Verify last tab content
    text = await browser_session.extract_text()
    assert "Tab 4" in text


# =============================================================================
# Multi-Tab 11: Tab creation during interaction
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_multitab_create_during_interaction(browser_session: BrowserSession) -> None:
    """Create new tab while interacting with current tab."""
    tab1 = await browser_session.new_tab("about:blank")
    page1 = browser_session._tab_controller._tabs[tab1].page
    await page1.set_content("""
        <html><body>
            <button id="btn" onclick="this.innerText='Clicked'">Click Me</button>
        </body></html>
    """)
    await asyncio.sleep(0.3)

    # Click button in tab 1
    await page1.click("#btn")
    await asyncio.sleep(0.2)

    # Create tab 2 without switching
    tab2 = await browser_session.new_tab("about:blank")
    page2 = browser_session._tab_controller._tabs[tab2].page
    await page2.set_content("<html><body><h1>Tab 2</h1></body></html>")
    await asyncio.sleep(0.3)

    # Current tab should be tab 2
    text_current = await browser_session.extract_text()
    assert "Tab 2" in text_current

    # Switch back to tab 1, button state should persist
    await browser_session.switch_tab(tab1)
    text1 = await browser_session.extract_text()
    assert "Clicked" in text1


# =============================================================================
# Multi-Tab 12: Memory efficient tab management
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_multitab_memory_efficient_management(browser_session: BrowserSession) -> None:
    """Test creating, using, and closing tabs efficiently."""
    # Create and close tabs in sequence
    for i in range(10):
        tab_id = await browser_session.new_tab("about:blank")
        page = browser_session._tab_controller._tabs[tab_id].page
        await page.set_content(f"<html><body><h1>Tab {i}</h1></body></html>")
        await asyncio.sleep(0.1)

        # Extract content
        text = await browser_session.extract_text()
        assert f"Tab {i}" in text

        # Close if not last
        if i < 9:
            await browser_session.close_tab(tab_id)
            await asyncio.sleep(0.05)

    # Should only have 1 tab remaining
    assert len(browser_session.list_tabs()) == 1
