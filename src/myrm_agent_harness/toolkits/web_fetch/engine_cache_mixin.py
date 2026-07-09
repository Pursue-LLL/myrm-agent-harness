"""CrawlEngine cache, coalescing, and background revalidation helpers.

[POS]
Mixin: LRU cache hits, SWR background workers, fetch error normalization.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from langchain_core.documents import Document

from .engine_types import BackgroundTask, CachedDocument

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.web_fetch.engine import CrawlEngine

logger = logging.getLogger(__name__)


class CrawlEngineCacheMixin:
    def _ensure_workers_started(self: CrawlEngine) -> None:
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

    def _calculate_priority(self: CrawlEngine, cache_key: str) -> int:
        """Compute background task priority (time decay + access frequency)."""
        stats = self._url_access_stats.get(cache_key)
        if not stats:
            return 0

        age_hours = (time.time() - stats.last_access) / 3600
        decay_factor = 0.5 ** (age_hours / 24)
        effective_count = stats.count * decay_factor
        return -round(effective_count)

    def _handle_cache_hit(
        self: CrawlEngine, cached_item: CachedDocument, is_expired: bool, url: str, cache_key: str
    ) -> Document | None:
        """Handle cache hit logic (fresh / stale-while-revalidate / stale)."""
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
        self: CrawlEngine, url: str, cache_key: str, future: asyncio.Future[Document | None], error: Exception
    ) -> Document | None:
        """Unified fetch error handling."""
        self._fail_cache.set(cache_key, True)

        if isinstance(error, asyncio.TimeoutError):
            logger.warning(f"Crawl timeout: {url}")
            if not future.done():
                future.set_result(None)
            return None
        if isinstance(error, (ConnectionError, OSError)):
            logger.warning(f"Network error: {url} — {error}")
            if not future.done():
                future.set_result(None)
            return None

        logger.error(f"Unexpected error during crawl: {url}", exc_info=True)
        if not future.done():
            future.set_exception(error)
        raise

    async def _background_worker(self: CrawlEngine) -> None:
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

    async def _background_revalidate(
        self: CrawlEngine, url: str, cache_key: str, cached_item: CachedDocument
    ) -> None:
        """Background async refresh of stale cache (Stale-While-Revalidate + 30s timeout)."""
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
