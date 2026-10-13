"""Real-Chromium proof of why `console_log` reports capture unavailable on the default engine.

The page really logs (an independent CDP listener sees it), yet the driver delivers no console event
to the session's logger. If a driver update starts delivering them, this test fails and the
unavailable answer in `get_console_log` must go. Run with:
`pytest -m integration tests/toolkits/browser/session/test_console_capture_integration.py`.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

import pytest

from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.session import BrowserSession
from myrm_agent_harness.toolkits.browser.session.browser_session_network_mixin import CONSOLE_CAPTURE_UNAVAILABLE
from tests.toolkits.browser._browser_available import chromium_available

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.asyncio,
    pytest.mark.skipif(not chromium_available(), reason="Chromium not available"),
]

_SETTLE_S = 1.0


@pytest.fixture
async def session() -> AsyncIterator[BrowserSession]:
    pool = GlobalBrowserPool(max_browsers=1)
    browser_session = BrowserSession(pool, ContextType.AGENT, allow_private_networks=True)
    await browser_session.new_tab()
    yield browser_session
    with contextlib.suppress(Exception):
        await asyncio.wait_for(browser_session.close(), timeout=20.0)
    with contextlib.suppress(Exception):
        await asyncio.wait_for(pool.shutdown(), timeout=20.0)


async def test_the_page_logs_but_the_default_engine_delivers_no_console_event(session: BrowserSession) -> None:
    page = session._tab_controller.get_active_page()
    seen_by_cdp: list[str] = []
    cdp = await page.context.new_cdp_session(page)
    cdp.on("Runtime.consoleAPICalled", lambda event: seen_by_cdp.append(event["type"]))
    await cdp.send("Runtime.enable")

    await page.evaluate("console.error('checkout failed')")
    await asyncio.sleep(_SETTLE_S)

    assert seen_by_cdp == ["error"], "control: the page really logged to the console"
    assert not session._console_logger._entries
    assert session.get_console_log() == CONSOLE_CAPTURE_UNAVAILABLE
