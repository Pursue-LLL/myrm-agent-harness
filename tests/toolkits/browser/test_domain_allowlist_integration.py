"""Integration test: domain_allowlist via BrowserSession context_kwargs.

The allow path uses a local-loopback HTTP server with ``allow_private_networks=True``
so SSRF guard does not preempt the domain filter; the block path relies on the
domain filter's ``route.abort("blockedbyclient")`` producing ERR_BLOCKED_BY_CLIENT.
The wildcard allow case uses www.example.com (reachable in CI/test networks).
"""

from __future__ import annotations

import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from patchright._impl._errors import Error as PatchrightError

from myrm_agent_harness.toolkits.browser import BrowserSession, DomainAllowlist
from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool

_PAGE_HTML = b"<!DOCTYPE html><html><body><h1>ok</h1></body></html>"


class _QuietHandler(BaseHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(_PAGE_HTML)))
        self.end_headers()
        self.wfile.write(_PAGE_HTML)


@contextmanager
def _local_server() -> Iterator[str]:
    """Yield a reachable loopback base URL served by a throwaway HTTP server."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}/"
    finally:
        server.shutdown()
        server.server_close()


@asynccontextmanager
async def _session_with_allowlist(
    pool: GlobalBrowserPool,
    allowlist: DomainAllowlist | None,
) -> AsyncIterator[BrowserSession]:
    """BrowserSession with SSRF guard disabled so the domain filter is authoritative."""
    session = BrowserSession(
        pool,
        ContextType.CRAWL,
        domain_allowlist=allowlist,
        allow_private_networks=True,
    )
    try:
        await session.new_tab()
        yield session
    finally:
        await session.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_domain_allowlist_blocks_navigation() -> None:
    """Test domain_allowlist blocks navigation to disallowed domains."""
    pool = GlobalBrowserPool(max_browsers=1)
    try:
        with _local_server() as url:
            async with _session_with_allowlist(
                pool, DomainAllowlist.from_strings(["example.com"])
            ) as session:
                await session.navigate(url)
                pytest.fail("Expected navigation to be blocked")
    except PatchrightError as e:
        assert "net::ERR_BLOCKED_BY_CLIENT" in str(e)
    finally:
        await pool.shutdown()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_domain_allowlist_allows_navigation() -> None:
    """Test domain_allowlist allows navigation to allowed domains."""
    pool = GlobalBrowserPool(max_browsers=1)
    try:
        with _local_server() as url:
            async with _session_with_allowlist(
                pool, DomainAllowlist.from_strings(["127.0.0.1"])
            ) as session:
                result = await session.navigate(url)
                assert isinstance(result, str)
    finally:
        await pool.shutdown()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_domain_allowlist_none() -> None:
    """Test domain_allowlist=None allows all domains."""
    pool = GlobalBrowserPool(max_browsers=1)
    try:
        with _local_server() as url:
            async with _session_with_allowlist(pool, None) as session:
                result = await session.navigate(url)
                assert isinstance(result, str)
    finally:
        await pool.shutdown()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_domain_allowlist_wildcard_patterns() -> None:
    """Test domain_allowlist with wildcard patterns."""
    pool = GlobalBrowserPool(max_browsers=1)
    try:
        with _local_server() as url:
            async with _session_with_allowlist(
                pool,
                DomainAllowlist.from_strings(["*.example.com", "*.test.org"]),
            ) as session:
                # Loopback host is not covered by the wildcard patterns → blocked.
                await session.navigate(url)
                pytest.fail("Expected navigation to be blocked")
    except PatchrightError as e:
        assert "ERR_BLOCKED_BY_CLIENT" in str(e) or "ERR_CONNECTION_CLOSED" in str(e)
    finally:
        await pool.shutdown()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_domain_allowlist_wildcard_allows_subdomain() -> None:
    """Test *.example.com allows www.example.com (reachable public host)."""
    pool = GlobalBrowserPool(max_browsers=1)
    try:
        async with _session_with_allowlist(
            pool,
            DomainAllowlist.from_strings(["*.example.com"]),
        ) as session:
            result = await session.navigate("https://www.example.com")
            assert isinstance(result, str)
    finally:
        await pool.shutdown()