"""Generic TTL Cache infrastructure.

Provides lightweight TTL cache with automatic eviction for framework-level
and business-layer use. No external dependencies, thread-safe via single-threaded design.

[INPUT]

[OUTPUT]
- TTLCache: Generic TTL cache with get/set/invalidate/evict
- CacheStats: Cache statistics (hit/miss/size/evictions)

[POS]
Framework infrastructure layer. Used by config caching, storage caching, etc.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, TypeVar

T = TypeVar("T")


@dataclass
class CacheStats:
    """Cache statistics."""

    hits: int = 0
    misses: int = 0
    size: int = 0
    evictions: int = 0
    ttl_seconds: float = 30.0
    max_size: int = 128


class TTLCache:
    """Generic TTL cache with automatic eviction.

    Thread-safe through single-threaded async design. No locks needed.
    Eviction: LRU-style (oldest entries evicted when max_size reached).
    """

    def __init__(self, ttl_seconds: float = 30.0, max_size: int = 128):
        """Initialize TTL cache.

        Args:
            ttl_seconds: Time-to-live in seconds. Entries older than this are auto-evicted.
            max_size: Maximum cache size. When exceeded, oldest entries evicted.
        """
        self._ttl_seconds = ttl_seconds
        self._max_size = max_size
        self._cache: dict[str, tuple[float, Any]] = {}
        self._stats = CacheStats(ttl_seconds=ttl_seconds, max_size=max_size)

    def get(self, key: str) -> Any | None:
        """Get cached value if still valid, otherwise return None and evict.

        Args:
            key: Cache key

        Returns:
            Cached value if valid, None otherwise
        """
        entry = self._cache.get(key)
        if entry is None:
            self._stats.misses += 1
            return None

        timestamp, value = entry
        if (time.monotonic() - timestamp) < self._ttl_seconds:
            self._stats.hits += 1
            return value

        # TTL expired, evict entry
        self._cache.pop(key, None)
        self._stats.evictions += 1
        self._stats.size = len(self._cache)
        self._stats.misses += 1
        return None

    def set(self, key: str, value: Any) -> None:
        """Store value in cache with current timestamp.

        Args:
            key: Cache key
            value: Value to cache
        """
        self._cache[key] = (time.monotonic(), value)
        self._stats.size = len(self._cache)

        # Evict oldest entries if size exceeded
        if len(self._cache) > self._max_size:
            self._evict_expired()

    def invalidate(self, key: str) -> None:
        """Invalidate (remove) cache entry.

        Args:
            key: Cache key to invalidate
        """
        if self._cache.pop(key, None) is not None:
            self._stats.size = len(self._cache)

    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()
        self._stats.size = 0

    def stats(self) -> CacheStats:
        """Get cache statistics.

        Returns:
            Current cache statistics
        """
        self._stats.size = len(self._cache)
        return self._stats

    def _evict_expired(self) -> None:
        """Remove expired entries and oldest entries if over max_size."""
        now = time.monotonic()

        # First pass: remove expired entries
        expired = [k for k, (ts, _) in self._cache.items() if now - ts >= self._ttl_seconds]
        for k in expired:
            del self._cache[k]
            self._stats.evictions += 1

        # Second pass: if still over max_size, remove oldest entries
        if len(self._cache) > self._max_size:
            # Sort by timestamp (oldest first)
            sorted_keys = sorted(self._cache.keys(), key=lambda k: self._cache[k][0])
            to_remove = len(self._cache) - self._max_size
            for k in sorted_keys[:to_remove]:
                del self._cache[k]
                self._stats.evictions += 1

        self._stats.size = len(self._cache)


__all__ = [
    "CacheStats",
    "TTLCache",
]
