"""Real-Chromium proof that a stalled or wedged page cannot trap the browser session.

Every scenario has a control group (a healthy server, or the call made without the cancel boundary)
so a pass cannot be an artifact of the setup. Run with:
`pytest -m integration tests/toolkits/browser/session/test_stall_resilience_integration.py`.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.browser import navigation
from myrm_agent_harness.toolkits.browser.exceptions import BrowserNavigationError
from myrm_agent_harness.toolkits.browser.navigation import ssrf_guard
from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.pool.config import BrowserPoolConfig
from myrm_agent_harness.toolkits.browser.pool.crash_watchdog import _pooled_page_answers
from myrm_agent_harness.toolkits.browser.session import BrowserSession
from myrm_agent_harness.toolkits.browser.tools import create_browser_tools
from myrm_agent_harness.toolkits.browser.tools.cancel_boundary import CANCELLED_RESULT
from myrm_agent_harness.toolkits.browser.utils.page_health import (
    PageUnresponsiveError,
    probe_alive,
    probe_browser_alive,
)
from myrm_agent_harness.utils.runtime.cancellation import CancellationToken, set_cancel_token
from tests.toolkits.browser._browser_available import chromium_available
from tests.toolkits.browser._stall_servers import StallServers

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.skipif(not chromium_available(), reason="Chromium not available"),
]

_NAVIGATION_BUDGET_MS = 1500
_TEARDOWN_BOUND_S = 20.0
_SPIN_SCRIPT = "() => { while (true) {} }"


@pytest.fixture
def short_navigation_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(navigation, "_NAVIGATION_TIMEOUT_MS", _NAVIGATION_BUDGET_MS)


@pytest.fixture
async def servers() -> AsyncIterator[StallServers]:
    async with StallServers(slow_delay_s=0.5) as running:
        yield running


@pytest.fixture(params=["local", "guarded"])
def mode(request: pytest.FixtureRequest) -> str:
    """`local` navigates with plain goto, `guarded` through the SSRF route guard (cloud hosting)."""
    return request.param


@pytest.fixture
async def pool(mode: str) -> AsyncIterator[GlobalBrowserPool]:
    # Cloud hosting rejects loopback in the context filter as well; the guarded run drops that filter so
    # the route guard (the code under test) is the only layer that judges the loopback stall servers.
    config = BrowserPoolConfig.minimal() if mode == "guarded" else None
    browser_pool = GlobalBrowserPool(max_browsers=1, config=config)
    yield browser_pool
    with contextlib.suppress(Exception):
        await asyncio.wait_for(browser_pool.shutdown(), timeout=_TEARDOWN_BOUND_S)


@pytest.fixture
async def session(mode: str, pool: GlobalBrowserPool, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[BrowserSession]:
    if mode == "guarded":
        # The stall servers are loopback hosts the guard rejects by design; treat them as public hosts.
        monkeypatch.setattr(ssrf_guard, "assert_browser_navigation_allowed", AsyncMock(return_value=None))
    browser_session = BrowserSession(pool, ContextType.AGENT, allow_private_networks=mode == "local")
    yield browser_session
    set_cancel_token(None)
    with contextlib.suppress(Exception):
        await asyncio.wait_for(browser_session.close(), timeout=_TEARDOWN_BOUND_S)


async def _spin_renderer(page) -> asyncio.Task:
    """Wedge the page's renderer in a script loop (nothing page-level answers afterwards)."""
    spinner = asyncio.create_task(page.evaluate(_SPIN_SCRIPT))
    await asyncio.sleep(0.5)
    return spinner


async def _reap(task: asyncio.Task) -> None:
    task.cancel()
    with contextlib.suppress(BaseException):
        await asyncio.wait_for(task, timeout=5.0)


class TestStalledNavigation:
    @pytest.mark.parametrize("stall", ["silent", "headers_only"])
    async def test_stalled_server_fails_fast_and_the_session_stays_usable(
        self, session: BrowserSession, servers: StallServers, short_navigation_budget: None, stall: str
    ) -> None:
        await session.new_tab()

        started = time.monotonic()
        with pytest.raises(BrowserNavigationError):
            await session.navigate(getattr(servers, stall))
        assert time.monotonic() - started < 15.0

        assert "title=Good" in await asyncio.wait_for(session.navigate(servers.ok), timeout=30.0)

    async def test_page_that_wedges_the_renderer_while_loading_is_replaced(
        self, session: BrowserSession, servers: StallServers, short_navigation_budget: None
    ) -> None:
        await session.new_tab()
        wedged = session._tab_controller.get_active_page()

        started = time.monotonic()
        with pytest.raises(PageUnresponsiveError, match="reset to a blank page"):
            await session.navigate(servers.spinning)
        assert time.monotonic() - started < 20.0

        assert wedged.is_closed()
        assert len(session.list_tabs()) == 1
        assert "title=Good" in await asyncio.wait_for(session.navigate(servers.ok), timeout=30.0)

    async def test_control_stalled_subresource_keeps_the_committed_document(
        self, session: BrowserSession, servers: StallServers, short_navigation_budget: None
    ) -> None:
        await session.new_tab()

        assert "title=Partial" in await session.navigate(servers.stalled_subresource)

    async def test_control_slow_server_within_the_budget_is_not_an_error(
        self, session: BrowserSession, servers: StallServers, short_navigation_budget: None
    ) -> None:
        await session.new_tab()

        assert "title=Slow" in await session.navigate(servers.slow)


