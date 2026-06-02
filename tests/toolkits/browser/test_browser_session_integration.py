"""Integration tests for BrowserSession — real headless browser.

Uses real Patchright/Chromium. Run with: pytest -m integration
Skip with: pytest -m "not integration"
"""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.browser.backends import FileVaultBackend
from myrm_agent_harness.toolkits.browser.backends.file_backend import load_or_create_key
from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.session import BrowserSession
from myrm_agent_harness.toolkits.browser.session_vault import SessionVault

_SIMPLE_HTML_CONTENT = """
<!DOCTYPE html>
<html>
<body>
    <h1>Integration Test</h1>
    <button id="btn">Click Me</button>
    <a href="#">Link</a>
    <input type="text" placeholder="Search"/>
</body>
</html>
"""


@pytest.fixture
async def browser_pool() -> GlobalBrowserPool:
    """Fresh pool for integration tests."""
    pool = GlobalBrowserPool(max_browsers=1)
    await pool.warmup(browsers=1, pages_per_context=2)
    yield pool
    await pool.shutdown()


@pytest.fixture
def session_vault(tmp_path: Path) -> SessionVault:
    """Real SessionVault with temporary storage for integration tests."""
    vault_dir = tmp_path / "session_vault"
    key_path = tmp_path / "vault.key"

    backend = FileVaultBackend(vault_dir)
    encryption_key = load_or_create_key(key_path)
    return SessionVault(backend, encryption_key)


@pytest.fixture
async def browser_session(browser_pool: GlobalBrowserPool, session_vault: SessionVault) -> BrowserSession:
    """BrowserSession with real pool and SessionVault."""
    session = BrowserSession(browser_pool, ContextType.AGENT, session_vault=session_vault)
    yield session
    await session.close()


# =============================================================================
# Core flow
# =============================================================================


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_integration_navigate_and_snapshot(
    browser_session: BrowserSession,
) -> None:
    """Navigate to page and verify snapshot returns refs."""
    tab_id = await browser_session.new_tab("about:blank")
    assert tab_id.startswith("tab")

    tab_handle = browser_session._tab_controller._tabs[tab_id]
    await tab_handle.page.set_content(_SIMPLE_HTML_CONTENT)

    result = await browser_session.snapshot(scope="content", diff=False)
    assert "Integration Test" in result.aria_tree or "button" in result.aria_tree.lower()
    assert result.meta.ref_count > 0
    assert "e0" in result.aria_tree or "e1" in result.aria_tree


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_integration_interact_click(
    browser_session: BrowserSession,
) -> None:
    """Snapshot → pick ref → click."""
    tab_id = await browser_session.new_tab("about:blank")
    tab_handle = browser_session._tab_controller._tabs[tab_id]
    await tab_handle.page.set_content(_SIMPLE_HTML_CONTENT)

    result = await browser_session.snapshot(scope="content", diff=False)

    refs = [f"e{i}" for i in range(result.meta.ref_count)]
    assert len(refs) > 0

    result = await browser_session.interact("click", refs[0])
    assert "OK" in result or "click" in result.lower()


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_integration_extract_text(
    browser_session: BrowserSession,
) -> None:
    """Extract page text."""
    tab_id = await browser_session.new_tab("about:blank")
    tab_handle = browser_session._tab_controller._tabs[tab_id]
    await tab_handle.page.set_content(_SIMPLE_HTML_CONTENT)

    text = await browser_session.extract_text()
    assert "Integration Test" in text
    assert "Click Me" in text


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_integration_extract_screenshot(
    browser_session: BrowserSession,
) -> None:
    """Screenshot returns valid base64."""
    tab_id = await browser_session.new_tab("about:blank")
    tab_handle = browser_session._tab_controller._tabs[tab_id]
    await tab_handle.page.set_content(_SIMPLE_HTML_CONTENT)

    b64 = await browser_session.extract_screenshot()
    assert len(b64) > 100
    assert b64[:20].isascii()


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_integration_evaluate_js(
    browser_session: BrowserSession,
) -> None:
    """Execute JavaScript in page."""
    tab_id = await browser_session.new_tab("about:blank")
    tab_handle = browser_session._tab_controller._tabs[tab_id]
    await tab_handle.page.set_content(_SIMPLE_HTML_CONTENT)

    result = await browser_session.evaluate("document.querySelector('h1')?.innerText ?? 'fallback'")
    assert "Integration" in result or "Test" in result


@pytest.mark.skip(reason="Network unavailable in test environment")
@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_integration_session_persistence(
    browser_session: BrowserSession,
) -> None:
    """Save and restore session (cookies + localStorage). Requires network."""
    await browser_session.new_tab("https://example.com")
    await browser_session.evaluate("localStorage.setItem('test_key', 'test_value')")

    save_result = await browser_session.save_session("integration-test.local")
    assert "Saved" in save_result

    restore_result = await browser_session.restore_session("integration-test.local")
    assert "Restored" in restore_result

    val = await browser_session.evaluate("localStorage.getItem('test_key')")
    assert "test_value" in str(val)

    await browser_session.delete_session("integration-test.local")


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_integration_save_pdf(
    browser_session: BrowserSession,
) -> None:
    """Export page to PDF."""
    tab_id = await browser_session.new_tab("about:blank")
    tab_handle = browser_session._tab_controller._tabs[tab_id]
    await tab_handle.page.set_content(_SIMPLE_HTML_CONTENT)

    result = await browser_session.save_pdf()
    assert "PDF" in result
    assert "Saved" in result

    path = result.replace("Saved PDF to ", "").strip()
    assert Path(path).exists()
    Path(path).unlink(missing_ok=True)


@pytest.mark.skip(reason="Network unavailable in test environment")
@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_integration_localhost(
    browser_pool: GlobalBrowserPool,
) -> None:
    """Navigate to localhost (requires network)."""
    session = BrowserSession(browser_pool, ContextType.AGENT)
    try:
        await session.new_tab("https://example.com")
        result = await session.navigate("https://example.com")
        assert "200" in result or "example.com" in result
        assert "200" in result

        text = await session.extract_text()
        assert "Example" in text or "example" in text.lower()
    finally:
        await session.close()
