"""Real-Chromium proof that a crashed tab is replaced before the next tool call uses it.

A renderer crash leaves the Page object open and every call on it failing, and a snapshot of it
still answers from the cache ("no DOM changes") as if the page were alive. Each scenario has a
control group (the same calls on a healthy tab change nothing). Run with:
`pytest -m integration tests/toolkits/browser/session/test_crashed_tab_recovery_integration.py`.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

import pytest
from langchain_core.tools import BaseTool

from myrm_agent_harness.toolkits.browser.exceptions import RefNotFoundError
from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.session import BrowserSession
from myrm_agent_harness.toolkits.browser.tools import create_browser_tools
from myrm_agent_harness.toolkits.browser.utils.page_health import probe_alive
from tests.toolkits.browser._browser_available import chromium_available
from tests.toolkits.browser._page_crash import crash_page

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.asyncio,
    pytest.mark.skipif(not chromium_available(), reason="Chromium not available"),
]

_RESET_NOTICE = "The tab was reset to a blank page"
_STALE_SNAPSHOT_CLAIM = "No DOM changes detected"
_PAGE = "<html><title>Shop</title><body><button>Buy</button></body></html>"
_TEARDOWN_BOUND_S = 20.0


@pytest.fixture
async def pool() -> AsyncIterator[GlobalBrowserPool]:
    browser_pool = GlobalBrowserPool(max_browsers=1)
    yield browser_pool
    with contextlib.suppress(Exception):
        await asyncio.wait_for(browser_pool.shutdown(), timeout=_TEARDOWN_BOUND_S)


@pytest.fixture
async def session(pool: GlobalBrowserPool) -> AsyncIterator[BrowserSession]:
    browser_session = BrowserSession(pool, ContextType.AGENT, allow_private_networks=True)
    await browser_session.new_tab()
    await browser_session._tab_controller.get_active_page().set_content(_PAGE)
    yield browser_session
    with contextlib.suppress(Exception):
        await asyncio.wait_for(browser_session.close(), timeout=_TEARDOWN_BOUND_S)


@pytest.fixture
def tools(session: BrowserSession) -> dict[str, BaseTool]:
    return {tool.name: tool for tool in create_browser_tools(session)}


async def test_a_snapshot_after_a_crash_is_a_fresh_blank_tab_not_a_stale_answer(
    session: BrowserSession, pool: GlobalBrowserPool, tools: dict[str, BaseTool]
) -> None:
    snapshot = tools["browser_snapshot_tool"]
    await snapshot.ainvoke({})
    unchanged = await snapshot.ainvoke({})
    assert _STALE_SNAPSHOT_CLAIM in unchanged, "control: on a healthy tab the second snapshot is a diff"
    assert _RESET_NOTICE not in unchanged
    tab_before = session.get_active_tab_id()

    crashed = session._tab_controller.get_active_page()
    await crash_page(pool, crashed)
    assert not await probe_alive(crashed), "control: the renderer really died"

    after = await snapshot.ainvoke({})
    again = await snapshot.ainvoke({})

    assert _RESET_NOTICE in after
    assert _STALE_SNAPSHOT_CLAIM not in after
    assert _RESET_NOTICE not in again, "the model hears about the reset once"
    assert session.get_active_tab_id() != tab_before
    assert await probe_alive(session._tab_controller.get_active_page())


async def test_a_click_with_a_ref_from_before_the_crash_is_refused_and_the_next_read_explains_why(
    session: BrowserSession, pool: GlobalBrowserPool, tools: dict[str, BaseTool]
) -> None:
    await tools["browser_snapshot_tool"].ainvoke({})
    crashed = session._tab_controller.get_active_page()
    await crash_page(pool, crashed)

    with pytest.raises(RefNotFoundError):
        await tools["browser_interact_tool"].ainvoke({"action": "click", "ref": "e0"})

    assert crashed.is_closed()
    assert _RESET_NOTICE in await tools["browser_snapshot_tool"].ainvoke({})


async def test_healthy_tool_calls_never_replace_the_tab(session: BrowserSession, tools: dict[str, BaseTool]) -> None:
    """Control: the entry check reads the browser's crash report, so it cannot misfire on a live tab."""
    tab_before = session.get_active_tab_id()
    page_before = session._tab_controller.get_active_page()

    for _ in range(3):
        result = await tools["browser_snapshot_tool"].ainvoke({})
        assert _RESET_NOTICE not in result

    assert session.get_active_tab_id() == tab_before
    assert session._tab_controller.get_active_page() is page_before
