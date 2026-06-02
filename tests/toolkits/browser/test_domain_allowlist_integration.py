"""Integration test: domain_allowlist via BrowserSession context_kwargs."""

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
        await session.navigate("https://www.google.com")
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


@pytest.mark.skip(reason="Network unavailable in test environment")
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

        result = await session.navigate("https://test.org")
        assert isinstance(result, str)

        await session.navigate("https://www.google.com")
        pytest.fail("Expected navigation to be blocked")
    except PatchrightError as e:
        assert "ERR_BLOCKED_BY_CLIENT" in str(e) or "ERR_CONNECTION_CLOSED" in str(e)
    finally:
        await session.close()
        await pool.shutdown()
