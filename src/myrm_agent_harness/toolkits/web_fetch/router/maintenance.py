"""堆管理 and 维护Module

职责：
- LRU 驱逐（学习Cache + 持久Rule，堆结构 O(log n)）
- 堆垃圾Compress（Trigger式 + 定期）
- 长期 not yet 访问DomainClean up

[INPUT]
- (none)

[OUTPUT]
- MaintenanceManager: class — Maintenance Manager

[POS]
Provides MaintenanceManager.
"""

from __future__ import annotations

import heapq
import logging
import time
from collections.abc import Callable

from ..fetchers.protocols import FetcherType
from .models import DomainStats, HeapEntry, PersistentRule

logger = logging.getLogger(__name__)


class MaintenanceManager:
    """堆管理 and 维护管理器

    core能力：
    - 学习Cache LRU 驱逐（堆结构 O(log n)）
    - 持久Rule LRU 驱逐（堆结构 O(log n)）
    - Trigger式堆垃圾Compress（堆 > 3x Rule数）
    - 长期 not yet 访问DomainClean up
    """

    def __init__(
        self,
        *,
        promotion_min_count: int,
        promotion_min_success_rate: float,
        inactive_days: int,
    ):
        self._promotion_min_count = promotion_min_count
        self._promotion_min_success_rate = promotion_min_success_rate
        self._inactive_days = inactive_days

    def evict_lru_domain(
        self,
        learning_cache: dict[str, DomainStats],
        learning_heap: list[HeapEntry],
        remove_tracking_callback: Callable[[str], None],
    ) -> None:
        """LRU 驱逐（学习Cache）"""
        while learning_heap:
            entry = heapq.heappop(learning_heap)
            domain = entry.domain

            if domain not in learning_cache:
                continue

            stats = learning_cache[domain]
            if stats.last_access_time != entry.timestamp:
                continue

            is_high_value = (
                stats.total_attempts > 0
                and stats.successful_attempts / stats.total_attempts >= self._promotion_min_success_rate
                and stats.total_attempts >= self._promotion_min_count * 0.5
            )

            if not is_high_value:
                del learning_cache[domain]
                remove_tracking_callback(domain)
                logger.warning(f"Cache evicted (heap LRU): {domain}")
                return

        if learning_cache:
            oldest = min(learning_cache.items(), key=lambda x: x[1].last_access_time)
            del learning_cache[oldest[0]]
            remove_tracking_callback(oldest[0])
            logger.warning(f"Cache evicted (fallback): {oldest[0]}")

    def evict_persistent_rule_lru(
        self,
        persistent_rules: dict[str, PersistentRule],
        persistent_heap: list[HeapEntry],
    ) -> None:
        """持久Rule LRU 驱逐（堆结构 O(log n)）"""
        while persistent_heap:
            entry = heapq.heappop(persistent_heap)
            domain = entry.domain

            if domain not in persistent_rules:
                continue

            rule = persistent_rules[domain]
            if rule.last_access_time != entry.timestamp:
                continue

            del persistent_rules[domain]
            logger.warning(f"Persistent rules full, evicted LRU: {domain}")
            return

        if persistent_rules:
            oldest = min(persistent_rules.items(), key=lambda x: x[1].last_access_time)
            del persistent_rules[oldest[0]]
            logger.warning(f"Persistent rules evicted (fallback): {oldest[0]}")

    def compact_heaps(
        self,
        learning_cache: dict[str, DomainStats],
        learning_heap: list[HeapEntry],
        persistent_rules: dict[str, PersistentRule],
        persistent_heap: list[HeapEntry],
    ) -> None:
        """Compress堆（移除垃圾条目）"""
        valid_learning = [
            entry
            for entry in learning_heap
            if entry.domain in learning_cache and learning_cache[entry.domain].last_access_time == entry.timestamp
        ]
        learning_before = len(learning_heap)
        learning_after = len(valid_learning)
        if learning_after < learning_before:
            learning_heap.clear()
            learning_heap.extend(valid_learning)
            heapq.heapify(learning_heap)
            logger.warning(
                f"Compacted learning heap: {learning_before} -> {learning_after} "
                f"(removed {learning_before - learning_after} garbage entries)"
            )

        valid_persistent = [
            entry
            for entry in persistent_heap
            if entry.domain in persistent_rules and persistent_rules[entry.domain].last_access_time == entry.timestamp
        ]
        persistent_before = len(persistent_heap)
        persistent_after = len(valid_persistent)
        if persistent_after < persistent_before:
            persistent_heap.clear()
            persistent_heap.extend(valid_persistent)
            heapq.heapify(persistent_heap)
            logger.warning(
                f"Compacted persistent heap: {persistent_before} -> {persistent_after} "
                f"(removed {persistent_before - persistent_after} garbage entries)"
            )

    def cleanup_inactive_domains(
        self,
        learning_cache: dict[str, DomainStats],
        persistent_rules: dict[str, PersistentRule],
        failure_counters: dict[str, dict[FetcherType, int]],
        remove_tracking_callback: Callable[[str], None],
    ) -> None:
        """Clean up长时间 not yet 访问 Domain"""
        now = time.time()
        inactive_threshold = now - self._inactive_days * 86400

        to_remove_learning = [
            domain for domain, stats in learning_cache.items() if stats.last_access_time < inactive_threshold
        ]
        for domain in to_remove_learning:
            del learning_cache[domain]
            remove_tracking_callback(domain)

        to_remove_persistent = [
            domain for domain, rule in persistent_rules.items() if rule.last_access_time < inactive_threshold
        ]
        for domain in to_remove_persistent:
            del persistent_rules[domain]

        active_domains = set(learning_cache.keys()) | set(persistent_rules.keys())
        to_remove_orphaned = [domain for domain in failure_counters if domain not in active_domains]
        for domain in to_remove_orphaned:
            remove_tracking_callback(domain)

        if to_remove_learning or to_remove_persistent or to_remove_orphaned:
            logger.warning(
                f"Cleaned up {len(to_remove_learning)} learning cache, "
                f"{len(to_remove_persistent)} persistent rules, "
                f"{len(to_remove_orphaned)} orphaned trackers"
            )
