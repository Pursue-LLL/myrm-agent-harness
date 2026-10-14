"""Stealth Fetcher — Maximum anti-detection based on Scrapling Patchright + BrowserForge

Patchright solves CDP leaks at the source level, BrowserForge generates fine-grained browser fingerprints。
Auto-bypasses Cloudflare Turnstile/Interstitial, hides Canvas fingerprints。

[INPUT]
- .target_guard::FetchTargetGuard (POS: per-fetch SSRF policy for the web_fetch tiers that follow redirects)
- toolkits.browser.pool.proxy::ProxyPool (POS: Manages proxy rotation across Browser Pool and FetchEngine. Supports: 1. Round-robin rotation across multiple proxies 2. Sticky sessions (same proxy for a given session_id with TTL) 3. Concurrency-safe in asyncio single-threaded event loop 4. Environment variable loading (MYRM_PROXIES) 5. Automatic expired session cleanup (via lifecycle tick))

[OUTPUT]
- StealthFetcher: L3 tier: Scrapling Patchright + BrowserForge, maximum ant...

[POS]
Stealth Fetcher — Maximum anti-detection based on Scrapling Patchright + BrowserForge.
Scrapling navigates without a route hook, so redirect hops cannot be vetted in flight; the final URL
is judged before the body is returned and a rejected one raises SSRFSecurityError.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from myrm_agent_harness.core.security.guards.ssrf import SSRFSecurityError
from myrm_agent_harness.core.security.http.secure_fetch import is_ssrf_shield_enabled, parse_allowed_internal_hosts

from .protocols import FetcherType, FetchResult
from .target_guard import FetchTargetGuard

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.browser.pool.proxy import ProxyPool

logger = logging.getLogger(__name__)

_MAX_CONCURRENT_STEALTH = 2
_STEALTH_TIMEOUT_S = 60.0


class StealthFetcher:
    """L3 tier: Scrapling Patchright + BrowserForge, maximum anti-detection"""

    fetcher_type = FetcherType.STEALTH

    def __init__(
        self,
        max_concurrent: int = _MAX_CONCURRENT_STEALTH,
        proxy_pool: ProxyPool | None = None,
        allow_private_networks: bool = False,
    ):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._proxy_pool = proxy_pool
        self._allow_private_networks = allow_private_networks

    async def fetch(self, url: str) -> FetchResult | None:
        from scrapling.fetchers import StealthyFetcher  # type: ignore[import-untyped]

        guard = (
            FetchTargetGuard(
                requested_url=url,
                allow_private_networks=self._allow_private_networks,
                allowed_hosts=parse_allowed_internal_hosts(),
            )
            if is_ssrf_shield_enabled()
            else None
        )
        async with self._semaphore:
            try:
                if guard is not None:
                    await guard.pin(url)
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
                if guard is not None:
                    await guard.pin(response.url or url)
                from ..probe.charset_detector import detect_and_decode_html

                html, _ = detect_and_decode_html(response.body, response.encoding)
                return FetchResult(
                    html=html,
                    url=response.url or url,
                    status_code=response.status,
                    headers=dict(response.headers) if response.headers else {},
                    fetcher_type=FetcherType.STEALTH,
                )
            except SSRFSecurityError:
                raise
            except TimeoutError:
                logger.warning(f"StealthFetcher timeout ({_STEALTH_TIMEOUT_S}s): {url}")
                return None
            except Exception as exc:
                logger.warning(f"StealthFetcher failed: {url} — {exc}")
                return None

    async def shutdown(self) -> None:
        pass
