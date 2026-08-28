"""In-flight search request coalescing and cache-key helpers.

[INPUT]
utils.lru_cache::LRUCache (POS: Generic TTL-based LRU cache)
web_search.common::SearchResult (POS: Unified search result dataclass)

[OUTPUT]
bucket_search_limit, normalize_search_query: cache-key normalization helpers
await_coalesced_search: single-flight wrapper with timeout retry and leader cancellation
reset_search_coalescing_state_for_tests: test-only module state reset

[POS]
Web search coalescing layer. Deduplicates concurrent identical searches, buckets result
limits, cancels stuck leaders on coalesce timeout, and retains held locks under pressure.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from collections.abc import Awaitable, Callable

from myrm_agent_harness.toolkits.web_search.common import SearchResult
from myrm_agent_harness.utils.lru_cache import LRUCache

logger = logging.getLogger(__name__)

COALESCING_TIMEOUT_SECONDS = 30.0
_COALESCE_WAIT_MAX_ATTEMPTS = 2
_LIMIT_BUCKETS: tuple[int, ...] = (10, 20, 50, 100)
_MAX_COALESCE_LOCKS = 256

_search_cache: LRUCache[list[SearchResult]] = LRUCache(maxsize=200, ttl=900, id="web_search_api_cache")
_pending_searches: dict[str, asyncio.Future[list[SearchResult]]] = {}
_pending_leader_tasks: dict[str, asyncio.Task[None]] = {}
_coalesce_locks: dict[str, asyncio.Lock] = {}


def bucket_search_limit(limit: int) -> int:
    """Round a requested result count up to the nearest cache bucket."""
    clamped = max(1, limit)
    for bucket in _LIMIT_BUCKETS:
        if clamped <= bucket:
            return bucket
    return _LIMIT_BUCKETS[-1]


def normalize_search_query(query: str) -> str:
    """Case-fold and collapse whitespace so trivial variants share cache keys."""
    return re.sub(r"\s+", " ", query.strip().lower())


def slice_search_results(results: list[SearchResult], limit: int) -> list[SearchResult]:
    if limit <= 0:
        return []
    return results[:limit]


def build_search_cache_key(
    search_service: str,
    query: str,
    bucketed_limit: int,
    extra_suffix: str,
) -> str:
    return f"{search_service}:{normalize_search_query(query)}:{bucketed_limit}:{extra_suffix}"


def _coalesce_lock_for(cache_key: str) -> asyncio.Lock:
    lock = _coalesce_locks.get(cache_key)
    if lock is None:
        if len(_coalesce_locks) > _MAX_COALESCE_LOCKS:
            retained = {key: item for key, item in _coalesce_locks.items() if item.locked()}
            _coalesce_locks.clear()
            _coalesce_locks.update(retained)
        lock = asyncio.Lock()
        _coalesce_locks[cache_key] = lock
    return lock


async def _cancel_coalesce_leader(cache_key: str) -> None:
    _pending_searches.pop(cache_key, None)
    leader = _pending_leader_tasks.pop(cache_key, None)
    if leader is None or leader.done():
        return
    leader.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await leader


async def await_coalesced_search(
    cache_key: str,
    bucketed_limit: int,
    caller_limit: int,
    fetch: Callable[[], Awaitable[list[SearchResult]]],
    *,
    log_label: str,
) -> list[SearchResult]:
    """Return cached or in-flight search results, coalescing concurrent identical keys."""
    cached = _search_cache.get(cache_key)
    if cached is not None:
        logger.info("Search cache hit: %s", log_label)
        return slice_search_results(cached, caller_limit)

    for attempt in range(_COALESCE_WAIT_MAX_ATTEMPTS):
        lock = _coalesce_lock_for(cache_key)
        async with lock:
            cached = _search_cache.get(cache_key)
            if cached is not None:
                return slice_search_results(cached, caller_limit)

            pending = _pending_searches.get(cache_key)
            if pending is not None:
                future = pending
            else:
                future = asyncio.get_running_loop().create_future()
                _pending_searches[cache_key] = future
                leader_task = asyncio.create_task(_run_coalesce_leader(future, fetch, cache_key))
                _pending_leader_tasks[cache_key] = leader_task

        try:
            results = await asyncio.wait_for(
                asyncio.shield(future),
                timeout=COALESCING_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            logger.warning(
                "Search coalescing timeout (%.0fs), retrying coalesce: %s",
                COALESCING_TIMEOUT_SECONDS,
                log_label,
            )
            await _cancel_coalesce_leader(cache_key)
            if attempt >= _COALESCE_WAIT_MAX_ATTEMPTS - 1:
                raise
            continue

        return slice_search_results(results, caller_limit)

    raise TimeoutError(f"Search coalescing exhausted retries: {log_label}")


async def _run_coalesce_leader(
    future: asyncio.Future[list[SearchResult]],
    fetch: Callable[[], Awaitable[list[SearchResult]]],
    cache_key: str,
) -> None:
    try:
        results = await fetch()
        _search_cache.set(cache_key, results)
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
        _pending_searches.pop(cache_key, None)
        _pending_leader_tasks.pop(cache_key, None)


def reset_search_coalescing_state_for_tests() -> None:
    """Clear module-level cache and in-flight coalescing state (tests only)."""
    for cache_key in list(_pending_leader_tasks):
        task = _pending_leader_tasks.get(cache_key)
        if task is not None and not task.done():
            task.cancel()
    _search_cache.clear()
    _pending_searches.clear()
    _pending_leader_tasks.clear()
    _coalesce_locks.clear()
