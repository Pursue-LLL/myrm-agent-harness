"""Real-Chromium proof that the local-mode private-origin policy holds under another spelling of the host.

A local session may only load a private origin the agent was sent to on purpose. A page, redirect or
script that points the tab at a hostname whose DNS answer is loopback or link-local reaches the same
origin, so the hostname is judged by what it resolves to. The hostnames below are fake: the process's
resolver answers them from a table (modelling an attacker-controlled A record) and Chromium is told
to map them onto the loopback test servers, so the request really can land when the policy lets it.
Explicitly navigated origins stay reachable, cloud metadata never is, and ranges a user's own proxy
or VPN may hand out for public names (RFC 1918, 198.18/15) are not judged. Run with:
`pytest -m integration tests/toolkits/browser/test_hostname_resolution_policy_integration.py`.
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

import pytest

from myrm_agent_harness.toolkits.browser import BrowserSession
from myrm_agent_harness.toolkits.browser.navigation.ssrf_guard import BrowserNavigationBlockedError
from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.pool.browser_pool import _DEFAULT_LAUNCH_OPTIONS
from tests.toolkits.browser._browser_available import chromium_available
from tests.toolkits.browser._redirect_servers import Reply, Site, page, redirect, serve

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.skipif(not chromium_available(), reason="Chromium not available"),
]

_SECRET = "LOCAL-ONLY-SECRET"
_DNS_ANSWERS = {
    "rebind.test": "127.0.0.1",
    "meta.test": "169.254.169.254",
    "fakeip.test": "198.18.1.234",
    "corp.test": "10.0.0.5",
}
_UNRESOLVABLE = "flaky.test"
_CHROMIUM_MAPPED = (*_DNS_ANSWERS, _UNRESOLVABLE)


type _AddrInfo = Sequence[
    tuple[
        socket.AddressFamily,
        socket.SocketKind,
        int,
        str,
        tuple[str, int] | tuple[str, int, int, int] | tuple[int, bytes],
    ]
]


@pytest.fixture(autouse=True)
def _process_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Answer the fake hostnames from a table; every other lookup stays real."""
    real = socket.getaddrinfo

    def answer(
        host: str | bytes | None,
        port: str | bytes | int | None,
        family: int = 0,
        kind: int = 0,
        proto: int = 0,
        flags: int = 0,
    ) -> _AddrInfo:
        name = host.decode() if isinstance(host, bytes) else host
        if name == _UNRESOLVABLE:
            raise socket.gaierror(socket.EAI_NONAME, "unresolvable in the test")
        if name in _DNS_ANSWERS:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (_DNS_ANSWERS[name], 0))]
        return real(host, port, family, kind, proto, flags)

    monkeypatch.setattr(socket, "getaddrinfo", answer)


@asynccontextmanager
async def _local_session() -> AsyncIterator[BrowserSession]:
    default_args = _DEFAULT_LAUNCH_OPTIONS["args"]
    assert isinstance(default_args, list)
    mapping = ", ".join(f"MAP {host} 127.0.0.1" for host in _CHROMIUM_MAPPED)
    launch_options = {**_DEFAULT_LAUNCH_OPTIONS, "args": [*default_args, f"--host-resolver-rules={mapping}"]}
    pool = GlobalBrowserPool(max_browsers=1, launch_options=launch_options)
    session = BrowserSession(pool, ContextType.AGENT, allow_private_networks=True)
    try:
        await session.new_tab()
        yield session
    finally:
        await session.close()
        await pool.shutdown()


def _as(host: str, site: Site, path: str = "/") -> str:
    """``site`` (a loopback server) under the fake hostname ``host``."""
    return f"http://{host}:{site.base_url.rsplit(':', 1)[1]}{path}"


def _script_page(script: str) -> Reply:
    return Reply(body=f"<!DOCTYPE html><html><head></head><body>start<script>{script}</script></body></html>".encode())


async def test_redirect_to_a_hostname_that_resolves_to_loopback_is_blocked_and_the_tab_is_reset() -> None:
    with (
        serve({"/secret": page(_SECRET)}) as elsewhere,
        serve({"/go": redirect(_as("rebind.test", elsewhere, "/secret"))}) as site,
    ):
        async with _local_session() as session:
            with pytest.raises(BrowserNavigationBlockedError, match=r"resolves to 127\.0\.0\.1"):
                await session.navigate(site.url("/go"))
            tab = session.get_active_page()
            assert tab.url == "about:blank"
            assert _SECRET not in await tab.content()


async def _wait_for_blank_tab(session: BrowserSession, *, timeout_s: float = 5.0) -> None:
    """Poll the tab URL: a navigation that is aborted and replaced makes ``wait_for_url`` raise."""
    async with asyncio.timeout(timeout_s):
        while session.get_active_page().url != "about:blank":
            await asyncio.sleep(0.05)


async def test_script_navigation_to_a_hostname_that_resolves_to_loopback_is_blocked_before_any_request() -> None:
    """Immediately (inside the navigation) and later (after it settled, where only the context filter acts)."""
    with serve({"/secret": page(_SECRET)}) as elsewhere:
        target = _as("rebind.test", elsewhere, "/secret")
        immediate = _script_page(f"location = '{target}'")
        delayed = _script_page(f"setTimeout(() => {{ location = '{target}'; }}, 300)")
        with serve({"/immediate": immediate, "/delayed": delayed}) as site:
            async with _local_session() as session:
                with pytest.raises(BrowserNavigationBlockedError):
                    await session.navigate(site.url("/immediate"))

                await session.navigate(site.url("/delayed"))
                await _wait_for_blank_tab(session)
        assert elsewhere.hits == []


async def test_cloud_metadata_behind_a_hostname_is_blocked_even_when_navigated_to_explicitly() -> None:
    with serve({"/creds": page(_SECRET)}) as service:
        async with _local_session() as session:
            with pytest.raises(BrowserNavigationBlockedError, match="metadata"):
                await session.navigate(_as("meta.test", service, "/creds"))
        assert service.hits == []


async def test_explicit_navigation_to_a_hostname_that_resolves_to_loopback_still_works() -> None:
    with serve({"/home": page("welcome")}) as service:
        async with _local_session() as session:
            await session.navigate(_as("rebind.test", service, "/home"))
            assert await session.get_active_page().inner_text("body") == "welcome"


@pytest.mark.parametrize("host", ["fakeip.test", "corp.test", _UNRESOLVABLE])
async def test_hostnames_a_users_proxy_or_network_may_hand_out_are_not_judged(host: str) -> None:
    with (
        serve({"/home": page("welcome")}) as destination,
        serve({"/go": redirect(_as(host, destination, "/home"))}) as site,
    ):
        async with _local_session() as session:
            await session.navigate(site.url("/go"))
            assert await session.get_active_page().inner_text("body") == "welcome"
