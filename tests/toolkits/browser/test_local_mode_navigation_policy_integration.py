"""Real-Chromium proof of the local-mode navigation policy.

A local session may browse the user's own machine, but only where the agent navigated on purpose.
Another private origin that a page, redirect or script merely points the tab at must not load,
and cloud metadata endpoints must never load. Private origins are modelled by loopback servers on
different ports: the port the agent was sent to is "explicit", the other one is "somewhere else on
this machine". Redirect hops cannot be intercepted before the request under patchright, so a
redirect into a non-granted origin is judged after the load and the tab is reset; that boundary is
asserted as such. Run with:
`pytest -m integration tests/toolkits/browser/test_local_mode_navigation_policy_integration.py`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

from myrm_agent_harness.toolkits.browser import BrowserSession
from myrm_agent_harness.toolkits.browser.navigation.ssrf_guard import BrowserNavigationBlockedError
from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from tests.toolkits.browser._browser_available import chromium_available
from tests.toolkits.browser._redirect_servers import Reply, page, redirect, serve

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.skipif(not chromium_available(), reason="Chromium not available"),
]

_SECRET = "LOCAL-ONLY-SECRET"
_CONTEXT_TYPES = [ContextType.CRAWL, ContextType.AGENT]


@asynccontextmanager
async def _local_session(context_type: ContextType) -> AsyncIterator[BrowserSession]:
    pool = GlobalBrowserPool(max_browsers=1)
    session = BrowserSession(pool, context_type, allow_private_networks=True)
    try:
        await session.new_tab()
        yield session
    finally:
        await session.close()
        await pool.shutdown()


def _script_page(script: str) -> Reply:
    return Reply(body=f"<!DOCTYPE html><html><head></head><body>start<script>{script}</script></body></html>".encode())


async def _visible_text(session: BrowserSession) -> str:
    return await session.get_active_page().inner_text("body")


async def _wait_for_tab_url(session: BrowserSession, url: str, *, timeout_s: float = 5.0) -> None:
    """Poll the tab URL: a navigation that is aborted and replaced makes ``wait_for_url`` raise."""
    async with asyncio.timeout(timeout_s):
        while session.get_active_page().url != url:
            await asyncio.sleep(0.05)


@pytest.mark.parametrize("context_type", _CONTEXT_TYPES)
async def test_explicit_private_navigation_and_same_origin_follow_ups_work(context_type: ContextType) -> None:
    routes = {
        "/start": redirect("/home"),
        "/home": _script_page("setTimeout(() => { location = '/next'; }, 200)"),
        "/next": page("next-page"),
    }
    with serve(routes) as site:
        async with _local_session(context_type) as session:
            await session.navigate(site.url("/start"))
            await _wait_for_tab_url(session, site.url("/next"))
            assert await _visible_text(session) == "next-page"


@pytest.mark.parametrize("context_type", _CONTEXT_TYPES)
async def test_redirect_into_another_private_origin_is_blocked_and_the_tab_is_reset(
    context_type: ContextType,
) -> None:
    with (
        serve({"/api/secret": page(_SECRET)}) as elsewhere,
        serve({"/go": redirect(elsewhere.url("/api/secret"))}) as site,
    ):
        async with _local_session(context_type) as session:
            with pytest.raises(BrowserNavigationBlockedError):
                await session.navigate(site.url("/go"))
            tab = session.get_active_page()
            assert tab.url == "about:blank"
            assert _SECRET not in await tab.content()


@pytest.mark.parametrize("context_type", _CONTEXT_TYPES)
async def test_script_navigation_into_another_private_origin_is_blocked_before_any_request(
    context_type: ContextType,
) -> None:
    with serve({"/api/secret": page(_SECRET)}) as elsewhere:
        target = elsewhere.url("/api/secret")
        immediate = _script_page(f"location = '{target}'")
        delayed = _script_page(f"setTimeout(() => {{ location = '{target}'; }}, 300)")
        with serve({"/immediate": immediate, "/delayed": delayed}) as site:
            async with _local_session(context_type) as session:
                with pytest.raises(BrowserNavigationBlockedError):
                    await session.navigate(site.url("/immediate"))

                await session.navigate(site.url("/delayed"))
                await _wait_for_tab_url(session, "about:blank")
        assert elsewhere.hits == []


@pytest.mark.parametrize("context_type", _CONTEXT_TYPES)
async def test_cloud_metadata_endpoint_is_never_reachable_even_when_asked_for_explicitly(
    context_type: ContextType,
) -> None:
    with serve({"/ok": page("fine")}) as site:
        async with _local_session(context_type) as session:
            await session.navigate(site.url("/ok"))
            for metadata_url in ("http://169.254.169.254/latest/meta-data/", "http://metadata.google.internal/"):
                with pytest.raises(BrowserNavigationBlockedError):
                    await session.navigate(metadata_url)
            assert session.get_active_page().url == site.url("/ok")


async def test_blocked_explicit_navigation_keeps_the_page_the_agent_was_on() -> None:
    with serve({"/ok": page("still here")}) as site:
        async with _local_session(ContextType.AGENT) as session:
            await session.navigate(site.url("/ok"))
            with pytest.raises(BrowserNavigationBlockedError):
                await session.navigate("http://169.254.169.254/")
            assert await _visible_text(session) == "still here"


async def test_navigating_to_a_second_private_origin_explicitly_grants_it() -> None:
    with serve({"/page": page("second")}) as second, serve({"/page": page("first")}) as first:
        async with _local_session(ContextType.AGENT) as session:
            await session.navigate(first.url("/page"))
            await session.navigate(second.url("/page"))
            assert await _visible_text(session) == "second"
