"""FetchEngine — Layered fetch engine.

Three-tier architecture:
  L1 HttpFetcher (curl_cffi, ~100 ms)
  L2 BrowserFetcher (Patchright + GlobalBrowserPool, ~1-3 s)
  L3 StealthFetcher (Patchright + BrowserForge, ~3-5 s)

Router: AdaptiveRouter (zero-config, self-learning, self-healing)
Cache: In-memory LRU (default 1 h TTL, 500 entries, 100 MB cap)
  - Request coalescing: concurrent requests for the same URL trigger only one network call (30 s timeout guard)
  - URL normalisation: strips 35+ tracking params for better hit rate
  - HTTP conditional requests: sends ETag / Last-Modified on cache expiry to save bandwidth
  - Stale-While-Revalidate: returns stale cache immediately, refreshes via background priority queue (30 s timeout)
  - Cache warm-up: concurrent pre-warming with exponential back-off retry
Boundary: single-sandbox, single-process semantics; router persistence path is injected config.

[INPUT]
web_fetch.fetchers.http_fetcher::HttpFetcher (POS: L1 HTTP fetcher with optional HTTP/3 retry)
web_fetch.fetchers.browser_fetcher::BrowserFetcher (POS: L2 browser-based fetcher)
web_fetch.fetchers.protocol::FetcherType, FetchResult (POS: Fetcher protocol types)
web_fetch.antibot_detector::is_blocked (POS: Anti-bot detection)
web_fetch.http3_probe::get_http3_retry_metrics (POS: QUIC egress probe and L1 retry metrics)
web_fetch.router.adaptive_router::AdaptiveRouter (POS: Self-learning fetcher router)
web_fetch.youtube_extractor::is_youtube_url, extract_youtube_transcript (POS: YouTube transcript fast-path extractor with oEmbed metadata)
browser.pool.proxy::ProxyPool (POS: Proxy pool for browser fetchers)
browser.domain_filter::DomainAllowlist (POS: Domain allowlist filter)
utils.lru_cache::LRUCache (POS: Generic TTL-based LRU cache)

[OUTPUT]
FetchEngine: Layered fetch engine with adaptive routing, caching, and request coalescing

[POS]
Core fetch engine. Orchestrates L1/L2/L3 fetchers behind an adaptive router with
in-memory caching, request coalescing, and stale-while-revalidate semantics.

"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from langchain_core.documents import Document

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.browser.domain_filter import DomainAllowlist
    from myrm_agent_harness.toolkits.browser.pool.proxy import ProxyPool
    from myrm_agent_harness.toolkits.browser.session_vault import SessionVault

from myrm_agent_harness.utils.lru_cache import LRUCache

from .bilibili_extractor import extract_bilibili_subtitle, is_bilibili_url
from .engine_cache_mixin import FetchEngineCacheMixin
from .engine_escalation_mixin import FetchEngineEscalationMixin
from .engine_fetch_mixin import FetchEngineFetchMixin
from .engine_types import (
    AccessStats,
    BackgroundTask,
    CachedDocument,
    FailedResult,
    SuccessResult,
)
from .fetchers.browser_fetcher import BrowserFetcher
from .fetchers.http_fetcher import HttpFetcher
from .fetchers.stealth_fetcher import StealthFetcher
from .http3_probe import get_http3_retry_metrics
from .pipeline import ContentPipeline
from .router.adaptive_router import AdaptiveRouter, RouterStats
from .youtube_extractor import extract_youtube_transcript, is_youtube_url

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.browser.pool.config import LaunchMode
    from myrm_agent_harness.toolkits.web_fetch.escalation.protocols import FetchEscalationProvider

logger = logging.getLogger(__name__)

__all__ = [
    "AccessStats",
    "BackgroundTask",
    "CachedDocument",
    "FetchEngine",
    "FailedResult",
    "SuccessResult",
]


class FetchEngine(
    FetchEngineEscalationMixin,
    FetchEngineFetchMixin,
    FetchEngineCacheMixin,
):
    """Tiered fetch engine: L1 HTTP -> L2 Browser -> L3 Stealth."""

    _DEFAULT_CRAWL_TIMEOUT: float = 45.0

    def __init__(
        self,
        *,
        use_raw_markdown: bool = False,
        proxy_pool: ProxyPool | None = None,
        session_vault: SessionVault | None = None,
        adaptive_router_rules_file: str | Path | None = None,
        cache_ttl: int = 3600,
        cache_maxsize: int = 500,
        cache_max_bytes: int = 100 * 1024 * 1024,
        stale_while_revalidate: bool = True,
        coalescing_timeout: float = 30.0,
        max_background_tasks: int = 10,
        crawl_timeout: float = _DEFAULT_CRAWL_TIMEOUT,
        domain_allowlist: DomainAllowlist | None = None,
        allow_private_networks: bool = False,
        youtube_languages: list[str] | None = None,
    ):
        self._domain_allowlist = domain_allowlist
        self._allow_private_networks = allow_private_networks
        self._youtube_languages = youtube_languages
        self._http_fetcher = HttpFetcher(proxy_pool=proxy_pool, session_vault=session_vault)
        self._browser_fetcher = BrowserFetcher(
            allow_private_networks=allow_private_networks, session_vault=session_vault
        )
        self._stealth_fetcher = StealthFetcher(proxy_pool=proxy_pool)
        self._pipeline = ContentPipeline(use_raw_markdown=use_raw_markdown)

        self._router = AdaptiveRouter(rules_file=adaptive_router_rules_file)

        def _doc_size(cached: CachedDocument) -> int:
            content_size = len(cached.doc.page_content.encode("utf-8"))
            metadata_size = sum(
                len(str(k).encode("utf-8")) + len(str(v).encode("utf-8")) for k, v in cached.doc.metadata.items()
            )
            return content_size + metadata_size

        self._crawl_cache: LRUCache[CachedDocument] = LRUCache(
            maxsize=cache_maxsize,
            ttl=cache_ttl,
            id="fetch_engine_cache",
            max_bytes=cache_max_bytes,
            size_fn=_doc_size,
        )
        self._fail_cache: LRUCache[bool] = LRUCache(maxsize=200, ttl=300, id="fetch_engine_fail_cache")
        self._pending_requests: dict[str, asyncio.Future[Document | None]] = {}
        self._enable_http_validation = True
        self._stale_while_revalidate = stale_while_revalidate
        self._coalescing_timeout = coalescing_timeout
        self._max_background_tasks = max_background_tasks
        self._crawl_timeout = crawl_timeout
        self._background_queue: asyncio.PriorityQueue[BackgroundTask] = asyncio.PriorityQueue()
        self._background_workers: list[asyncio.Task[None]] = []
        self._url_access_stats: OrderedDict[str, AccessStats] = OrderedDict()
        self._max_access_stats_size = 10_000

        self._bg_revalidations_success = 0
        self._bg_revalidations_failed = 0
        self._bg_revalidations_timeout = 0
        self._bg_revalidations_total_ms = 0.0
        self._bg_revalidations_skipped = 0

        self._workers_started = False

        self._escalation_providers: list[FetchEscalationProvider] | None = None
        self._browser_launch_mode: LaunchMode | None = None

    def set_session_vault(self, session_vault: SessionVault) -> None:
        """Inject SessionVault dynamically (e.g. from server layer)."""
        self._http_fetcher._session_vault = session_vault
        self._browser_fetcher._session_vault = session_vault

    def set_escalation_providers(self, providers: list[FetchEscalationProvider] | None) -> None:
        """Inject optional L4 remote fetch providers (server layer implements httpx vendors)."""
        self._escalation_providers = providers

    def set_browser_launch_mode(self, launch_mode: LaunchMode | None) -> None:
        """Set browser launch mode for L2 fetches (e.g. EXTENSION for logged-in pages)."""
        self._browser_launch_mode = launch_mode
        self._browser_fetcher.set_launch_mode_preference(launch_mode)

    async def crawl(
        self, url: str, *, force_refresh: bool = False, max_chars: int = 0, allow_escalation: bool = True
    ) -> Document | None:
        """Crawl a single URL, return Document or None."""
        self._ensure_workers_started()

        from .url_normalizer import normalize_url

        if not self._allow_private_networks:
            from myrm_agent_harness.core.security.guards.ssrf import validate_url_for_ssrf

            result = validate_url_for_ssrf(url)
            if not result.safe:
                logger.warning(f"URL blocked (SSRF): {url} — {result.error}")
                return None

        if self._domain_allowlist:
            hostname = urlparse(url).hostname or ""
            if not self._domain_allowlist.is_allowed(hostname):
                logger.warning("URL blocked by domain allowlist: %s (host=%s)", url, hostname)
                return None

        cache_key = normalize_url(url)

        if cache_key in self._url_access_stats:
            self._url_access_stats[cache_key].count += 1
        else:
            self._url_access_stats[cache_key] = AccessStats(count=1, last_access=time.time())

        self._url_access_stats.move_to_end(cache_key)

        if len(self._url_access_stats) > self._max_access_stats_size:
            self._url_access_stats.popitem(last=False)

        if not force_refresh and cache_key in self._pending_requests:
            logger.info(f"Request coalescing: waiting for in-flight request: {url}")
            try:
                return await asyncio.wait_for(self._pending_requests[cache_key], timeout=self._coalescing_timeout)
            except TimeoutError:
                logger.warning(f"Request coalescing timeout ({self._coalescing_timeout}s), retrying: {url}")
                self._pending_requests.pop(cache_key, None)

        if force_refresh:
            self._crawl_cache.delete(cache_key)
            self._fail_cache.delete(cache_key)

        cached_item, is_expired = self._crawl_cache.get_with_expiry(cache_key)
        if cached_item is not None and not force_refresh:
            result = self._handle_cache_hit(cached_item, is_expired, url, cache_key)
            if result is not None:
                return result

        if self._fail_cache.contains(cache_key):
            logger.info(f"Fail cache hit (skipping): {url}")
            return None

        future: asyncio.Future[Document | None] = asyncio.Future()
        self._pending_requests[cache_key] = future

        etag = cached_item.etag if cached_item and self._enable_http_validation else None
        last_modified = cached_item.last_modified if cached_item and self._enable_http_validation else None

        try:
            if is_youtube_url(url):
                async with asyncio.timeout(self._crawl_timeout):
                    doc = await extract_youtube_transcript(
                        url,
                        preferred_languages=self._youtube_languages,
                        proxy_pool=self._http_fetcher._proxy_pool,
                    )
                if doc is not None:
                    fetch_result = None
                else:
                    async with asyncio.timeout(self._crawl_timeout):
                        doc, fetch_result = await self._crawl_with_degradation(
                            url,
                            etag=etag,
                            last_modified=last_modified,
                            max_chars=max_chars,
                            allow_escalation=allow_escalation,
                        )
            elif is_bilibili_url(url):
                async with asyncio.timeout(self._crawl_timeout):
                    bilibili_cookies = await self._load_bilibili_cookies()
                    doc = await extract_bilibili_subtitle(
                        url,
                        cookies=bilibili_cookies,
                        proxy_pool=self._http_fetcher._proxy_pool,
                    )
                if doc is not None:
                    fetch_result = None
                else:
                    async with asyncio.timeout(self._crawl_timeout):
                        doc, fetch_result = await self._crawl_with_degradation(
                            url,
                            etag=etag,
                            last_modified=last_modified,
                            max_chars=max_chars,
                            allow_escalation=allow_escalation,
                        )
            else:
                async with asyncio.timeout(self._crawl_timeout):
                    doc, fetch_result = await self._crawl_with_degradation(
                        url,
                        etag=etag,
                        last_modified=last_modified,
                        max_chars=max_chars,
                        allow_escalation=allow_escalation,
                    )

            if fetch_result and fetch_result.status_code == 304 and cached_item:
                logger.info(f"HTTP 304: cache still valid: {url}")
                cached_item.cached_at = time.time()
                self._crawl_cache.set(cache_key, cached_item)
                doc = cached_item.doc
            elif doc is not None:
                new_etag = fetch_result.etag if fetch_result else None
                new_last_modified = fetch_result.last_modified if fetch_result else None
                cached = CachedDocument(doc=doc, etag=new_etag, last_modified=new_last_modified, cached_at=time.time())
                self._crawl_cache.set(cache_key, cached)
            else:
                self._fail_cache.set(cache_key, True)

            if not future.done():
                future.set_result(doc)

            if doc is not None and cache_key in self._url_access_stats:
                self._url_access_stats[cache_key].last_access = time.time()

            return doc
        except Exception as e:
            return await self._handle_fetch_error(url, cache_key, future, e)
        finally:
            self._pending_requests.pop(cache_key, None)

    async def crawl_many(
        self,
        urls: list[str],
        *,
        max_concurrency: int = 10,
        force_refresh: bool = False,
        max_chars: int = 0,
        allow_escalation: bool = True,
    ) -> tuple[SuccessResult, FailedResult]:
        """Batch-crawl multiple URLs in parallel with global concurrency cap."""
        self._ensure_workers_started()

        success_results: SuccessResult = []
        failed_results: FailedResult = []
        sem = asyncio.Semaphore(max_concurrency)

        async def process(url: str) -> None:
            async with sem:
                doc = await self.crawl(
                    url, force_refresh=force_refresh, max_chars=max_chars, allow_escalation=allow_escalation
                )
            if doc is not None:
                success_results.append((url, doc))
            else:
                failed_results.append((url, None))

        await asyncio.gather(*(process(u) for u in urls))
        return success_results, failed_results

    async def prefetch_with_retry(
        self,
        urls: list[str],
        *,
        max_retries: int = 3,
        initial_backoff: float = 1.0,
        max_concurrency: int = 10,
    ) -> tuple[SuccessResult, FailedResult]:
        """Warm up cache (concurrent + auto-retry on failure + exponential backoff)."""
        self._ensure_workers_started()

        success_results: SuccessResult = []
        failed_results: FailedResult = []
        results_lock = asyncio.Lock()
        sem = asyncio.Semaphore(max_concurrency)

        async def retry_one(url: str) -> None:
            async with sem:
                retry_count = 0
                backoff = initial_backoff
                last_error = None

                while retry_count <= max_retries:
                    try:
                        force_refresh = retry_count > 0
                        doc = await self.crawl(url, force_refresh=force_refresh)
                        if doc is not None:
                            async with results_lock:
                                success_results.append((url, doc))
                            return
                        last_error = "Crawl returned None"
                        logger.warning(
                            f"Prefetch failed (attempt {retry_count + 1}/{max_retries + 1}): {url} — {last_error}"
                        )
                    except Exception as e:
                        last_error = str(e)
                        logger.warning(f"Prefetch failed (attempt {retry_count + 1}/{max_retries + 1}): {url} — {e}")

                    retry_count += 1
                    if retry_count <= max_retries:
                        await asyncio.sleep(backoff)
                        backoff *= 2

                logger.error(f"Prefetch exhausted all retries: {url} — {last_error}")
                async with results_lock:
                    failed_results.append((url, None))

        await asyncio.gather(*(retry_one(u) for u in urls))
        return success_results, failed_results

    async def prefetch(self, urls: list[str], *, max_concurrency: int = 5) -> None:
        """Cache warmup: background async load URLs into cache."""
        self._ensure_workers_started()

        sem = asyncio.Semaphore(max_concurrency)

        async def prefetch_one(url: str) -> None:
            async with sem:
                try:
                    await self.crawl(url)
                except Exception:
                    logger.warning(f"Prefetch failed: {url}")

        await asyncio.gather(*(prefetch_one(u) for u in urls), return_exceptions=True)

    async def shutdown(self) -> None:
        if self._background_workers:
            logger.info(f"Stopping {len(self._background_workers)} background workers")
            for _ in self._background_workers:
                self._background_queue.put_nowait(BackgroundTask(priority=0, url="", cache_key="", cached_item=None))
            await asyncio.gather(*self._background_workers, return_exceptions=True)
            self._background_workers.clear()

        self._router.shutdown()
        await self._http_fetcher.shutdown()
        await self._browser_fetcher.shutdown()
        await self._stealth_fetcher.shutdown()

        from .router.site_experience import get_global_site_experience_store

        get_global_site_experience_store().shutdown()

    def get_router_stats(self) -> RouterStats:
        """Get router statistics."""
        return self._router.get_stats()

    def get_cache_metrics(self) -> dict[str, dict[str, int | float]]:
        """Get cache metrics (for monitoring and tuning)."""
        total_bg = self._bg_revalidations_success + self._bg_revalidations_failed + self._bg_revalidations_timeout
        avg_latency = self._bg_revalidations_total_ms / total_bg if total_bg > 0 else 0.0

        return {
            "crawl_cache": self._crawl_cache.get_metrics(),
            "fail_cache": self._fail_cache.get_metrics(),
            "http3_retry": get_http3_retry_metrics(),
            "background_revalidation": {
                "success": self._bg_revalidations_success,
                "failed": self._bg_revalidations_failed,
                "timeout": self._bg_revalidations_timeout,
                "skipped": self._bg_revalidations_skipped,
                "total": total_bg,
                "success_rate": self._bg_revalidations_success / total_bg if total_bg > 0 else 0.0,
                "avg_latency_ms": avg_latency,
                "queue_size": self._background_queue.qsize(),
                "active_workers": len(self._background_workers),
                "max_tasks": self._max_background_tasks,
            },
        }
