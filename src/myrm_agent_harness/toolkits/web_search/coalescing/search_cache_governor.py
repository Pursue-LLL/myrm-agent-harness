"""Dynamic query freshness and search cache governor.

Orchestrates freshness classification, tier-specific TTL caching, and
single-flight deduplication to prevent stampedes even under realtime bypass.

[INPUT]
- toolkits.web_search.coalescing.freshness_intent_types::FreshnessDetectionResult, FreshnessGovernorConfig
  (POS: Data models and intent types for Dynamic Query Freshness and Cache Governance.)
- toolkits.web_search.coalescing.query_freshness_detector::QueryFreshnessDetector (POS: Query freshness
  detector for web search and request caching.)
- toolkits.web_search.coalescing.search_coalescing::bucket_search_limit, build_search_cache_key,
  has_cacheable_search_results, slice_search_results (POS: Web search coalescing layer.)
- toolkits.web_search.core.common::SearchResult (POS: Shared data models for web search results, used across
  the search toolkit.)

[OUTPUT]
- GovernedSearchReceipt: Audit metadata emitted alongside search results.
- SearchCacheGovernor: Governor managing dynamic TTL expiration and protected single-flight execution.

[POS]
Dynamic query freshness and search cache governor.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import NamedTuple

from myrm_agent_harness.toolkits.web_search.coalescing.freshness_intent_types import (
    FreshnessDetectionResult,
    FreshnessGovernorConfig,
)
from myrm_agent_harness.toolkits.web_search.coalescing.query_freshness_detector import (
    QueryFreshnessDetector,
)
from myrm_agent_harness.toolkits.web_search.coalescing.search_coalescing import (
    bucket_search_limit,
    build_search_cache_key,
    has_cacheable_search_results,
    slice_search_results,
)
from myrm_agent_harness.toolkits.web_search.core.common import SearchResult

logger = logging.getLogger(__name__)

COALESCING_TIMEOUT_SECONDS = 30.0
_COALESCE_WAIT_MAX_ATTEMPTS = 2
_MAX_COALESCE_LOCKS = 256


class _TimestampedCacheEntry(NamedTuple):
    results: list[SearchResult]
    expire_at: float


@dataclass(frozen=True, slots=True)
class GovernedSearchReceipt:
    """Audit metadata emitted alongside search results."""

    detection: FreshnessDetectionResult
    cache_hit: bool
    single_flight_coalesced: bool
    duration_ms: float


class SearchCacheGovernor:
    """Governor managing dynamic TTL expiration and protected single-flight execution."""

    def __init__(
        self,
        config: FreshnessGovernorConfig | None = None,
        detector: QueryFreshnessDetector | None = None,
    ) -> None:
        self._config = config or FreshnessGovernorConfig()
        self._detector = detector or QueryFreshnessDetector(self._config)
        self._dynamic_cache: dict[str, _TimestampedCacheEntry] = {}
        self._pending_searches: dict[str, asyncio.Future[list[SearchResult]]] = {}
        self._pending_leaders: dict[str, asyncio.Task[None]] = {}
        self._coalesce_locks: dict[str, asyncio.Lock] = {}

    def get_cached(self, cache_key: str) -> list[SearchResult] | None:
        """Retrieve unexpired results from the dynamic cache."""
        entry = self._dynamic_cache.get(cache_key)
        if entry is None:
            return None
        if time.time() > entry.expire_at:
            self._dynamic_cache.pop(cache_key, None)
            return None
        return entry.results

    def store_cache(
        self, cache_key: str, results: list[SearchResult], ttl_seconds: int
    ) -> None:
        """Persist results with explicit TTL, skipping if TTL <= 0."""
        if ttl_seconds <= 0 or not has_cacheable_search_results(results):
            return
        expire_at = time.time() + ttl_seconds
        self._dynamic_cache[cache_key] = _TimestampedCacheEntry(
            results=results, expire_at=expire_at
        )

    async def execute_governed_search(
        self,
        search_service: str,
        query: str,
        caller_limit: int,
        fetch: Callable[[], Awaitable[list[SearchResult]]],
        *,
        explicit_bypass: bool = False,
        prompt_hint: str | None = None,
        log_label: str = "",
    ) -> tuple[list[SearchResult], GovernedSearchReceipt]:
        """Execute search with dynamic freshness classification and stampede-safe single flight."""
        start_time = time.perf_counter()
        bucketed_limit = bucket_search_limit(caller_limit)
        detection = self._detector.detect(
            query,
            explicit_bypass=explicit_bypass,
            prompt_hint=prompt_hint,
        )

        suffix = (
            "bypass"
            if detection.is_bypass_cache
            else f"ttl{detection.effective_ttl_seconds}"
        )
        cache_key = build_search_cache_key(
            search_service, query, bucketed_limit, suffix
        )

        # 1. Cache hit evaluation (bypassed if freshness requires realtime data)
        if not detection.is_bypass_cache:
            cached = self.get_cached(cache_key)
            if cached is not None:
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                receipt = GovernedSearchReceipt(
                    detection=detection,
                    cache_hit=True,
                    single_flight_coalesced=False,
                    duration_ms=round(duration_ms, 2),
                )
                return slice_search_results(cached, caller_limit), receipt

        # 2. Single-flight coalescing to prevent stampedes (active even for realtime queries)
        is_coalesced = False
        for attempt in range(_COALESCE_WAIT_MAX_ATTEMPTS):
            lock = self._get_lock(cache_key)
            async with lock:
                if not detection.is_bypass_cache:
                    cached = self.get_cached(cache_key)
                    if cached is not None:
                        duration_ms = (time.perf_counter() - start_time) * 1000.0
                        receipt = GovernedSearchReceipt(
                            detection=detection,
                            cache_hit=True,
                            single_flight_coalesced=True,
                            duration_ms=round(duration_ms, 2),
                        )
                        return slice_search_results(cached, caller_limit), receipt

                pending = self._pending_searches.get(cache_key)
                if pending is not None:
                    future = pending
                    is_coalesced = True
                else:
                    future = asyncio.get_running_loop().create_future()
                    self._pending_searches[cache_key] = future
                    leader_task = asyncio.create_task(
                        self._run_leader(future, fetch, cache_key, detection)
                    )
                    self._pending_leaders[cache_key] = leader_task

            try:
                results = await asyncio.wait_for(
                    asyncio.shield(future),
                    timeout=COALESCING_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                logger.warning(
                    "Search governor timeout (%.0fs), retry attempt %d: %s",
                    COALESCING_TIMEOUT_SECONDS,
                    attempt,
                    log_label,
                )
                await self._cancel_leader(cache_key)
                if attempt >= _COALESCE_WAIT_MAX_ATTEMPTS - 1:
                    raise
                continue

            duration_ms = (time.perf_counter() - start_time) * 1000.0
            receipt = GovernedSearchReceipt(
                detection=detection,
                cache_hit=False,
                single_flight_coalesced=is_coalesced,
                duration_ms=round(duration_ms, 2),
            )
            return slice_search_results(results, caller_limit), receipt

        raise TimeoutError(f"Search governor exhausted retries: {log_label}")

    async def _run_leader(
        self,
        future: asyncio.Future[list[SearchResult]],
        fetch: Callable[[], Awaitable[list[SearchResult]]],
        cache_key: str,
        detection: FreshnessDetectionResult,
    ) -> None:
        """Run single-flight leader and selectively persist results based on freshness tier."""
        try:
            results = await fetch()
            if not detection.is_bypass_cache and detection.effective_ttl_seconds > 0:
                self.store_cache(
                    cache_key, results, detection.effective_ttl_seconds
                )
            if not future.done():
                future.set_result(results)
        except asyncio.CancelledError:
            if not future.done():
                future.cancel()
            raise
        except Exception as exc:
            if not future.done():
                future.set_exception(exc)
        finally:
            self._pending_searches.pop(cache_key, None)
            self._pending_leaders.pop(cache_key, None)

    def _get_lock(self, key: str) -> asyncio.Lock:
        lock = self._coalesce_locks.get(key)
        if lock is None:
            if len(self._coalesce_locks) > _MAX_COALESCE_LOCKS:
                retained = {k: v for k, v in self._coalesce_locks.items() if v.locked()}
                self._coalesce_locks.clear()
                self._coalesce_locks.update(retained)
            lock = asyncio.Lock()
            self._coalesce_locks[key] = lock
        return lock

    async def _cancel_leader(self, cache_key: str) -> None:
        self._pending_searches.pop(cache_key, None)
        leader = self._pending_leaders.pop(cache_key, None)
        if leader is None or leader.done():
            return
        leader.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await leader

    def reset_state_for_tests(self) -> None:
        """Clear all in-memory caches, locks, and leader tasks for test isolation."""
        for key in list(self._pending_leaders):
            task = self._pending_leaders.get(key)
            if task is not None and not task.done():
                task.cancel()
        self._dynamic_cache.clear()
        self._pending_searches.clear()
        self._pending_leaders.clear()
        self._coalesce_locks.clear()
