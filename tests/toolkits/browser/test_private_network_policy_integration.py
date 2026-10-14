"""Real-Chromium proof that ``allow_private_networks`` reaches the context-level HTTP filter.

A context with a domain list or resource blocking installs a route filter whose hop
revalidation blocks loopback and private targets unless told otherwise. The session flag has
to travel through ``ContextFactory`` into that filter, or a session that opted into local
access would be blocked as soon as any list or resource blocking is attached. Every scenario
counts requests that reached the server, so a pass cannot be an artifact of the setup. Run with:
`pytest -m integration tests/toolkits/browser/test_private_network_policy_integration.py`.
"""

from __future__ import annotations

import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from patchright.async_api import Error as BrowserDriverError

from myrm_agent_harness.toolkits.browser import BrowserSession, DomainAllowlist
from myrm_agent_harness.toolkits.browser.exceptions import BrowserNavigationError
from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from tests.toolkits.browser._browser_available import chromium_available

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.skipif(not chromium_available(), reason="Chromium not available"),
]

_PAGE_HTML = b"<!DOCTYPE html><html><body><h1>ok</h1></body></html>"
_OTHER_HOST = DomainAllowlist.from_strings(["blocked.example"])


@contextmanager
def _local_server() -> Iterator[tuple[str, list[str]]]:
    """Yield a loopback base URL and the list of request paths the server received."""
    hits: list[str] = []

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            pass

        def do_GET(self) -> None:
            hits.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(_PAGE_HTML)))
            self.end_headers()
            self.wfile.write(_PAGE_HTML)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}/", hits
    finally:
        server.shutdown()
        server.server_close()


@asynccontextmanager
async def _pool() -> AsyncIterator[GlobalBrowserPool]:
    pool = GlobalBrowserPool(max_browsers=1)
    try:
        yield pool
    finally:
        await pool.shutdown()


@asynccontextmanager
async def _session(
    pool: GlobalBrowserPool, blocklist: DomainAllowlist | None, *, allow_private_networks: bool
) -> AsyncIterator[BrowserSession]:
    session = BrowserSession(
        pool, ContextType.CRAWL, domain_blocklist=blocklist, allow_private_networks=allow_private_networks
    )
    try:
        await session.new_tab()
        yield session
    finally:
        await session.close()


async def test_flag_survives_a_domain_blocklist() -> None:
    async with _pool() as pool, _session(pool, _OTHER_HOST, allow_private_networks=True) as session:
        with _local_server() as (url, hits):
            assert isinstance(await session.navigate(url), str)
            assert "/" in hits


async def test_flag_survives_default_resource_blocking() -> None:
    """No list at all: the pool's default resource blocking is the only reason a filter exists."""
    async with _pool() as pool, _session(pool, None, allow_private_networks=True) as session:
        with _local_server() as (url, hits):
            assert isinstance(await session.navigate(url), str)
            assert "/" in hits


async def _goto_through_filter(context_kwargs: dict[str, object]) -> tuple[str, list[str]]:
    """Navigate a fresh pooled context straight to a loopback server.

    Returns the driver error text ("" on success) and the request paths the server received.
    """
    async with _pool() as pool:
        page, context_key = await pool.acquire_page(ContextType.CRAWL, context_kwargs=context_kwargs)
        try:
            with _local_server() as (url, hits):
                try:
                    await page.goto(url)
                except BrowserDriverError as exc:
                    return str(exc), hits
                return "", hits
        finally:
            await pool.release_page(page, context_key)


async def test_blocklist_stays_authoritative_when_private_networks_are_allowed() -> None:
    error, hits = await _goto_through_filter(
        {"allow_private_networks": True, "domain_blocklist": DomainAllowlist.from_strings(["127.0.0.1"])}
    )
    assert "net::ERR_BLOCKED_BY_CLIENT" in error
    assert hits == []


async def test_filter_blocks_private_targets_without_the_flag() -> None:
    """Control: a context created without the flag keeps blocking loopback at the filter."""
    error, hits = await _goto_through_filter({"domain_blocklist": _OTHER_HOST})
    assert "net::ERR_" in error
    assert hits == []


async def test_session_without_the_flag_cannot_reach_loopback() -> None:
    """Control for the whole session path (cloud default): navigation guard and context filter both block."""
    async with _pool() as pool, _session(pool, None, allow_private_networks=False) as session:
        with _local_server() as (url, hits), pytest.raises(BrowserNavigationError):
            await session.navigate(url)
        assert hits == []
