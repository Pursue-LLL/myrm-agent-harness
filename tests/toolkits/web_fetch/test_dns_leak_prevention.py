"""Unit tests for DNS leak prevention in proxy mode.

Verifies that:
- L3 StealthFetcher passes dns_over_https=True to Scrapling when proxy is active
- L2 BrowserPool adds --dns-over-https-templates flag when proxy_pool is configured
- Neither layer adds DoH when no proxy is configured
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.pool import GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.pool.proxy import ProxyConfig, RoundRobinProxyPool
from myrm_agent_harness.toolkits.web_fetch.fetchers.stealth_fetcher import StealthFetcher

_DOH_FLAG = "--dns-over-https-templates=https://cloudflare-dns.com/dns-query"


class TestStealthFetcherDnsProtection:
    """L3 StealthFetcher DNS leak prevention."""

    @pytest.mark.asyncio
    async def test_dns_over_https_enabled_with_proxy(self) -> None:
        proxy = ProxyConfig(server="http://proxy.example.com:8080")
        pool = RoundRobinProxyPool(proxies=[proxy])
        fetcher = StealthFetcher(proxy_pool=pool)

        mock_response = MagicMock()
        mock_response.body = b"<html></html>"
        mock_response.encoding = "utf-8"
        mock_response.url = "https://example.com"
        mock_response.status = 200
        mock_response.headers = {}

        with patch(
            "scrapling.fetchers.StealthyFetcher.async_fetch",
            new_callable=AsyncMock,
            return_value=mock_response,
        ) as mock_fetch:
            await fetcher.fetch("https://example.com")
            mock_fetch.assert_called_once()
            call_kwargs = mock_fetch.call_args[1]
            assert call_kwargs.get("dns_over_https") is True
            assert "proxy" in call_kwargs

    @pytest.mark.asyncio
    async def test_dns_over_https_not_set_without_proxy(self) -> None:
        fetcher = StealthFetcher(proxy_pool=None)

        mock_response = MagicMock()
        mock_response.body = b"<html></html>"
        mock_response.encoding = "utf-8"
        mock_response.url = "https://example.com"
        mock_response.status = 200
        mock_response.headers = {}

        with patch(
            "scrapling.fetchers.StealthyFetcher.async_fetch",
            new_callable=AsyncMock,
            return_value=mock_response,
        ) as mock_fetch:
            await fetcher.fetch("https://example.com")
            mock_fetch.assert_called_once()
            call_kwargs = mock_fetch.call_args[1]
            assert "dns_over_https" not in call_kwargs
            assert "proxy" not in call_kwargs


class TestBrowserPoolDnsProtection:
    """L2 BrowserPool DNS leak prevention via Chrome launch args."""

    def test_doh_flag_added_with_proxy_pool(self) -> None:
        proxy = ProxyConfig(server="http://proxy.example.com:8080")
        pool = RoundRobinProxyPool(proxies=[proxy])
        browser_pool = GlobalBrowserPool(proxy_pool=pool)

        args = browser_pool._launch_options.get("args", [])
        assert _DOH_FLAG in args
        browser_pool._lifecycle_task = None

    def test_doh_flag_absent_without_proxy_pool(self) -> None:
        browser_pool = GlobalBrowserPool(proxy_pool=None)

        args = browser_pool._launch_options.get("args", [])
        assert _DOH_FLAG not in args
        browser_pool._lifecycle_task = None

    def test_doh_flag_not_duplicated(self) -> None:
        proxy = ProxyConfig(server="http://proxy.example.com:8080")
        pool = RoundRobinProxyPool(proxies=[proxy])
        browser_pool = GlobalBrowserPool(proxy_pool=pool)

        args = browser_pool._launch_options.get("args", [])
        assert args.count(_DOH_FLAG) == 1
        browser_pool._lifecycle_task = None
