"""Unit tests for DNS leak prevention in proxy mode.

Verifies that:
- L3 StealthFetcher passes dns_over_https=True to Scrapling when proxy is active
- L3 StealthFetcher keeps DoH across proxy rotation and concurrent fetches
- L2 BrowserPool adds --dns-over-https-templates flag when proxy_pool is configured
- L2 BrowserPool correctly appends to existing/custom launch_options
- DoH flag propagates through to BrowserLauncher
- Neither layer adds DoH when no proxy is configured
"""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.pool import GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.pool.proxy import ProxyConfig, RoundRobinProxyPool
from myrm_agent_harness.toolkits.web_fetch.fetchers.stealth_fetcher import StealthFetcher

_scrapling_available = importlib.util.find_spec("scrapling") is not None

_DOH_FLAG = "--dns-over-https-templates=https://cloudflare-dns.com/dns-query"


def _make_mock_response(url: str = "https://example.com") -> MagicMock:
    resp = MagicMock()
    resp.body = b"<html></html>"
    resp.encoding = "utf-8"
    resp.url = url
    resp.status = 200
    resp.headers = {}
    return resp


@pytest.mark.skipif(not _scrapling_available, reason="scrapling not installed")
class TestStealthFetcherDnsProtection:
    """L3 StealthFetcher DNS leak prevention."""

    @pytest.mark.asyncio
    async def test_dns_over_https_enabled_with_proxy(self) -> None:
        proxy = ProxyConfig(server="http://proxy.example.com:8080")
        pool = RoundRobinProxyPool(proxies=[proxy])
        fetcher = StealthFetcher(proxy_pool=pool)

        with patch(
            "scrapling.fetchers.StealthyFetcher.async_fetch",
            new_callable=AsyncMock,
            return_value=_make_mock_response(),
        ) as mock_fetch:
            await fetcher.fetch("https://example.com")
            mock_fetch.assert_called_once()
            call_kwargs = mock_fetch.call_args[1]
            assert call_kwargs.get("dns_over_https") is True
            assert "proxy" in call_kwargs

    @pytest.mark.asyncio
    async def test_dns_over_https_not_set_without_proxy(self) -> None:
        fetcher = StealthFetcher(proxy_pool=None)

        with patch(
            "scrapling.fetchers.StealthyFetcher.async_fetch",
            new_callable=AsyncMock,
            return_value=_make_mock_response(),
        ) as mock_fetch:
            await fetcher.fetch("https://example.com")
            mock_fetch.assert_called_once()
            call_kwargs = mock_fetch.call_args[1]
            assert "dns_over_https" not in call_kwargs
            assert "proxy" not in call_kwargs

    @pytest.mark.asyncio
    async def test_doh_persists_across_proxy_rotation(self) -> None:
        """Multiple fetches with round-robin proxy rotation all carry DoH."""
        proxies = [
            ProxyConfig(server="http://proxy1.example.com:8080"),
            ProxyConfig(server="http://proxy2.example.com:9090"),
        ]
        pool = RoundRobinProxyPool(proxies=proxies)
        fetcher = StealthFetcher(proxy_pool=pool)

        with patch(
            "scrapling.fetchers.StealthyFetcher.async_fetch",
            new_callable=AsyncMock,
            return_value=_make_mock_response(),
        ) as mock_fetch:
            await fetcher.fetch("https://site-a.com")
            await fetcher.fetch("https://site-b.com")

            assert mock_fetch.call_count == 2
            for call in mock_fetch.call_args_list:
                assert call[1].get("dns_over_https") is True
                assert "proxy" in call[1]

            # Verify proxy rotation actually happened
            used_proxies = {call[1]["proxy"] for call in mock_fetch.call_args_list}
            assert len(used_proxies) == 2

    @pytest.mark.asyncio
    async def test_doh_under_concurrent_fetches(self) -> None:
        """Concurrent fetches each independently carry DoH."""
        import asyncio

        proxy = ProxyConfig(server="http://proxy.example.com:8080")
        pool = RoundRobinProxyPool(proxies=[proxy])
        fetcher = StealthFetcher(max_concurrent=3, proxy_pool=pool)

        with patch(
            "scrapling.fetchers.StealthyFetcher.async_fetch",
            new_callable=AsyncMock,
            return_value=_make_mock_response(),
        ) as mock_fetch:
            await asyncio.gather(
                fetcher.fetch("https://a.com"),
                fetcher.fetch("https://b.com"),
                fetcher.fetch("https://c.com"),
            )

            assert mock_fetch.call_count == 3
            for call in mock_fetch.call_args_list:
                assert call[1].get("dns_over_https") is True

    @pytest.mark.asyncio
    async def test_doh_param_set_even_when_fetch_fails(self) -> None:
        """DoH is passed to Scrapling even if the fetch raises an exception."""
        proxy = ProxyConfig(server="http://proxy.example.com:8080")
        pool = RoundRobinProxyPool(proxies=[proxy])
        fetcher = StealthFetcher(proxy_pool=pool)

        with patch(
            "scrapling.fetchers.StealthyFetcher.async_fetch",
            new_callable=AsyncMock,
            side_effect=RuntimeError("network error"),
        ) as mock_fetch:
            result = await fetcher.fetch("https://example.com")
            assert result is None
            mock_fetch.assert_called_once()
            call_kwargs = mock_fetch.call_args[1]
            assert call_kwargs.get("dns_over_https") is True


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

    def test_doh_appends_to_existing_custom_args(self) -> None:
        """When user provides custom launch_options with args, DoH flag appends."""
        proxy = ProxyConfig(server="http://proxy.example.com:8080")
        pool = RoundRobinProxyPool(proxies=[proxy])
        custom_opts: dict[str, object] = {"args": ["--disable-gpu", "--no-sandbox"]}
        browser_pool = GlobalBrowserPool(proxy_pool=pool, launch_options=custom_opts)

        args = browser_pool._launch_options.get("args", [])
        assert "--disable-gpu" in args
        assert "--no-sandbox" in args
        assert _DOH_FLAG in args
        browser_pool._lifecycle_task = None

    def test_doh_creates_args_when_custom_opts_lack_args_key(self) -> None:
        """When user provides launch_options without 'args' key, DoH still injected."""
        proxy = ProxyConfig(server="http://proxy.example.com:8080")
        pool = RoundRobinProxyPool(proxies=[proxy])
        custom_opts: dict[str, object] = {"headless": True}
        browser_pool = GlobalBrowserPool(proxy_pool=pool, launch_options=custom_opts)

        args = browser_pool._launch_options.get("args", [])
        assert _DOH_FLAG in args
        assert browser_pool._launch_options.get("headless") is True
        browser_pool._lifecycle_task = None

    def test_doh_flag_propagates_to_launcher(self) -> None:
        """DoH flag in _launch_options is passed through to BrowserLauncher."""
        from myrm_agent_harness.toolkits.browser.pool.config import BrowserEngine

        proxy = ProxyConfig(server="http://proxy.example.com:8080")
        pool = RoundRobinProxyPool(proxies=[proxy])
        browser_pool = GlobalBrowserPool(proxy_pool=pool)

        launcher = browser_pool._get_launcher(BrowserEngine.CHROMIUM_PATCHRIGHT)
        launcher_args = launcher._launch_options.get("args", [])
        assert _DOH_FLAG in launcher_args
        browser_pool._lifecycle_task = None
