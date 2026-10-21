"""Real-Chromium proof that only the active tab feeds the network log.

The log must follow `switch_tab` and `close_tab`; a page that is no longer active must stop
reporting into it. Each scenario has a control group (the active tab's own request is logged), and
the background request is issued first, so seeing the control entry also proves the earlier events
were already processed. Run with:
`pytest -m integration tests/toolkits/browser/session/test_network_log_tab_switch.py`.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

import pytest
from patchright.async_api import Page

from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.session import BrowserSession
from tests.toolkits.browser._browser_available import chromium_available
from tests.toolkits.browser._stall_servers import StallServers

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.asyncio,
    pytest.mark.skipif(not chromium_available(), reason="Chromium not available"),
]

_TEARDOWN_BOUND_S = 20.0


@pytest.fixture
async def servers() -> AsyncIterator[StallServers]:
    async with StallServers() as running:
        yield running


@pytest.fixture
async def session() -> AsyncIterator[BrowserSession]:
    pool = GlobalBrowserPool(max_browsers=1)
    browser_session = BrowserSession(pool, ContextType.AGENT, allow_private_networks=True)
    yield browser_session
    with contextlib.suppress(Exception):
        await asyncio.wait_for(browser_session.close(), timeout=_TEARDOWN_BOUND_S)
    with contextlib.suppress(Exception):
        await asyncio.wait_for(pool.shutdown(), timeout=_TEARDOWN_BOUND_S)


async def _fetch(page: Page, url: str) -> None:
    """Issue a request from `page`; `no-cors` so the opaque cross-origin response still completes."""
    await page.evaluate("(url) => fetch(url, { mode: 'no-cors' })", url)


def _logged(session: BrowserSession, marker: str) -> bool:
    return marker in session.get_network_log("all")


async def test_a_background_tab_stops_reporting_after_switch_tab(
    session: BrowserSession, servers: StallServers
) -> None:
    background = await session.new_tab()
    foreground = await session.new_tab()
    await session.switch_tab(foreground)
    await session.switch_tab(background)

    await _fetch(session._tab_controller.get_page(foreground), f"{servers.ok}?from=background")
    await _fetch(session._tab_controller.get_page(background), f"{servers.ok}?from=active")

    assert _logged(session, "from=active")
    assert not _logged(session, "from=background")


async def test_a_closed_active_tab_hands_the_log_to_the_next_active_tab(
    session: BrowserSession, servers: StallServers
) -> None:
    first = await session.new_tab()
    second = await session.new_tab()
    first_page = session._tab_controller.get_page(first)

    await session.close_tab(second)

    await _fetch(first_page, f"{servers.ok}?from=survivor")
    assert _logged(session, "from=survivor")
