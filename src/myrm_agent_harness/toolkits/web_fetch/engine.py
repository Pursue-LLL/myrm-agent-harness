"""CrawlEngine — Layered crawl engine.

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
CrawlEngine: Layered crawl engine with adaptive routing, caching, and request coalescing

[POS]
Core crawl engine. Orchestrates L1/L2/L3 fetchers behind an adaptive router with
in-memory caching, request coalescing, and stale-while-revalidate semantics.

"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from langchain_core.documents import Document

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.browser.domain_filter import DomainAllowlist
    from myrm_agent_harness.toolkits.browser.pool.proxy import ProxyPool
    from myrm_agent_harness.toolkits.browser.session_vault import SessionVault

from myrm_agent_harness.utils.lru_cache import LRUCache

from .antibot_detector import is_blocked as detect_antibot
from .fetchers.browser_fetcher import BrowserFetcher
from .fetchers.http_fetcher import HttpFetcher
from .fetchers.protocols import FetcherType, FetchResult
from .fetchers.stealth_fetcher import StealthFetcher
from .http3_probe import get_http3_retry_metrics
from .pipeline import ContentPipeline
from .router.adaptive_router import AdaptiveRouter, RouterStats
from .youtube_extractor import extract_youtube_transcript, is_youtube_url

logger = logging.getLogger(__name__)

try:
    import psutil

    _PSUTIL_AVAILABLE = True
except (ImportError, TypeError):
    _PSUTIL_AVAILABLE = False
    logger.warning("psutil not available, resource tracking disabled")

SuccessResult = list[tuple[str, Document]]
FailedResult = list[tuple[str, None]]

# 403 anti-crawl / 429 rate-limit can be bypassed via browser layer, allow degradation
_DEGRADABLE_4XX = frozenset({403, 429})


@dataclass(slots=True)
class CachedDocument:
    """Cached Document with HTTP validation metadata."""

    doc: Document
    etag: str | None = None
    last_modified: str | None = None
    cached_at: float = 0.0


@dataclass(slots=True)
class AccessStats:
    """URL access statistics (for priority calculation)."""

    count: int
    last_access: float


@dataclass(slots=True, order=True)
class BackgroundTask:
    """Background refresh task (supports priority sorting)."""

    priority: int
    url: str = ""
    cache_key: str = ""
    cached_item: CachedDocument | None = None


class CrawlEngine:
    """Tiered crawl engine: L1 HTTP -> L2 Browser -> L3 Stealth.

    Router: AdaptiveRouter (zero-config, self-learning, self-healing)
    Browser: GlobalBrowserPool (resource reuse)
    Cache: In-memory LRU (default 1h TTL, 500 entries, memory cap, request coalescing, SWR, HTTP conditional requests)
    Security: SSRF protection + optional domain allowlist (DomainAllowlist injection)
    Boundary: single-process semantics, no cross-process/cross-tenant consistency

    Core optimizations:
    - Request coalescing: 30s timeout protection, avoids slow-request blocking
    - Stale-While-Revalidate: priority queue + worker pool (30s timeout, time-decayed priority)
    - HTTP conditional requests: ETag/Last-Modified validation, 304 cache reuse
    - URL normalization: removes 35+ tracking parameters, improves hit rate
    - Cache warmup: concurrent warmup + exponential backoff retry (9.4x speedup)
    - Cache metrics: hits/stale_hits/misses + background task success rate/latency/timeout/skip/queue/worker count
    """

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
            """Estimate CachedDocument byte size (page_content + metadata)."""
            content_size = len(cached.doc.page_content.encode("utf-8"))
            metadata_size = sum(
                len(str(k).encode("utf-8")) + len(str(v).encode("utf-8")) for k, v in cached.doc.metadata.items()
            )
            return content_size + metadata_size

        self._crawl_cache: LRUCache[CachedDocument] = LRUCache(
            maxsize=cache_maxsize,
            ttl=cache_ttl,
            id="crawl_engine_cache",
            max_bytes=cache_max_bytes,
            size_fn=_doc_size,
        )
        self._fail_cache: LRUCache[bool] = LRUCache(maxsize=200, ttl=300, id="crawl_engine_fail_cache")
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

        # Background revalidation metrics
        self._bg_revalidations_success = 0
        self._bg_revalidations_failed = 0
        self._bg_revalidations_timeout = 0
        self._bg_revalidations_total_ms = 0.0
        self._bg_revalidations_skipped = 0

        # Lazy initialization flag
        self._workers_started = False

    def set_session_vault(self, session_vault: SessionVault) -> None:
        """Inject SessionVault dynamically (e.g. from server layer)."""
        self._http_fetcher._session_vault = session_vault
        self._browser_fetcher._session_vault = session_vault

    def _ensure_workers_started(self) -> None:
        """Lazy start background workers (idempotent, thread-safe)."""
        if self._workers_started:
            return

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return

        if not self._workers_started:
            for _ in range(self._max_background_tasks):
                worker = asyncio.create_task(self._background_worker())
                self._background_workers.append(worker)
            self._workers_started = True

    def _calculate_priority(self, cache_key: str) -> int:
        """Compute background task priority (time decay + access frequency).

        Returns:
            Negative number (lower = higher priority)
        """
        stats = self._url_access_stats.get(cache_key)
        if not stats:
            return 0

        # Time decay: 50% decay per 24h
        age_hours = (time.time() - stats.last_access) / 3600
        decay_factor = 0.5 ** (age_hours / 24)

        # Effective access count = raw count * decay factor
        effective_count = stats.count * decay_factor

        return -round(effective_count)

    async def _try_fetch_and_process(
        self,
        url: str,
        fetcher_type: FetcherType,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
        max_chars: int = 0,
    ) -> tuple[Document | None, bool, float, float | None, float | None, FetchResult | None]:
        """Fetch with a specified fetcher and process through the pipeline.

        Returns:
            (doc, degradable, latency_ms, cpu_percent, memory_mb, fetch_result)
        """
        fetcher_map = {
            FetcherType.HTTP: self._http_fetcher,
            FetcherType.BROWSER: self._browser_fetcher,
            FetcherType.STEALTH: self._stealth_fetcher,
        }
        fetcher = fetcher_map[fetcher_type]

        if _PSUTIL_AVAILABLE:
            process = psutil.Process()
            cpu_times_start = process.cpu_times()
            mem_start_mb = process.memory_info().rss / 1024 / 1024
        else:
            cpu_times_start = None
            mem_start_mb = None

        start_time = time.time()
        if fetcher_type == FetcherType.HTTP and (etag or last_modified):
            fetch_result: FetchResult | None = await fetcher.fetch(url, etag=etag, last_modified=last_modified)
        else:
            fetch_result: FetchResult | None = await fetcher.fetch(url)
        elapsed = time.time() - start_time
        latency_ms = elapsed * 1000.0

        if _PSUTIL_AVAILABLE and cpu_times_start is not None and mem_start_mb is not None:
            cpu_times_end = process.cpu_times()
            cpu_used = (cpu_times_end.user - cpu_times_start.user) + (cpu_times_end.system - cpu_times_start.system)
            cpu_percent = (cpu_used / elapsed * 100.0) if elapsed > 0 else 0.0
            mem_delta_mb = (process.memory_info().rss / 1024 / 1024) - mem_start_mb
            cpu_percent = max(0.0, cpu_percent)
            memory_mb = max(0.0, mem_delta_mb)
        else:
            cpu_percent = None
            memory_mb = None

        if fetch_result is None:
            return None, True, latency_ms, cpu_percent, memory_mb, None

        if fetch_result.status_code == 304:
            logger.info(f"HTTP 304 Not Modified: {url}")
            return None, False, latency_ms, cpu_percent, memory_mb, fetch_result

        if (
            fetcher_type == FetcherType.HTTP
            and 400 <= fetch_result.status_code < 500
            and fetch_result.status_code not in _DEGRADABLE_4XX
        ):
            logger.warning(f"HTTP {fetch_result.status_code} not degradable, abort: {url}")
            return None, False, latency_ms, cpu_percent, memory_mb, None

        if fetcher_type == FetcherType.HTTP and not fetch_result.has_content:
            logger.warning(f"L1 HTTP returned empty shell, will degrade: {url}")
            return None, True, latency_ms, cpu_percent, memory_mb, None

        if fetch_result.raw_body is not None:
            from .binary_router import route_binary_content

            doc = await route_binary_content(fetch_result.raw_body, fetch_result.headers, url)
            return doc, False, latency_ms, cpu_percent, memory_mb, fetch_result

        blocked, reason = detect_antibot(fetch_result.status_code, fetch_result.html)
        if blocked:
            logger.warning(f"Anti-bot detected ({reason}): {url}")
            return None, True, latency_ms, cpu_percent, memory_mb, None

        doc = self._pipeline.process(fetch_result, max_chars=max_chars)

        if doc and doc.metadata.get("was_truncated"):
            try:
                from myrm_agent_harness.utils.event_utils import dispatch_custom_event

                await dispatch_custom_event(
                    "agent_status",
                    {
                        "step_key": "ux_warning_truncated",
                        "status": "warning",
                        "items": [
                            {
                                "text": f"Warning: Content from {url} was intelligently truncated to fit within context limits."
                            }
                        ],
                        "metadata": {"type": "html_truncation", "url": url},
                    },
                )
            except Exception as e:
                logger.warning(f"Failed to dispatch truncation event: {e}")

        return doc, True, latency_ms, cpu_percent, memory_mb, fetch_result

    async def _try_and_report(
        self,
        url: str,
        fetcher_type: FetcherType,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
        max_chars: int = 0,
    ) -> tuple[Document | None, bool, float, float | None, float | None, FetchResult | None]:
        """Attempt fetch and auto-report result to router."""
        doc, degradable, latency, cpu, mem, fetch_result = await self._try_fetch_and_process(
            url, fetcher_type, etag=etag, last_modified=last_modified, max_chars=max_chars
        )
        self._report_feedback(url, fetcher_type, success=(doc is not None), latency_ms=latency, cpu=cpu, memory=mem)
        return doc, degradable, latency, cpu, mem, fetch_result

    async def _crawl_with_degradation(
        self, url: str, *, etag: str | None = None, last_modified: str | None = None, max_chars: int = 0
    ) -> tuple[Document | None, FetchResult | None]:
        """Smart degradation: select starting tier from routing result, degrade tier by tier.

        Returns:
            (doc, fetch_result): fetch_result used to extract ETag/Last-Modified
        """
        decision = self._router.select(url)
        start_type = decision.fetcher_type

        if start_type == FetcherType.STEALTH:
            doc, _, _, _, _, result = await self._try_and_report(url, FetcherType.STEALTH, max_chars=max_chars)
            if doc:
                return doc, result

            logger.warning(f"Stealth failed, trying browser: {url}")
            doc, _, _, _, _, result = await self._try_and_report(url, FetcherType.BROWSER, max_chars=max_chars)
            return doc, result

        if start_type == FetcherType.BROWSER:
            doc, _, _, _, _, result = await self._try_and_report(url, FetcherType.BROWSER, max_chars=max_chars)
            if doc:
                return doc, result

            logger.warning(f"Browser failed, trying stealth: {url}")
            doc, _, _, _, _, result = await self._try_and_report(url, FetcherType.STEALTH, max_chars=max_chars)
            return doc, result

        doc, degradable, _, _, _, result = await self._try_and_report(
            url, FetcherType.HTTP, etag=etag, last_modified=last_modified, max_chars=max_chars
        )
        if doc or not degradable:
            return doc, result

        logger.warning(f"HTTP insufficient, degrading to browser: {url}")
        try:
            from myrm_agent_harness.utils.event_utils import dispatch_custom_event

            await dispatch_custom_event(
                "agent_status",
                {
                    "event": "tool_fallback",
                    "tool": "web_fetch_tool",
                    "fallback_type": "antibot_bypass",
                    "message": "触发反爬防御，正在切换至无头浏览器模拟模式...",
                },
            )
        except Exception:
            pass

        doc, _, _, _, _, result = await self._try_and_report(url, FetcherType.BROWSER, max_chars=max_chars)
        if doc:
            return doc, result

        logger.warning(f"Browser failed, degrading to stealth: {url}")
        try:
            from myrm_agent_harness.utils.event_utils import dispatch_custom_event

            await dispatch_custom_event(
                "agent_status",
                {
                    "event": "tool_fallback",
                    "tool": "web_fetch_tool",
                    "fallback_type": "stealth_bypass",
                    "message": "浏览器模式受阻，正在切换至深度隐身模式...",
                },
            )
        except Exception:
            pass

        doc, _, _, _, _, result = await self._try_and_report(url, FetcherType.STEALTH, max_chars=max_chars)
        return doc, result

    def _report_feedback(
        self,
        url: str,
        fetcher_type: FetcherType,
        success: bool,
        latency_ms: float | None = None,
        cpu: float | None = None,
        memory: float | None = None,
    ) -> None:
        """Report fetch result to router (with multi-dimensional resource cost)."""
        self._router.report_result(url, fetcher_type, success, latency_ms, cpu, memory)

    def _handle_cache_hit(
        self, cached_item: CachedDocument, is_expired: bool, url: str, cache_key: str
    ) -> Document | None:
        """Handle cache hit logic (fresh / stale-while-revalidate / stale).

        Returns:
            Document if cache can be served immediately, None if need network fetch
        """
        cache_age = time.time() - cached_item.cached_at

        if not is_expired:
            logger.info(f"Cache hit (fresh, age={cache_age:.1f}s): {url}")
            return cached_item.doc

        if self._stale_while_revalidate:
            if self._background_queue.qsize() >= self._max_background_tasks:
                logger.warning(f"Background queue full ({self._max_background_tasks}), skipping revalidation: {url}")
                self._bg_revalidations_skipped += 1
            else:
                logger.info(f"Serving stale while revalidating (age={cache_age:.1f}s): {url}")
                priority = self._calculate_priority(cache_key)
                task = BackgroundTask(priority=priority, url=url, cache_key=cache_key, cached_item=cached_item)
                self._background_queue.put_nowait(task)
            return cached_item.doc

        if self._enable_http_validation and (cached_item.etag or cached_item.last_modified):
            logger.info(f"Cache expired (age={cache_age:.1f}s), sending conditional request: {url}")
            return None

        logger.info(f"Cache hit (stale, age={cache_age:.1f}s, no validation headers): {url}")
        return cached_item.doc

    async def _handle_fetch_error(
        self, url: str, cache_key: str, future: asyncio.Future[Document | None], error: Exception
    ) -> Document | None:
        """Unified fetch error handling.

        Note: For unexpected exceptions, sets fail_cache then re-raises to ensure callers see the error
        """
        self._fail_cache.set(cache_key, True)

        if isinstance(error, asyncio.TimeoutError):
            logger.warning(f"Crawl timeout: {url}")
            if not future.done():
                future.set_result(None)
            return None
        elif isinstance(error, (ConnectionError, OSError)):
            logger.warning(f"Network error: {url} — {error}")
            if not future.done():
                future.set_result(None)
            return None
        else:
            logger.error(f"Unexpected error during crawl: {url}", exc_info=True)
            if not future.done():
                future.set_exception(error)
            raise

    async def crawl(self, url: str, *, force_refresh: bool = False, max_chars: int = 0) -> Document | None:
        """Crawl a single URL, return Document or None.

        Args:
            url: Target URL
            force_refresh: Force refresh, bypass cache (for page update scenarios)
            max_chars: Token budget (in characters) to truncate the document intelligently.

        Concurrency: when multiple coroutines crawl the same URL, only one network request is issued; others await the result
        """
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

        # Track access frequency (for background task priority, LRU eviction prevents memory leaks)
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
                            url, etag=etag, last_modified=last_modified, max_chars=max_chars
                        )
            else:
                async with asyncio.timeout(self._crawl_timeout):
                    doc, fetch_result = await self._crawl_with_degradation(
                        url, etag=etag, last_modified=last_modified, max_chars=max_chars
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
        self, urls: list[str], *, max_concurrency: int = 10, force_refresh: bool = False, max_chars: int = 0
    ) -> tuple[SuccessResult, FailedResult]:
        """Batch-crawl multiple URLs in parallel with global concurrency cap.

        Args:
            urls: Target URL list
            max_concurrency: Maximum concurrency
            force_refresh: Force refresh all URLs, bypass cache
            max_chars: Token budget (in characters) to truncate the document intelligently.
        """
        self._ensure_workers_started()

        success_results: SuccessResult = []
        failed_results: FailedResult = []
        sem = asyncio.Semaphore(max_concurrency)

        async def process(url: str) -> None:
            async with sem:
                doc = await self.crawl(url, force_refresh=force_refresh, max_chars=max_chars)
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
        """Warm up cache (concurrent + auto-retry on failure + exponential backoff).

        Args:
            urls: URLs to warm up
            max_retries: Maximum retry count (default 3)
            initial_backoff: Initial backoff time (seconds, default 1.0s)
            max_concurrency: Maximum concurrency (default 10)

        Returns:
            (success_list, failure_list)
        """
        self._ensure_workers_started()

        success_results: SuccessResult = []
        failed_results: FailedResult = []
        results_lock = asyncio.Lock()
        sem = asyncio.Semaphore(max_concurrency)

        async def retry_one(url: str) -> None:
            """Single URL retry logic."""
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
                        else:
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

    async def _background_worker(self) -> None:
        """Background worker: dequeue tasks from priority queue and execute."""
        while True:
            try:
                task = await self._background_queue.get()
                if task.cached_item is None:
                    break

                await self._background_revalidate(task.url, task.cache_key, task.cached_item)
                self._background_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Background worker error: {e}", exc_info=True)

    async def _background_revalidate(self, url: str, cache_key: str, cached_item: CachedDocument) -> None:
        """Background async refresh of stale cache (Stale-While-Revalidate + 30s timeout).

        Args:
            url: Original URL
            cache_key: Normalized cache key
            cached_item: Currently cached document
        """
        start = time.perf_counter()
        try:
            async with asyncio.timeout(30):
                etag = cached_item.etag if self._enable_http_validation else None
                last_modified = cached_item.last_modified if self._enable_http_validation else None

                doc, fetch_result = await self._crawl_with_degradation(url, etag=etag, last_modified=last_modified)

                if fetch_result and fetch_result.status_code == 304:
                    logger.info(f"Background revalidation: 304 (cache still valid): {url}")
                    cached_item.cached_at = time.time()
                    self._crawl_cache.set(cache_key, cached_item)
                    self._bg_revalidations_success += 1
                elif doc is not None:
                    logger.info(f"Background revalidation: 200 (cache updated): {url}")
                    new_etag = fetch_result.etag if fetch_result else None
                    new_last_modified = fetch_result.last_modified if fetch_result else None
                    cached = CachedDocument(
                        doc=doc, etag=new_etag, last_modified=new_last_modified, cached_at=time.time()
                    )
                    self._crawl_cache.set(cache_key, cached)
                    self._bg_revalidations_success += 1
                else:
                    logger.warning(f"Background revalidation failed: {url}")
                    self._fail_cache.set(cache_key, True)
                    self._bg_revalidations_failed += 1
        except TimeoutError:
            logger.warning(f"Background revalidation timeout (30s): {url}")
            self._bg_revalidations_timeout += 1
        except Exception as e:
            logger.warning(f"Background revalidation error: {url} — {e}")
            self._bg_revalidations_failed += 1
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self._bg_revalidations_total_ms += elapsed_ms

    async def prefetch(self, urls: list[str], *, max_concurrency: int = 5) -> None:
        """Cache warmup: background async load URLs into cache.

        Use cases:
        - Known-upcoming URL list (e.g. search results)
        - Preload popular pages on startup

        Args:
            urls: URLs to warm up
            max_concurrency: Maximum concurrency (default 5, avoids impacting foreground requests)

        Note: This method returns nothing; failures are silently recorded in fail_cache
        """
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
        # Stop background worker pool
        if self._background_workers:
            logger.info(f"Stopping {len(self._background_workers)} background workers")
            # Send stop signals
            for _ in self._background_workers:
                self._background_queue.put_nowait(BackgroundTask(priority=0, url="", cache_key="", cached_item=None))
            # Wait for workers to exit
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
        """Get cache metrics (for monitoring and tuning).

        Returns:
            Metrics dict covering success cache, fail cache, and background tasks
        """
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
