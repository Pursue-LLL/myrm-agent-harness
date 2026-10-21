"""Three-dimensional bounded cache with TTL, LRU item count, and Byte-Cap limits.

Eradicates unbounded in-memory dictionaries that cause progressive RSS growth
and late-night Kubernetes OOMKilled events.

[INPUT]
- __future__
- time
- collections
- memory_sentinel_types

[OUTPUT]
- ThreeDimensionalBoundedCache

[POS]
Three-dimensional bounded cache with TTL, LRU item count, and Byte-Cap limits.
"""

from __future__ import annotations

import time
from collections import OrderedDict

from .memory_sentinel_types import (
    BoundedCacheStats,
)


class ThreeDimensionalBoundedCache:
    """Bounded cache strictly enforcing Time-To-Live, LRU capacity, and Heap Byte limits."""

    def __init__(
        self,
        max_items: int = 1000,
        max_bytes: int = 64 * 1024 * 1024,  # 64 MB default
        default_ttl_s: float = 600.0,  # 10 minutes default
    ) -> None:
        self.max_items = max_items
        self.max_bytes = max_bytes
        self.default_ttl_s = default_ttl_s

        # Storage mapping: key -> (value, expiry_timestamp, byte_size)
        self._cache: OrderedDict[str, tuple[str, float, int]] = OrderedDict()
        self._current_bytes: int = 0
        self._hit_count: int = 0
        self._miss_count: int = 0
        self._eviction_count: int = 0

    def get(self, key: str) -> str | None:
        """Retrieve a cached entry, checking expiration and updating LRU recency."""
        entry = self._cache.get(key)
        if entry is None:
            self._miss_count += 1
            return None

        val, expiry, byte_size = entry
        now = time.time()

        if now >= expiry:
            # Expired: evict immediately
            self._cache.pop(key, None)
            self._current_bytes = max(0, self._current_bytes - byte_size)
            self._eviction_count += 1
            self._miss_count += 1
            return None

        # Hit: promote to most-recently-used position
        self._cache.move_to_end(key)
        self._hit_count += 1
        return val

    def set(
        self,
        key: str,
        value: str,
        custom_ttl_s: float | None = None,
    ) -> None:
        """Store a string value while strictly enforcing capacity and byte caps."""
        now = time.time()
        ttl = custom_ttl_s if custom_ttl_s is not None else self.default_ttl_s
        expiry = now + ttl
        new_byte_size = len(value.encode("utf-8"))

        # If key already present, refund its current byte allocation before re-evaluating
        if key in self._cache:
            _, _, old_size = self._cache.pop(key)
            self._current_bytes = max(0, self._current_bytes - old_size)

        # 1. Enforce Item Count Capacity Limit via LRU eviction
        while len(self._cache) >= self.max_items and self._cache:
            _, (_, _, evicted_size) = self._cache.popitem(last=False)
            self._current_bytes = max(0, self._current_bytes - evicted_size)
            self._eviction_count += 1

        # 2. Enforce Byte-Cap Limit via LRU eviction
        while (self._current_bytes + new_byte_size > self.max_bytes) and self._cache:
            _, (_, _, evicted_size) = self._cache.popitem(last=False)
            self._current_bytes = max(0, self._current_bytes - evicted_size)
            self._eviction_count += 1

        # Insert entry if it fits within the absolute byte cap
        if new_byte_size <= self.max_bytes:
            self._cache[key] = (value, expiry, new_byte_size)
            self._current_bytes += new_byte_size

    def delete(self, key: str) -> bool:
        """Remove a cached entry by key."""
        entry = self._cache.pop(key, None)
        if entry is not None:
            _, _, byte_size = entry
            self._current_bytes = max(0, self._current_bytes - byte_size)
            return True
        return False

    def clear(self) -> None:
        """Clear all entries and reset byte allocations."""
        self._cache.clear()
        self._current_bytes = 0

    def get_stats(self) -> BoundedCacheStats:
        """Return real-time operational telemetry for this bounded cache."""
        return BoundedCacheStats(
            item_count=len(self._cache),
            current_bytes=self._current_bytes,
            max_bytes=self.max_bytes,
            max_items=self.max_items,
            hit_count=self._hit_count,
            miss_count=self._miss_count,
            eviction_count=self._eviction_count,
        )
