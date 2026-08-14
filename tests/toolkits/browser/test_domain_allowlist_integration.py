"""Integration test: domain_allowlist via BrowserSession context_kwargs.

The blocking/allowlist semantics are verified offline — the allow path uses a
reachable public host (www.example.com), the block path uses a local-loopback
address that is never in the allowlist, so the suite does not depend on
reachability of google.com/test.org.
"""

import pytest
from patchright._impl._errors import Error as PatchrightError

from myrm_agent_harness.toolkits.browser import BrowserSession, DomainAllowlist
from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool


@pytest.mark.integration
@pytest.mark.asyncio
async def test_domain_allowlist_blocks_navigation() -> None:
    """Test domain_allowlist blocks navigation to disallowed domains."""
    pool = GlobalBrowserPool(max_browsers=1)
    allowlist = DomainAllowlist.from_strings(["example.com"])
    session = BrowserSession(pool, ContextType.CRAWL, domain_allowlist=allowlist)

    try:
        await session.new_tab()
        # Loopback host is not in the allowlist → route.abort must fire.
        await session.navigate("http://127.0.0.1:1/")
        pytest.fail("Expected navigation to be blocked")
    except PatchrightError as e:
        assert "net::ERR_BLOCKED_BY_CLIENT" in str(e)
    finally:
        await session.close()
        await pool.shutdown()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_domain_allowlist_allows_navigation() -> None:
    """Test domain_allowlist allows navigation to allowed domains."""
    pool = GlobalBrowserPool(max_browsers=1)
    allowlist = DomainAllowlist.from_strings(["*.example.com"])
    session = BrowserSession(pool, ContextType.CRAWL, domain_allowlist=allowlist)

    try:
        await session.new_tab()
        result = await session.navigate("https://www.example.com")
        assert isinstance(result, str)
    finally:
        await session.close()
        await pool.shutdown()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_domain_allowlist_none() -> None:
    """Test domain_allowlist=None allows all domains."""
    pool = GlobalBrowserPool(max_browsers=1)
    session = BrowserSession(pool, ContextType.CRAWL, domain_allowlist=None)

    try:
        await session.new_tab()
        result = await session.navigate("https://www.example.com")
        assert isinstance(result, str)
    finally:
        await session.close()
        await pool.shutdown()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_domain_allowlist_wildcard_patterns() -> None:
    """Test domain_allowlist with wildcard patterns."""
    pool = GlobalBrowserPool(max_browsers=1)
    allowlist = DomainAllowlist.from_strings(["*.example.com", "*.test.org"])
    session = BrowserSession(pool, ContextType.CRAWL, domain_allowlist=allowlist)

    try:
        await session.new_tab()
        result = await session.navigate("https://www.example.com")
        assert isinstance(result, str)

        # Loopback host is not covered by the wildcard patterns → must be blocked.
        await session.navigate("http://127.0.0.1:1/")
        pytest.fail("Expected navigation to be blocked")
    except PatchrightError as e:
        assert "ERR_BLOCKED_BY_CLIENT" in str(e) or "ERR_CONNECTION_CLOSED" in str(e)
    finally:
        await session.close()
        await pool.shutdown()