class TestStopDuringStall:
    async def test_stop_releases_the_stalled_navigate_tool_and_the_next_call_works(
        self, session: BrowserSession, servers: StallServers
    ) -> None:
        navigate_tool = create_browser_tools(session)[0]
        await session.new_tab()
        token = CancellationToken("req")
        set_cancel_token(token)
        invoking = asyncio.create_task(navigate_tool.ainvoke({"url": servers.silent}))
        await servers.wait_for_request(servers.silent)  # stuck inside the driver; the 30s budget cannot be what ends it

        stopped = time.monotonic()
        token.cancel()
        result = await asyncio.wait_for(invoking, timeout=20.0)

        assert result == CANCELLED_RESULT
        assert time.monotonic() - stopped < 15.0
        set_cancel_token(None)
        assert "title=Good" in await asyncio.wait_for(session.navigate(servers.ok), timeout=30.0)

    async def test_control_without_the_boundary_a_stop_leaves_the_session_blocked(
        self, session: BrowserSession, servers: StallServers
    ) -> None:
        await session.new_tab()
        token = CancellationToken("req")
        set_cancel_token(token)
        navigating = asyncio.create_task(session.navigate(servers.silent))
        await servers.wait_for_request(servers.silent)

        token.cancel()
        await asyncio.sleep(4.0)

        try:
            assert not navigating.done(), "the flag alone releases nothing: this is the defect the boundary removes"
        finally:
            await _reap(navigating)


class TestWedgedRenderer:
    async def test_spinning_renderer_is_replaced_by_a_working_tab(
        self, session: BrowserSession, servers: StallServers
    ) -> None:
        await session.new_tab(servers.ok)
        page = session._tab_controller.get_active_page()
        spinner = await _spin_renderer(page)
        try:
            assert not await probe_alive(page), "control: the renderer must really be wedged"

            replacement = await asyncio.wait_for(session.recover_active_tab(), timeout=15.0)

            assert replacement is not None
            assert session.list_tabs() == [replacement]
            assert await probe_alive(session._tab_controller.get_active_page())
            assert "title=Good" in await asyncio.wait_for(session.navigate(servers.ok), timeout=30.0)
        finally:
            await _reap(spinner)

    async def test_control_healthy_page_is_not_replaced(self, session: BrowserSession, servers: StallServers) -> None:
        await session.new_tab(servers.ok)
        tab_before = session.get_active_tab_id()

        assert await session.recover_active_tab() is None
        assert session.get_active_tab_id() == tab_before

    @pytest.mark.parametrize("wedge", ["spinning_renderer", "stalled_navigation"])
    async def test_a_wedged_page_released_to_the_pool_is_never_handed_out_again(
        self, session: BrowserSession, servers: StallServers, wedge: str
    ) -> None:
        await session.new_tab(servers.ok)
        wedged = session._tab_controller.get_active_page()
        if wedge == "spinning_renderer":
            blocker = await _spin_renderer(wedged)
        else:
            blocker = asyncio.create_task(wedged.goto(servers.silent, timeout=0))
            await servers.wait_for_request(servers.silent)
        try:
            await session._tab_controller.close_tab(session.get_active_tab_id())  # releases without closing it

            await asyncio.wait_for(session.new_tab(), timeout=30.0)
            fresh = session._tab_controller.get_active_page()

            assert fresh is not wedged
            assert await probe_alive(fresh)
        finally:
            await _reap(blocker)


class TestWatchdog:
    async def test_slow_navigation_is_not_mistaken_for_a_dead_browser(
        self, session: BrowserSession, pool: GlobalBrowserPool, servers: StallServers
    ) -> None:
        await session.new_tab()
        page = session._tab_controller.get_active_page()
        navigating = asyncio.create_task(page.goto(servers.silent, timeout=0))
        await servers.wait_for_request(servers.silent)
        inst = pool._browsers[0]
        try:
            assert not await _pooled_page_answers(inst), "control: the page-level probe reads the stall as death"

            assert await pool._check_browser_alive(inst)
            await pool._lifecycle_tick()

            assert inst in pool._browsers
        finally:
            await _reap(navigating)

    async def test_a_really_dead_browser_fails_the_browser_level_probe(
        self, session: BrowserSession, pool: GlobalBrowserPool
    ) -> None:
        await session.new_tab()
        inst = pool._browsers[0]
        assert await probe_browser_alive(inst.browser)

        await asyncio.wait_for(inst.browser.close(), timeout=15.0)

        assert not await probe_browser_alive(inst.browser)
