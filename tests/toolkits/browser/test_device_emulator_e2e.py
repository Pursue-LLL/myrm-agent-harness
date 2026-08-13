"""Real-browser E2E test for runtime mobile device emulation.

Run with: pytest -m e2e tests/toolkits/browser/test_device_emulator_e2e.py
"""

from __future__ import annotations

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
    """BrowserSession for E2E tests."""
    session = BrowserSession(browser_pool, ContextType.AGENT)
    yield session
    await session.close()


MOBILE_HTML = (
    "data:text/html,<meta name=\"viewport\" "
    "content=\"width=device-width,initial-scale=1\"><title>mobile</title>"
)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_emulate_device_changes_ua_and_viewport(
    browser_session: BrowserSession,
) -> None:
    """Runtime CDP injection genuinely changes UA + viewport on the live page."""
    await browser_session.new_tab("about:blank")
    page = browser_session.get_active_page()
    await page.goto(MOBILE_HTML)

    result = await browser_session.emulate_device("iPhone 15 Pro")
    assert "Emulated 'iPhone 15 Pro'" in result
    assert "393x659" in result

    ua = await page.evaluate("navigator.userAgent")
    assert "iPhone" in ua and "Mobile" in ua

    dims = await page.evaluate(
        "() => ({ width: innerWidth, height: innerHeight, dpr: devicePixelRatio, "
        "maxTouchPoints: navigator.maxTouchPoints })"
    )
    assert dims["width"] == 393
    assert dims["height"] == 659
    assert dims["dpr"] == 3.0
    assert dims["maxTouchPoints"] > 0


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_emulate_desktop_restores_viewport(
    browser_session: BrowserSession,
) -> None:
    """'desktop' clears overrides and restores native behavior."""
    await browser_session.new_tab("about:blank")
    page = browser_session.get_active_page()
    await page.goto(MOBILE_HTML)

    await browser_session.emulate_device("iPhone 15 Pro")
    result = await browser_session.emulate_device("desktop")
    assert "Restored desktop viewport" in result

    ua = await page.evaluate("navigator.userAgent")
    assert "iPhone" not in ua

    dims = await page.evaluate(
        "() => ({ width: innerWidth, dpr: devicePixelRatio, "
        "maxTouchPoints: navigator.maxTouchPoints })"
    )
    assert dims["width"] >= 1000  # desktop-width layout viewport (context default)
    assert dims["width"] != 393
    assert dims["dpr"] == 1.0
    assert dims["maxTouchPoints"] == 0


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_list_emulatable_devices_returns_curated_set(
    browser_session: BrowserSession,
) -> None:
    """The curated device registry is exposed through the session."""
    devices = browser_session.list_emulatable_devices()
    assert "iPhone 15 Pro" in devices
    assert "Pixel 8" in devices
    assert "Galaxy S24" in devices
