"""Stealth Fetcher — Maximum anti-detection based on Scrapling Patchright + BrowserForge

Patchright solves CDP leaks at the source level, BrowserForge generates fine-grained browser fingerprints。
Auto-bypasses Cloudflare Turnstile/Interstitial, hides Canvas fingerprints。

[INPUT]
- toolkits.browser.pool.proxy::ProxyPool (POS: Manages proxy rotation across Browser Pool and CrawlEngine. Supports: 1. Round-robin rotation across multiple proxies 2. Sticky sessions (same proxy for a given session_id with TTL) 3. Concurrency-safe in asyncio single-threaded event loop 4. Environment variable loading (MYRM_PROXIES) 5. Automatic expired session cleanup (via lifecycle tick))

[OUTPUT]
- StealthFetcher: L3 tier: Scrapling Patchright + BrowserForge, maximum ant...

[POS]
Stealth Fetcher — Maximum anti-detection based on Scrapling Patchright + BrowserForge
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from .protocols import FetcherType, FetchResult

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.browser.pool.proxy import ProxyPool

logger = logging.getLogger(__name__)

_MAX_CONCURRENT_STEALTH = 2
_STEALTH_TIMEOUT_S = 60.0


class StealthFetcher:
    """L3 tier: Scrapling Patchright + BrowserForge, maximum anti-detection"""

    fetcher_type = FetcherType.STEALTH

    def __init__(self, max_concurrent: int = _MAX_CONCURRENT_STEALTH, proxy_pool: ProxyPool | None = None):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._proxy_pool = proxy_pool

    async def fetch(self, url: str) -> FetchResult | None:
        from scrapling.fetchers import StealthyFetcher  # type: ignore[import-untyped]

        async with self._semaphore:
            try:
                kwargs: dict[str, object] = {
                    "headless": True,
                    "network_idle": True,
                    "block_webrtc": True,
                    "hide_canvas": True,
                    "disable_resources": True,
                    "block_ads": True,
                    "solve_cloudflare": True,
                }
                if self._proxy_pool:
                    kwargs["proxy"] = self._proxy_pool.get_next().to_url()
                    kwargs["dns_over_https"] = True
                async with asyncio.timeout(_STEALTH_TIMEOUT_S):
                    response = await StealthyFetcher.async_fetch(url, **kwargs)
                html = response.body.decode(response.encoding or "utf-8", errors="replace")
                return FetchResult(
                    html=html,
                    url=response.url or url,
                    status_code=response.status,
                    headers=dict(response.headers) if response.headers else {},
                    fetcher_type=FetcherType.STEALTH,
                )
            except TimeoutError:
                logger.warning(f"StealthFetcher timeout ({_STEALTH_TIMEOUT_S}s): {url}")
                return None
            except Exception as exc:
                logger.warning(f"StealthFetcher failed: {url} — {exc}")
                return None

    async def shutdown(self) -> None:
        pass
