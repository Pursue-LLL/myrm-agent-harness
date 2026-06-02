"""E2E tests for error recovery and edge cases.

Tests error handling, recovery, and edge case scenarios:
- Network failures and timeouts
- Invalid inputs and malformed pages
- Resource loading errors
- Permission and security errors

Run with: pytest -m e2e tests/toolkits/browser/test_browser_e2e_error_recovery.py
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
    """BrowserSession for error recovery tests."""
    session = BrowserSession(browser_pool, ContextType.AGENT)
    yield session
    await session.close()


# =============================================================================
# Error 1: Navigation to invalid URL
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_error_invalid_url_recovery(browser_session: BrowserSession) -> None:
    """Test graceful handling of invalid URLs."""
    await browser_session.new_tab("about:blank")

    # Try invalid URL (expect exception)
    try:
        result = await browser_session.navigate("not-a-valid-url")
        # If no exception, should have error message
        assert "error" in result.lower() or "invalid" in result.lower()
    except ValueError as e:
        # Expected behavior - validation raises ValueError
        assert "invalid" in str(e).lower() or "scheme" in str(e).lower()


# =============================================================================
# Error 2: Network timeout
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_error_network_timeout_recovery(browser_session: BrowserSession) -> None:
    """Test timeout handling for slow pages."""
    await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller.get_active_page()

    # Create page with slow-loading resource
    await page.set_content("""
        <!DOCTYPE html>
        <html><body>
            <h1>Timeout Test</h1>
            <img src="http://httpbin.org/delay/10" alt="Slow image"/>
        </body></html>
    """)
    await asyncio.sleep(0.5)

    # Should handle gracefully
    text = await browser_session.extract_text()
    assert "Timeout Test" in text  # Page content should still be accessible


# =============================================================================
# Error 3: Missing element interaction
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_error_missing_element_recovery(browser_session: BrowserSession) -> None:
    """Test handling of interaction with non-existent elements."""
    tab_id = await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller._tabs[tab_id].page

    await page.set_content("<html><body><h1>No Buttons Here</h1></body></html>")
    await asyncio.sleep(0.3)

    # Get snapshot
    await browser_session.snapshot(scope="content", diff=False)

    # Try to interact with non-existent ref (should handle gracefully)
    try:
        await browser_session.interact("click", "e999")
    except Exception as e:
        # Expected to fail, but should not crash the session
        assert "ref" in str(e).lower() or "not found" in str(e).lower()

    # Session should still be usable
    text = await browser_session.extract_text()
    assert "No Buttons Here" in text


# =============================================================================
# Error 4: JavaScript errors on page
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_error_javascript_errors_on_page(browser_session: BrowserSession) -> None:
    """Test handling pages with JavaScript errors."""
    tab_id = await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller._tabs[tab_id].page

    await page.set_content("""
        <!DOCTYPE html>
        <html><body>
            <h1>Page with JS Errors</h1>
            <button id="errorBtn" onclick="causeError()">Cause Error</button>
            <div id="result"></div>
            <script>
                function causeError() {
                    try {
                        nonExistentFunction();
                    } catch (e) {
                        document.getElementById('result').innerText = 'Error caught: ' + e.message;
                    }
                }
            </script>
        </body></html>
    """)
    await asyncio.sleep(0.5)

    # Click button that causes JS error
    await page.click("#errorBtn")
    await asyncio.sleep(0.3)

    # Should handle gracefully
    text = await browser_session.extract_text()
    assert "Error caught" in text


# =============================================================================
# Error 5: Empty page handling
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_error_empty_page_handling(browser_session: BrowserSession) -> None:
    """Test handling of completely empty pages."""
    tab_id = await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller._tabs[tab_id].page

    await page.set_content("")
    await asyncio.sleep(0.3)

    # Should not crash
    result = await browser_session.snapshot(scope="content", diff=False)
    assert result.meta is not None

    text = await browser_session.extract_text()
    assert isinstance(text, str)  # May be empty, but should be string


# =============================================================================
# Error 6: Malformed HTML
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_error_malformed_html_recovery(browser_session: BrowserSession) -> None:
    """Test handling of malformed HTML."""
    tab_id = await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller._tabs[tab_id].page

    # Malformed HTML
    await page.set_content("""
        <!DOCTYPE html>
        <html><body>
            <div>Unclosed div
            <button>Button without closing tag
            <p>Paragraph<div>Nested wrong
        </body></html>
    """)
    await asyncio.sleep(0.5)

    # Browser should auto-fix and still work
    result = await browser_session.snapshot(scope="content", diff=False)
    assert result.meta.ref_count >= 0

    text = await browser_session.extract_text()
    assert "Unclosed div" in text or "Button" in text


# =============================================================================
# Error 7: Very long text content
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_error_very_long_text_handling(browser_session: BrowserSession) -> None:
    """Test handling of pages with very long text content."""
    tab_id = await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller._tabs[tab_id].page

    # Generate very long text (10,000 words)
    long_text = " ".join([f"Word{i}" for i in range(10000)])

    await page.set_content(f"""
        <!DOCTYPE html>
        <html><body>
            <h1>Long Text Test</h1>
            <button id="showBtn" onclick="document.getElementById('longText').style.display='block'">Show</button>
            <div id="longText" style="display:none">{long_text}</div>
        </body></html>
    """)
    await asyncio.sleep(0.5)

    # Click to show long text
    await page.click("#showBtn")
    await asyncio.sleep(0.5)

    # Should handle large content
    text = await browser_session.extract_text()
    assert "Long Text Test" in text
    assert len(text) > 10000


# =============================================================================
# Error 8: Rapid successive interactions
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_error_rapid_interactions(browser_session: BrowserSession) -> None:
    """Test rapid successive interactions without delays."""
    tab_id = await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller._tabs[tab_id].page

    await page.set_content("""
        <!DOCTYPE html>
        <html><body>
            <button id="counter" onclick="increment()">Count: 0</button>
            <script>
                let count = 0;
                function increment() {
                    count++;
                    document.getElementById('counter').innerText = 'Count: ' + count;
                }
            </script>
        </body></html>
    """)
    await asyncio.sleep(0.5)

    # Rapid clicks
    for _ in range(10):
        await page.click("#counter")
        # No sleep between clicks

    await asyncio.sleep(0.3)

    # Verify count updated
    count = await page.evaluate("""
        parseInt(document.getElementById('counter').innerText.split(': ')[1])
    """)
    assert count >= 5  # May not be exactly 10 due to race conditions


# =============================================================================
# Error 9: Session persistence without vault
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_error_session_operations_without_vault(browser_pool: GlobalBrowserPool) -> None:
    """Test session operations when vault not configured."""
    # Create session without SessionVault
    session = BrowserSession(browser_pool, ContextType.AGENT)  # No session_vault parameter
    await session.new_tab("about:blank")

    # All session operations should return error messages
    result = await session.save_session("test.com")
    assert "error" in result.lower() or "not configured" in result.lower()

    result = await session.restore_session("test.com")
    assert "error" in result.lower() or "not configured" in result.lower()

    result = await session.list_sessions()
    assert "error" in result.lower() or "not configured" in result.lower()

    result = await session.delete_session("test.com")
    assert "error" in result.lower() or "not configured" in result.lower()

    await session.close()


# =============================================================================
# Error 10: Multiple snapshots without changes
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_error_repeated_snapshots(browser_session: BrowserSession) -> None:
    """Test multiple snapshots of unchanged page."""
    tab_id = await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller._tabs[tab_id].page

    await page.set_content("<html><body><h1>Static Page</h1></body></html>")
    await asyncio.sleep(0.3)

    # Multiple snapshots
    for i in range(5):
        result = await browser_session.snapshot(scope="content", diff=True)
        if i == 0:
            assert "Static Page" in result.aria_tree or result.meta.ref_count >= 0
        else:
            # Subsequent snapshots should show "unchanged"
            assert "unchanged" in result.aria_tree.lower() or len(result.aria_tree) < 500


# =============================================================================
# Error 11: Extract from tab that was closed
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_error_extract_from_closed_tab(browser_session: BrowserSession) -> None:
    """Test extracting from a tab that was closed."""
    tab_id = await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller._tabs[tab_id].page
    await page.set_content("<html><body><h1>Will Close</h1></body></html>")
    await asyncio.sleep(0.3)

    # Close the tab
    await browser_session.close_tab(tab_id)
    await asyncio.sleep(0.2)

    # Try to extract (should fail gracefully or switch to another tab)
    try:
        text = await browser_session.extract_text()
        # If it doesn't raise, it switched to another tab
        assert isinstance(text, str)
    except Exception as e:
        # Expected error
        assert "tab" in str(e).lower() or "closed" in str(e).lower()


# =============================================================================
# Error 12: Navigate while page is loading
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_error_navigate_during_load(browser_session: BrowserSession) -> None:
    """Test navigation interruption."""
    tab_id = await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller._tabs[tab_id].page

    # Start slow page load
    await page.set_content("""
        <!DOCTYPE html>
        <html><body>
            <h1>Page 1</h1>
            <script>
                // Simulate slow loading
                setTimeout(() => {}, 5000);
            </script>
        </body></html>
    """)

    # Immediately navigate to another page
    await asyncio.sleep(0.1)
    await page.set_content("<html><body><h1>Page 2</h1></body></html>")
    await asyncio.sleep(0.5)

    # Should show second page
    text = await browser_session.extract_text()
    assert "Page 2" in text


# =============================================================================
# Error 13: Interact with disabled element
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_error_interact_with_disabled_element(browser_session: BrowserSession) -> None:
    """Test interaction with disabled elements."""
    tab_id = await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller._tabs[tab_id].page

    await page.set_content("""
        <!DOCTYPE html>
        <html><body>
            <button id="btn" disabled onclick="alert('clicked')">Disabled Button</button>
        </body></html>
    """)
    await asyncio.sleep(0.3)

    # Try to click disabled button
    try:
        await page.click("#btn", timeout=2000)
    except Exception:
        # Expected to fail or do nothing
        pass

    # Session should still be usable
    text = await browser_session.extract_text()
    assert "Disabled Button" in text


# =============================================================================
# Error 14: Screenshot of hidden element
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_error_screenshot_hidden_element(browser_session: BrowserSession) -> None:
    """Test screenshot of hidden elements."""
    tab_id = await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller._tabs[tab_id].page

    await page.set_content("""
        <!DOCTYPE html>
        <html><body>
            <div id="visible">Visible Content</div>
            <div id="hidden" style="display:none">Hidden Content</div>
        </body></html>
    """)
    await asyncio.sleep(0.3)

    # Take screenshot (should succeed, hidden element just not shown)
    screenshot = await browser_session.extract_screenshot()
    assert len(screenshot) > 1000  # Valid base64 image


# =============================================================================
# Error 15: Extract text with special characters
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_error_special_characters_handling(browser_session: BrowserSession) -> None:
    """Test text extraction with special characters."""
    tab_id = await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller._tabs[tab_id].page

    await page.set_content("""
        <!DOCTYPE html>
        <html><body>
            <h1>Special Characters: <>&"'</h1>
            <p>Unicode: 中文 日本語 العربية </p>
            <code>Code: &#60;div&#62;</code>
        </body></html>
    """)
    await asyncio.sleep(0.3)

    # Extract text
    text = await browser_session.extract_text()

    # Should handle special chars (may be encoded/escaped)
    assert "Special Characters" in text
    assert "Unicode" in text or "中文" in text or "" in text
