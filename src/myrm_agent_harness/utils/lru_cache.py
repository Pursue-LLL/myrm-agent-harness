"""LRU 缓存工具（同步 + 可观测）

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- time (POS: Python 标准库，时间处理)

[OUTPUT]
- LRUCache: 带 TTL 支持的 LRU 缓存类（同步，带metrics）

[POS]
LRU cache utility. OrderedDict-based LRU cache implementation with TTL support.

"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable
from typing import NamedTuple, TypeVar

_V = TypeVar("_V")


class _CacheEntry[V](NamedTuple):
    """缓存条目（值 + 时间戳）"""

    value: _V
    timestamp: float


class LRUCache[V]:
    """带 TTL 支持的泛型 LRU 缓存（同步，真正的O(1)）

    所有操作均为同步方法。内部仅涉及 OrderedDict 的纯内存操作，
    不包含任何 I/O 或 await 点，因此无需 asyncio.Lock。
    在 asyncio 单线程模型中，纯 CPU 操作不会被中断，天然线程安全。

    特性：
    - LRU驱逐：达到maxsize时驱逐最少使用的条目
    - TTL过期：自适应惰性清理（短TTL: 50%间隔，长TTL: 10%间隔）
    - 真正的O(1)：基于OrderedDict（原生move_to_end）
    - 可观测性：内置metrics（hits/stale_hits/misses、命中率、驱逐数、过期数、利用率）
    - 内存上限：支持按字节数限制（可选，默认不限制）
    - get_with_expiry：获取缓存项及其过期状态（支持 Stale-While-Revalidate）

    清理策略：
    - ttl < 60秒：cleanup_interval = max(ttl // 2, 1)（支持测试场景）
    - ttl >= 60秒：cleanup_interval = max(ttl // 10, 60)（生产场景）

    驱逐策略：
    - 按条目数：len(cache) > maxsize 时驱逐最旧条目
    - 按字节数：current_bytes > max_bytes 时驱逐最旧条目（保留至少 1 个条目）
    - 优先级：字节数驱逐 > 条目数驱逐
    """

    def __init__(
        self,
        maxsize: int = 128,
        ttl: int = 3600,
        id: str = "",
        max_bytes: int | None = None,
        size_fn: Callable[[_V], int] | None = None,
    ):
        if maxsize <= 0:
            raise ValueError(f"maxsize must be positive, got {maxsize}")
        if ttl <= 0:
            raise ValueError(f"ttl must be positive, got {ttl}")
        if max_bytes is not None and max_bytes <= 0:
            raise ValueError(f"max_bytes must be positive, got {max_bytes}")

        self._cache: OrderedDict[str, _CacheEntry[_V]] = OrderedDict()
        self.maxsize = maxsize
        self.ttl = ttl
        self.id = id
        self.max_bytes = max_bytes
        self._size_fn = size_fn or (lambda v: 1)

        # Metrics for observability
        self._hits = 0
        self._misses = 0
        self._stale_hits = 0
        self._evictions = 0
        self._expirations = 0
        self._current_bytes = 0

        # Lazy cleanup tracking with adaptive interval
        self._last_cleanup_time = time.time()
        if ttl < 60:
            self._cleanup_interval = max(ttl // 2, 1)
        else:
            self._cleanup_interval = max(ttl // 10, 60)

    def _is_expired(self, entry: _CacheEntry[_V]) -> bool:
        return time.time() - entry.timestamp > self.ttl

    def _cleanup_expired(self) -> None:
        """惰性清理过期条目（按时间间隔触发，避免每次set都O(n)扫描）"""
        current_time = time.time()

        if current_time - self._last_cleanup_time < self._cleanup_interval:
            return

        self._last_cleanup_time = current_time
        expired_keys = [key for key, entry in self._cache.items() if current_time - entry.timestamp > self.ttl]
        for key in expired_keys:
            entry = self._cache[key]
            self._current_bytes -= self._size_fn(entry.value)
            del self._cache[key]
            self._expirations += 1

    def __len__(self) -> int:
        return len(self._cache)

    def get(self, key: str, default: _V | None = None) -> _V | None:
        """获取缓存项，不存在或已过期时返回 default"""
        if key not in self._cache:
            self._misses += 1
            return default

        entry = self._cache[key]

        if self._is_expired(entry):
            self._current_bytes -= self._size_fn(entry.value)
            del self._cache[key]
            self._expirations += 1
            self._misses += 1
            return default

        self._cache.move_to_end(key)
        self._hits += 1
        return entry.value

    def get_with_expiry(self, key: str) -> tuple[_V | None, bool]:
        """获取缓存项及其过期状态（不自动清理过期项）

        Returns:
            (value, is_expired): value 为缓存值（若存在），is_expired 为是否过期
        """
        if key not in self._cache:
            self._misses += 1
            return (None, False)

        entry = self._cache[key]
        is_expired = self._is_expired(entry)

        if not is_expired:
            self._cache.move_to_end(key)
            self._hits += 1
        else:
            self._stale_hits += 1

        return (entry.value, is_expired)

    def set(self, key: str, value: _V) -> None:
        """设置缓存项"""
        current_time = time.time()
        entry = _CacheEntry(value=value, timestamp=current_time)
        value_size = self._size_fn(value)

        if key in self._cache:
            old_entry = self._cache[key]
            old_size = self._size_fn(old_entry.value)
            self._current_bytes -= old_size
            self._cache[key] = entry
            self._cache.move_to_end(key)
            self._current_bytes += value_size
        else:
            self._cache[key] = entry
            self._current_bytes += value_size

        self._cleanup_expired()

        if self.max_bytes is not None:
            while self._current_bytes > self.max_bytes and len(self._cache) > 1:
                _evicted_key, evicted_entry = self._cache.popitem(last=False)
                self._current_bytes -= self._size_fn(evicted_entry.value)
                self._evictions += 1

        while len(self._cache) > self.maxsize:
            _evicted_key, evicted_entry = self._cache.popitem(last=False)
            self._current_bytes -= self._size_fn(evicted_entry.value)
            self._evictions += 1

    def contains(self, key: str) -> bool:
        """检查键是否存在且未过期"""
        if key not in self._cache:
            return False
        entry = self._cache[key]
        if self._is_expired(entry):
            self._current_bytes -= self._size_fn(entry.value)
            del self._cache[key]
            self._expirations += 1
            return False
        return True

    def __setitem__(self, key: str, value: _V) -> None:
        self.set(key, value)

    def __getitem__(self, key: str) -> _V:
        result = self.get(key)
        if result is None and key not in self._cache:
            raise KeyError(key)
        return result  # type: ignore[return-value]

    def __contains__(self, key: object) -> bool:
        return self.contains(str(key)) if isinstance(key, str) else False

    def delete(self, key: str) -> None:
        """删除缓存项"""
        if key in self._cache:
            entry = self._cache[key]
            self._current_bytes -= self._size_fn(entry.value)
            del self._cache[key]

    def clear(self) -> None:
        """清空缓存和所有指标"""
        self._cache.clear()
        self._hits = 0
        self._misses = 0
        self._stale_hits = 0
        self._evictions = 0
        self._expirations = 0
        self._current_bytes = 0

    def items(self) -> dict[str, _V]:
        """返回所有缓存项的快照"""
        return {key: entry.value for key, entry in self._cache.items()}

    def get_metrics(self) -> dict[str, int | float]:
        """获取缓存指标（用于监控）

        Returns:
            包含命中率、驱逐数、过期数等指标的字典
        """
        hits = self._hits
        misses = self._misses
        stale_hits = self._stale_hits
        evictions = self._evictions
        expirations = self._expirations
        size = len(self._cache)
        current_bytes = self._current_bytes

        total_requests = hits + misses + stale_hits
        hit_rate = hits / total_requests if total_requests > 0 else 0.0
        stale_hit_rate = stale_hits / total_requests if total_requests > 0 else 0.0

        metrics = {
            "id": self.id,
            "hits": hits,
            "misses": misses,
            "stale_hits": stale_hits,
            "hit_rate": hit_rate,
            "stale_hit_rate": stale_hit_rate,
            "evictions": evictions,
            "expirations": expirations,
            "size": size,
            "maxsize": self.maxsize,
            "utilization": size / self.maxsize if self.maxsize > 0 else 0.0,
            "current_bytes": current_bytes,
        }

        if self.max_bytes is not None:
            metrics["max_bytes"] = self.max_bytes
            metrics["byte_utilization"] = current_bytes / self.max_bytes if self.max_bytes > 0 else 0.0

        return metrics
