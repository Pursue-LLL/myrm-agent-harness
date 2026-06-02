import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from myrm_agent_harness.toolkits.web_fetch.fetchers.http_fetcher import HttpFetcher
from myrm_agent_harness.toolkits.browser.session_vault import SessionVault, SessionEntry
from myrm_agent_harness.toolkits.browser.backends.file_backend import FileVaultBackend
from pathlib import Path
import http.cookiejar

@pytest.mark.asyncio
async def test_http_fetcher_cookiejar_injection(install_fake_scrapling: AsyncMock):
    """Test that HttpFetcher correctly injects cookies from SessionVault as a CookieJar"""
    
    # Setup mock SessionVault
    mock_vault = MagicMock(spec=SessionVault)
    
    # Create a mock SessionEntry with storage_state containing cookies
    import time
    mock_entry = SessionEntry(
        domain="example.com",
        created_at=time.time(),
        expires_at=time.time() + 3600,
        storage_state={
            "cookies": [
                {
                    "name": "session_id",
                    "value": "12345",
                    "domain": "example.com",
                    "path": "/",
                    "secure": True,
                    "expires": 1700000000,
                    "httpOnly": True
                },
                {
                    "name": "temp_cookie",
                    "value": "abc",
                    "domain": ".example.com",
                    "path": "/api",
                    "secure": False,
                    "expires": -1, # Session cookie
                    "httpOnly": False
                },
                {
                    "name": "zero_expires_cookie",
                    "value": "xyz",
                    "domain": "example.com",
                    "path": "/",
                    "secure": True,
                    "expires": 0, # Should be treated as session cookie
                    "httpOnly": True
                }
            ]
        }
    )
    
    mock_vault.load = AsyncMock(return_value=mock_entry)
    
    # Initialize HttpFetcher with mock vault
    fetcher = HttpFetcher(session_vault=mock_vault)
    
    # Mock AsyncFetcher.get to intercept the call and check kwargs
    mock_get = install_fake_scrapling
    with patch.dict("os.environ", {"MYRM_ENABLE_SSRF_SHIELD": "false", "MYRM_HTTP3_RETRY": "0"}):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.body = b"<html><body><p>" + (b"Test content. " * 20) + b"</p></body></html>"
        mock_response.encoding = "utf-8"
        mock_response.url = "https://example.com/test"
        mock_response.headers = {"content-type": "text/html"}
        mock_get.return_value = mock_response
        
        # Call fetch
        await fetcher.fetch("https://example.com/test")
        
        # Verify SessionVault.load was called with correct domain
        mock_vault.load.assert_called_once_with("example.com")
        
        # Verify AsyncFetcher.get was called
        mock_get.assert_called_once()
        
        # Extract the kwargs passed to AsyncFetcher.get
        _, kwargs = mock_get.call_args
        
        # Verify cookies were injected as a CookieJar
        assert "cookies" in kwargs
        cookie_jar = kwargs["cookies"]
        assert isinstance(cookie_jar, http.cookiejar.CookieJar)
        
        # Extract cookies from CookieJar to verify contents
        cookies = list(cookie_jar)
        assert len(cookies) == 3
        
        # Verify session_id cookie
        session_cookie = next(c for c in cookies if c.name == "session_id")
        assert session_cookie.value == "12345"
        assert session_cookie.domain == "example.com"
        assert session_cookie.path == "/"
        assert session_cookie.secure is True
        assert session_cookie.expires == 1700000000
        
        # Verify temp_cookie (expires: -1 should be mapped to None)
        temp_cookie = next(c for c in cookies if c.name == "temp_cookie")
        assert temp_cookie.value == "abc"
        assert temp_cookie.domain == ".example.com"
        assert temp_cookie.path == "/api"
        assert temp_cookie.secure is False
        assert temp_cookie.expires is None
        
        # Verify zero_expires_cookie (expires: 0 should be mapped to None)
        zero_cookie = next(c for c in cookies if c.name == "zero_expires_cookie")
        assert zero_cookie.value == "xyz"
        assert zero_cookie.domain == "example.com"
        assert zero_cookie.path == "/"
        assert zero_cookie.secure is True
        assert zero_cookie.expires is None

@pytest.mark.asyncio
async def test_browser_fetcher_storage_state_injection():
    """Test that BrowserFetcher correctly passes storage_state to the browser pool"""
    from myrm_agent_harness.toolkits.web_fetch.fetchers.browser_fetcher import BrowserFetcher
    from myrm_agent_harness.toolkits.browser.pool import GlobalBrowserPool
    from myrm_agent_harness.toolkits.browser.pool import ContextType
    
    # Setup mock SessionVault
    mock_vault = MagicMock(spec=SessionVault)
    
    # Create a mock SessionEntry with storage_state
    mock_storage_state = {"cookies": [{"name": "test", "value": "123", "domain": "example.com", "path": "/"}]}
    import time
    mock_entry = SessionEntry(
        domain="example.com",
        created_at=time.time(),
        expires_at=time.time() + 3600,
        storage_state=mock_storage_state
    )
    
    mock_vault.load = AsyncMock(return_value=mock_entry)
    
    # Setup mock BrowserPool
    mock_pool = MagicMock(spec=GlobalBrowserPool)
    mock_page = MagicMock()
    mock_page.content = AsyncMock(return_value="<html><body>Test</body></html>")
    mock_page.url = "https://example.com/test"
    
    # The acquire_page method returns a tuple (page, context_key)
    mock_pool.acquire_page = AsyncMock(return_value=(mock_page, "crawl_example.com"))
    mock_pool.release_page = AsyncMock()
    
    # Initialize BrowserFetcher with mock vault and pool
    fetcher = BrowserFetcher(browser_pool=mock_pool, session_vault=mock_vault)
    
    # Call fetch
    await fetcher.fetch("https://example.com/test")
    
    # Verify SessionVault.load was called with correct domain
    mock_vault.load.assert_called_once_with("example.com")
    
    # Verify acquire_page was called with correct context_kwargs containing storage_state
    mock_pool.acquire_page.assert_called_once_with(
        ContextType.CRAWL,
        context_key="crawl_example.com",
        context_kwargs={"storage_state": mock_storage_state}
    )

