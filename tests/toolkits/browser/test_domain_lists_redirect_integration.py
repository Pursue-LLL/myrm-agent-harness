"""Real-Chromium proof that the agent's domain allow/block lists also judge redirect targets.

The request filter only sees requests Chromium hands to the context route, and patchright does not
route the hops of a document redirect. A site on the allowlist could therefore bounce the tab to a
host the user forbade, and the page would load. The navigation guard now replays the redirect chain
after the load and applies the same lists to every hop it follows; a violating document is discarded
and the tab reset. Distinct hostnames on one loopback interface (``127.0.0.1`` and ``localhost``)
stand in for distinct sites; the SSRF layer is satisfied by granting the loopback origins up front so
the lists are the only policy under test. Run with:
`pytest -m integration tests/toolkits/browser/test_domain_lists_redirect_integration.py`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

from myrm_agent_harness.toolkits.browser import BrowserSession, DomainAllowlist
from myrm_agent_harness.toolkits.browser.navigation.ssrf_guard import BrowserNavigationBlockedError
from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.utils.private_origins import private_origin_grants
from tests.toolkits.browser._browser_available import chromium_available
from tests.toolkits.browser._redirect_servers import Site, page, redirect, serve

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.skipif(not chromium_available(), reason="Chromium not available"),
]

_SECRET = "FORBIDDEN-SITE-CONTENT"


def _as_localhost(site: Site) -> str:
    """The same loopback server under the hostname ``localhost`` instead of ``127.0.0.1``."""
    return site.base_url.replace("127.0.0.1", "localhost")


@asynccontextmanager
async def _session(
    *origins: str,
    allowlist: list[str] | None = None,
    blocklist: list[str] | None = None,
) -> AsyncIterator[BrowserSession]:
    pool = GlobalBrowserPool(max_browsers=1)
    session = BrowserSession(
        pool,
        ContextType.CRAWL,
        domain_allowlist=DomainAllowlist.from_strings(allowlist) if allowlist else None,
        domain_blocklist=DomainAllowlist.from_strings(blocklist) if blocklist else None,
        allow_private_networks=True,
    )
    try:
        await session.new_tab()
        grants = private_origin_grants(session.get_active_page().context)
        for origin in origins:
            grants.grant(origin)
        yield session
    finally:
        await session.close()
        await pool.shutdown()


async def _assert_blocked_and_discarded(session: BrowserSession, entry_url: str) -> None:
    with pytest.raises(BrowserNavigationBlockedError):
        await session.navigate(entry_url)
    tab = session.get_active_page()
    assert tab.url == "about:blank"
    assert _SECRET not in await tab.content()


async def test_redirect_hop_to_a_blocklisted_host_is_blocked_and_the_tab_is_reset() -> None:
    with serve({"/secret": page(_SECRET)}) as forbidden:
        target = _as_localhost(forbidden) + "/secret"
        with serve({"/go": redirect(target)}) as entry:
            async with _session(entry.base_url, _as_localhost(forbidden), blocklist=["localhost"]) as session:
                await _assert_blocked_and_discarded(session, entry.url("/go"))


async def test_redirect_hop_outside_the_allowlist_is_blocked_and_the_tab_is_reset() -> None:
    with serve({"/secret": page(_SECRET)}) as forbidden:
        target = _as_localhost(forbidden) + "/secret"
        with serve({"/go": redirect(target)}) as entry:
            async with _session(entry.base_url, _as_localhost(forbidden), allowlist=["127.0.0.1"]) as session:
                await _assert_blocked_and_discarded(session, entry.url("/go"))


async def test_a_forbidden_host_in_the_middle_of_a_chain_is_blocked() -> None:
    """entry -> forbidden host -> allowed landing page: the middle hop alone violates the policy."""
    with (
        serve({"/end": page(_SECRET)}) as landing,
        serve({"/mid": redirect(landing.url("/end"))}) as forbidden,
        serve({"/go": redirect(_as_localhost(forbidden) + "/mid")}) as entry,
    ):
        origins = (entry.base_url, _as_localhost(forbidden), landing.base_url)
        async with _session(*origins, blocklist=["localhost"]) as session:
            await _assert_blocked_and_discarded(session, entry.url("/go"))


async def test_redirect_hop_inside_the_allowlist_still_loads() -> None:
    with serve({"/home": page("welcome")}) as destination:
        target = _as_localhost(destination) + "/home"
        with serve({"/go": redirect(target)}) as entry:
            async with _session(
                entry.base_url, _as_localhost(destination), allowlist=["127.0.0.1", "localhost"]
            ) as session:
                await session.navigate(entry.url("/go"))
                assert await session.get_active_page().inner_text("body") == "welcome"


async def test_redirect_to_a_host_that_is_not_blocklisted_still_loads() -> None:
    with serve({"/home": page("welcome")}) as destination:
        target = _as_localhost(destination) + "/home"
        with serve({"/go": redirect(target)}) as entry:
            async with _session(entry.base_url, _as_localhost(destination), blocklist=["blocked.example"]) as session:
                await session.navigate(entry.url("/go"))
                assert await session.get_active_page().inner_text("body") == "welcome"