"""Fetchers 核心功能测试"""

import pytest

from myrm_agent_harness.toolkits.web_fetch.fetchers.browser_fetcher import BrowserFetcher
from myrm_agent_harness.toolkits.web_fetch.fetchers.http_fetcher import HttpFetcher
from myrm_agent_harness.toolkits.web_fetch.fetchers.protocols import FetcherType, FetchResult
from myrm_agent_harness.toolkits.web_fetch.fetchers.stealth_fetcher import StealthFetcher


@pytest.mark.asyncio
async def test_http_fetcher_initialization():
    """测试 HttpFetcher 初始化参数"""
    from pathlib import Path

    from myrm_agent_harness.toolkits.browser.backends.file_backend import FileVaultBackend
    from myrm_agent_harness.toolkits.browser.pool.proxy import ProxyConfig, RoundRobinProxyPool
    from myrm_agent_harness.toolkits.browser.session_vault import SessionVault

    pool = RoundRobinProxyPool([ProxyConfig(server="http://proxy.com:8080")])
    vault = SessionVault(FileVaultBackend(Path("/tmp/test")), b"0123456789abcdef0123456789abcdef")
    fetcher = HttpFetcher(max_concurrent=10, timeout=15, proxy_pool=pool, session_vault=vault)

    assert fetcher.fetcher_type == FetcherType.HTTP
    assert fetcher._timeout == 15
    assert fetcher._proxy_pool is pool
    assert fetcher._session_vault is vault


@pytest.mark.asyncio
async def test_http_fetcher_shutdown():
    """测试 HttpFetcher 关闭"""
    fetcher = HttpFetcher()

    await fetcher.shutdown()


@pytest.mark.asyncio
async def test_browser_fetcher_initialization():
    """测试 BrowserFetcher 初始化"""
    from pathlib import Path

    from myrm_agent_harness.toolkits.browser.backends.file_backend import FileVaultBackend
    from myrm_agent_harness.toolkits.browser.session_vault import SessionVault

    vault = SessionVault(FileVaultBackend(Path("/tmp/test")), b"0123456789abcdef0123456789abcdef")
    fetcher = BrowserFetcher(session_vault=vault)

    assert fetcher.fetcher_type == FetcherType.BROWSER
    assert fetcher._session_vault is vault


@pytest.mark.asyncio
async def test_browser_fetcher_shutdown():
    """测试 BrowserFetcher 关闭"""
    fetcher = BrowserFetcher()

    await fetcher.shutdown()


@pytest.mark.asyncio
async def test_stealth_fetcher_initialization():
    """测试 StealthFetcher 初始化"""
    from myrm_agent_harness.toolkits.browser.pool.proxy import ProxyConfig, RoundRobinProxyPool

    pool = RoundRobinProxyPool([ProxyConfig(server="http://proxy.com:8080")])
    fetcher = StealthFetcher(proxy_pool=pool)

    assert fetcher.fetcher_type == FetcherType.STEALTH


@pytest.mark.asyncio
async def test_stealth_fetcher_shutdown():
    """测试 StealthFetcher 关闭"""
    fetcher = StealthFetcher()

    await fetcher.shutdown()


def test_fetch_result_has_content():
    """测试 FetchResult.has_content 属性"""
    long_html = "<html><body><p>" + ("This is a test paragraph with content. " * 20) + "</p></body></html>"
    result_with_content = FetchResult(html=long_html, url="https://example.com", status_code=200)

    result_no_content = FetchResult(html="<html></html>", url="https://example.com", status_code=200)

    assert result_with_content.has_content is True
    assert result_no_content.has_content is False


def test_fetch_result_etag():
    """测试 FetchResult.etag 属性"""
    result = FetchResult(html="<html></html>", url="https://example.com", status_code=200, headers={"etag": "123456"})

    assert result.etag == "123456"


def test_fetch_result_last_modified():
    """测试 FetchResult.last_modified 属性"""
    result = FetchResult(
        html="<html></html>",
        url="https://example.com",
        status_code=200,
        headers={"last-modified": "Mon, 23 Mar 2026 00:00:00 GMT"},
    )

    assert result.last_modified == "Mon, 23 Mar 2026 00:00:00 GMT"


def test_fetch_result_raw_body_default():
    """FetchResult.raw_body defaults to None"""
    result = FetchResult(html="<html></html>", url="https://example.com")
    assert result.raw_body is None


def test_fetch_result_raw_body_set():
    """FetchResult.raw_body can hold binary data"""
    pdf_bytes = b"%PDF-1.4 fake content"
    result = FetchResult(html="", url="https://example.com/doc.pdf", raw_body=pdf_bytes)
    assert result.raw_body == pdf_bytes
    assert result.html == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
