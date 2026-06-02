"""Unified adaptive router.

Zero-configuration, self-learning, self-healing intelligent routing system.

Core capabilities:
- Persistent rules: JSON serialization, cross-session memory, dual-heap LRU (O(log n))
- Learning cache: short-term memory, heap-based O(log n) eviction, periodic garbage compaction
- Fast failure response: 3 failures trigger immediate escalation, sliding window statistics
- Auto promotion/demotion: stable high-frequency domains get promoted, high failure rate triggers demotion
- Precise exploration: persistent rules 0.1%, learning cache 5%
- Multi-dimensional cost learning: latency + CPU + memory, normalized units, seed cost cold-start, configurable weights
- Async persistence: background saves, non-blocking decision path
- Two-phase read-write lock: decision logic concurrent (read lock), stats update fast-serialized (write lock)

Framework boundaries:
- Single-sandbox single-process semantics, no cross-process/cross-replica consistency guarantees
- Persistence path injected by control plane via rules_file parameter

[INPUT]
- (none)

[OUTPUT]
- RouterStats: Router statistics.
- AdaptiveRouter: Adaptive router.

[POS]
Unified adaptive router.
"""

from __future__ import annotations

import heapq
import logging
import random
import time
from collections import defaultdict, deque
from fnmatch import fnmatch
from pathlib import Path
from typing import TypedDict

from ..fetchers.protocols import FetcherType
from .cost_learner import CostLearner
from .domain_metrics import DomainMetricsManager
from .maintenance import MaintenanceManager
from .models import DomainStats, FetcherDecision, HeapEntry, PersistentRule, RWLock
from .persistence import PersistenceManager

logger = logging.getLogger(__name__)


class RouterStats(TypedDict):
    """Router statistics."""

    persistent_rules: int
    wildcard_rules: int
    learning_cache: int
    persistent_hits: int
    learning_hits: int
    default_hits: int
    explorations: int
    cost_optimized: int
    cost_learning: dict[str, dict[str, float]]
    domain_metrics: dict[str, object]


class AdaptiveRouter:
    """Adaptive router.

    Memory model: persistent rules (JSON + heap LRU) + learning cache (heap LRU + garbage compaction)
    Decision mechanism: failure circuit-break + multi-dimensional cost evaluation (normalized) + exploration
    Maintenance: auto promotion/demotion + periodic cleanup + async persistence
    Concurrency model: two-phase read-write lock
      - Phase 1 (read lock): decision logic (pure read-only, allows multi-thread concurrency)
      - Phase 2 (write lock): stats update (fast serialization, minimized hold time)
    Cost dimensions: latency + CPU + memory (normalized units, configurable weights)
    """

    SEED_COSTS = CostLearner.SEED_COSTS

    @property
    def _latency_history(self):
        """Latency history (delegated to CostLearner)."""
        return self._cost_learner._latency_history

    @property
    def _cpu_history(self):
        """CPU history (delegated to CostLearner)."""
        return self._cost_learner._cpu_history

    @property
    def _memory_history(self):
        """Memory history (delegated to CostLearner)."""
        return self._cost_learner._memory_history

    def __init__(
        self,
        *,
        rules_file: str | Path | None = None,
        http_fail_threshold: int = 3,
        browser_fail_threshold: int = 2,
        promotion_min_count: int = 100,
        promotion_min_success_rate: float = 0.95,
        demotion_fail_count: int = 10,
        demotion_fail_rate: float = 0.3,
        demotion_fail_window_hours: int = 24,
        max_cache_size: int = 10000,
        max_persistent_rules: int = 10000,
        cleanup_interval_minutes: int = 60,
        inactive_days: int = 7,
        exploration_rate: float = 0.05,
        save_interval_minutes: int = 5,
        latency_weight: float = 1.0,
        cpu_weight: float = 0.3,
        memory_weight: float = 0.2,
        domain_metrics_manager: DomainMetricsManager | None = None,
    ):
        self._lock = RWLock()

        rules_path = Path(rules_file) if rules_file else Path(__file__).parent / "adaptive_rules.json"
        self._persistence = PersistenceManager(rules_path)

        if domain_metrics_manager is not None:
            self._domain_metrics_manager = domain_metrics_manager
        else:
            from .domain_metrics import get_global_domain_metrics_manager

            self._domain_metrics_manager = get_global_domain_metrics_manager()

        self._cost_learner = CostLearner(
            latency_weight=latency_weight,
            cpu_weight=cpu_weight,
            memory_weight=memory_weight,
            domain_metrics_manager=self._domain_metrics_manager,
        )
        self._maintenance = MaintenanceManager(
            promotion_min_count=promotion_min_count,
            promotion_min_success_rate=promotion_min_success_rate,
            inactive_days=inactive_days,
        )

        self._persistent_rules, self._wildcard_rules, self._persistent_heap = self._persistence.load_rules()

        self._learning_cache: dict[str, DomainStats] = {}
        self._learning_heap: list[HeapEntry] = []

        self._failure_counters: dict[str, dict[FetcherType, int]] = defaultdict(lambda: defaultdict(int))
        self._recent_failures: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=100))
        self._recent_attempts: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=100))
        self._forced_fetchers: dict[str, tuple[FetcherType, float]] = {}

        self._http_fail_threshold = http_fail_threshold
        self._browser_fail_threshold = browser_fail_threshold
        self._promotion_min_count = promotion_min_count
        self._promotion_min_success_rate = promotion_min_success_rate
        self._demotion_fail_count = demotion_fail_count
        self._demotion_fail_rate = demotion_fail_rate
        self._demotion_fail_window_hours = demotion_fail_window_hours
        self._max_cache_size = max_cache_size
        self._max_persistent_rules = max_persistent_rules
        self._cleanup_interval_minutes = cleanup_interval_minutes
        self._exploration_rate = exploration_rate
        self._save_interval_minutes = save_interval_minutes

        self._last_cleanup_time = time.time()
        self._last_save_time = time.time()
        self._last_heap_compact_time = time.time()

        self._stats = {
            "persistent_hits": 0,
            "learning_hits": 0,
            "default_hits": 0,
            "explorations": 0,
            "cost_optimized": 0,
        }

        logger.info("AdaptiveRouter initialized")

    def _extract_domain(self, url: str) -> str:
        """Extract domain name."""
        from urllib.parse import urlparse

        try:
            parsed = urlparse(url)
            return parsed.netloc.lower() or url.lower()
        except Exception:
            return url.lower()

    def _lookup_rules(self, domain: str) -> FetcherType | None:
        """Query persistent rules (exact match + wildcard match)."""
        if domain in self._persistent_rules:
            return self._persistent_rules[domain].fetcher_type

        for pattern, fetcher_type in self._wildcard_rules.items():
            if fnmatch(domain, pattern):
                return fetcher_type

        return None

    def _get_adaptive_exploration_rate(self, domain: str) -> float:
        """Adaptive exploration rate based on domain access frequency.

        Strategy:
        - High-frequency domains (>100 visits): reduced rate (base_rate / 10)
        - Medium-frequency domains (10-100 visits): normal rate
        - Low-frequency domains (<10 visits): increased rate (base_rate * 3)
        """
        metrics = self._domain_metrics_manager.get(domain)
        if not metrics:
            return self._exploration_rate * 3.0

        access_count = metrics.total_accesses
        if access_count > 100:
            return self._exploration_rate / 10.0
        elif access_count > 10:
            return self._exploration_rate
        else:
            return self._exploration_rate * 3.0

    def _get_cost_optimization_threshold(self, domain: str) -> int:
        """Compute cost optimization threshold based on domain access frequency.

        Strategy:
        - Low-frequency domains (≤10 visits): 10 visits (thorough learning)
        - High-frequency domains (≥100 visits): 3 visits (fast optimization)
        - Medium-frequency domains: linear interpolation
        """
        metrics = self._domain_metrics_manager.get(domain)
        if not metrics:
            return 10

        accesses = metrics.total_accesses

        if accesses <= 10:
            return 10
        if accesses >= 100:
            return 3

        ratio = (accesses - 10) / 90
        return int(10 - 7 * ratio)

    def _should_explore(
        self, fetcher_type: FetcherType, min_fetcher: FetcherType, rate: float | None = None
    ) -> tuple[FetcherType, bool]:
        """Exploration: probabilistically try a cheaper fetcher (no lower than min_fetcher).

        Args:
            fetcher_type: Currently selected fetcher
            min_fetcher: Minimum available fetcher (failure escalation floor)
            rate: Exploration rate

        Returns:
            (fetcher_type, explored): Selected fetcher and whether exploration occurred
        """
        exploration_rate = rate if rate is not None else self._exploration_rate

        if random.random() < exploration_rate:
            if fetcher_type == FetcherType.STEALTH:
                explored_fetcher = FetcherType.BROWSER
                if explored_fetcher.value >= min_fetcher.value:
                    return explored_fetcher, True
            elif fetcher_type == FetcherType.BROWSER:
                explored_fetcher = FetcherType.HTTP
                if explored_fetcher.value >= min_fetcher.value:
                    return explored_fetcher, True

        return fetcher_type, False

    def _remove_domain_tracking(self, domain: str) -> None:
        """Remove all tracking data for a domain (failure counters, failure records, request records)."""
        self._failure_counters.pop(domain, None)
        self._recent_failures.pop(domain, None)
        self._recent_attempts.pop(domain, None)

    def _cleanup_expired_forced_fetchers(self) -> None:
        """Clean up expired force-fetcher overrides (internal; caller must hold write lock)."""
        now = time.time()
        expired = [domain for domain, (_, expire_time) in self._forced_fetchers.items() if expire_time <= now]

        for domain in expired:
            del self._forced_fetchers[domain]

        if expired:
            logger.warning(f"Cleaned up {len(expired)} expired forced fetchers")

    def select(self, url: str) -> FetcherDecision:
        """Select a fetcher (two-phase: read-lock decision + write-lock stats, concurrency-safe).

        Failure counting strategy:
        - Prefer DomainMetrics time-decayed counts (24h window)
        - Fall back to in-memory counters

        Exploration rate strategy:
        - Dynamically adjusted based on domain access frequency

        Force overrides:
        - Check for temporary force-fetcher override (for debugging and ops)
        """
        with self._lock.read_lock():
            domain = self._extract_domain(url)

            if domain in self._forced_fetchers:
                fetcher, expire_time = self._forced_fetchers[domain]
                if time.time() < expire_time:
                    return FetcherDecision(fetcher, reason="forced_override")

            metrics = self._domain_metrics_manager.get(domain)
            if metrics:
                http_fails = metrics.get_recent_failures_count(FetcherType.HTTP, self._demotion_fail_window_hours)
                browser_fails = metrics.get_recent_failures_count(FetcherType.BROWSER, self._demotion_fail_window_hours)
            else:
                http_fails = self._failure_counters[domain].get(FetcherType.HTTP, 0)
                browser_fails = self._failure_counters[domain].get(FetcherType.BROWSER, 0)

            min_fetcher = FetcherType.HTTP
            if http_fails >= self._http_fail_threshold:
                min_fetcher = FetcherType.BROWSER
                if browser_fails >= self._browser_fail_threshold:
                    min_fetcher = FetcherType.STEALTH

            cached_fetcher = self._lookup_rules(domain)
            if cached_fetcher:
                if cached_fetcher.value < min_fetcher.value:
                    fetcher_type = min_fetcher
                    reason = "failure_override"
                else:
                    fetcher_type = cached_fetcher
                    reason = "persistent_rule"

                persistent_exploration_rate = self._exploration_rate / 50.0
                final_fetcher, explored = self._should_explore(
                    fetcher_type, min_fetcher, rate=persistent_exploration_rate
                )

                decision = FetcherDecision(
                    fetcher_type=final_fetcher,
                    reason=reason if not explored else "exploration",
                )
                decision._hit_type = "persistent"
                decision._explored = explored
            elif domain in self._learning_cache:
                stats = self._learning_cache[domain]
                cached_fetcher = stats.fetcher_type

                if cached_fetcher.value < min_fetcher.value:
                    fetcher_type = min_fetcher
                    reason = "failure_escalation"
                else:
                    threshold = self._get_cost_optimization_threshold(domain)
                    if stats.total_attempts >= threshold:
                        fetcher_type = self._select_by_cost(domain, min_fetcher)
                        reason = "cost_optimized" if fetcher_type != cached_fetcher else "learning_cache"
                    else:
                        fetcher_type = cached_fetcher
                        reason = "learning_cache"

                adaptive_rate = self._get_adaptive_exploration_rate(domain)
                final_fetcher, explored = self._should_explore(fetcher_type, min_fetcher, rate=adaptive_rate)

                decision = FetcherDecision(
                    fetcher_type=final_fetcher,
                    reason=reason if not explored else "exploration",
                )
                decision._hit_type = "learning"
                decision._cost_optimized = reason == "cost_optimized" and fetcher_type != cached_fetcher
                decision._explored = explored
            else:
                decision = FetcherDecision(fetcher_type=min_fetcher, reason="failure_based")
                decision._hit_type = "default"

        with self._lock.write_lock():
            now = time.time()
            self._recent_attempts[domain].append(now)

            if domain in self._persistent_rules:
                self._persistent_rules[domain].last_access_time = now
                heapq.heappush(self._persistent_heap, HeapEntry(now, domain))

            if decision._hit_type == "persistent":
                self._stats["persistent_hits"] += 1
            elif decision._hit_type == "learning":
                self._stats["learning_hits"] += 1
            elif decision._hit_type == "default":
                self._stats["default_hits"] += 1

            if decision._explored:
                self._stats["explorations"] += 1

            if decision._cost_optimized:
                self._stats["cost_optimized"] += 1

            self._maybe_periodic_maintenance()

        return decision

    def _select_by_cost(self, domain: str, min_fetcher: FetcherType) -> FetcherType:
        """Cost-aware decision."""
        candidates = [ft for ft in FetcherType if ft.value >= min_fetcher.value]

        best_fetcher = min_fetcher
        best_score = float("inf")

        for fetcher in candidates:
            expected_cost = self._cost_learner.calculate_expected_cost(domain, fetcher, self._learning_cache)
            if expected_cost < best_score:
                best_score = expected_cost
                best_fetcher = fetcher

        return best_fetcher

    def report_result(
        self,
        url: str,
        fetcher_type: FetcherType,
        success: bool,
        latency_ms: float | None = None,
        cpu_percent: float | None = None,
        memory_mb: float | None = None,
    ) -> None:
        """Report crawl result (uses write lock, exclusive).

        Data flow:
        - Sync latency and success rate to DomainMetrics
        - Sync to CostLearner (global + domain-level)
        - Update failure counters and promotion/demotion checks
        """
        with self._lock.write_lock():
            domain = self._extract_domain(url)

            self._cost_learner.record_cost(fetcher_type, latency_ms, cpu_percent, memory_mb, domain=domain)

            metrics = self._domain_metrics_manager.get_or_create(domain)
            metrics.record_fetcher_result(fetcher_type, success, latency_ms)

            if not success:
                self._failure_counters[domain][fetcher_type] += 1
                self._recent_failures[domain].append(time.time())
                self._check_demotion(domain)
            else:
                self._failure_counters[domain][fetcher_type] = 0

            now = time.time()

            if domain in self._persistent_rules:
                self._persistent_rules[domain].last_access_time = now
                heapq.heappush(self._persistent_heap, HeapEntry(now, domain))

            if domain not in self._persistent_rules:
                if domain not in self._learning_cache:
                    self._learning_cache[domain] = DomainStats(
                        fetcher_type=fetcher_type,
                        total_attempts=1,
                        successful_attempts=1 if success else 0,
                        last_access_time=now,
                    )
                    heapq.heappush(self._learning_heap, HeapEntry(now, domain))
                else:
                    stats = self._learning_cache[domain]
                    stats.total_attempts += 1
                    if success:
                        stats.successful_attempts += 1
                        stats.fetcher_type = fetcher_type
                    stats.last_access_time = now

                self._check_promotion(domain)

            if len(self._learning_cache) > self._max_cache_size:
                self._maintenance.evict_lru_domain(
                    self._learning_cache,
                    self._learning_heap,
                    self._remove_domain_tracking,
                )

    def _check_promotion(self, domain: str) -> None:
        """Check whether promotion conditions are met."""
        if domain not in self._learning_cache:
            return

        stats = self._learning_cache[domain]
        success_rate = stats.successful_attempts / stats.total_attempts if stats.total_attempts > 0 else 0

        if stats.total_attempts >= self._promotion_min_count and success_rate >= self._promotion_min_success_rate:
            if len(self._persistent_rules) >= self._max_persistent_rules:
                self._maintenance.evict_persistent_rule_lru(
                    self._persistent_rules,
                    self._persistent_heap,
                )

            now = time.time()
            self._persistent_rules[domain] = PersistentRule(fetcher_type=stats.fetcher_type, last_access_time=now)
            heapq.heappush(self._persistent_heap, HeapEntry(now, domain))

            del self._learning_cache[domain]

            logger.warning(
                f"Promoted {domain} -> {stats.fetcher_type.name} "
                f"(attempts={stats.total_attempts}, rate={success_rate:.2%})"
            )

    def _check_demotion(self, domain: str) -> None:
        """Check whether demotion conditions are met (based on failure rate or absolute failure count)."""
        if domain not in self._persistent_rules:
            return

        now = time.time()
        cutoff_time = now - self._demotion_fail_window_hours * 3600
        recent_fails = [t for t in self._recent_failures[domain] if t >= cutoff_time]
        recent_attempts = [t for t in self._recent_attempts[domain] if t >= cutoff_time]

        if len(recent_attempts) == 0:
            return

        fail_count = len(recent_fails)
        failure_rate = fail_count / len(recent_attempts)

        should_demote = fail_count >= self._demotion_fail_count or (
            failure_rate > self._demotion_fail_rate and len(recent_attempts) >= self._demotion_fail_count
        )

        if should_demote:
            rule = self._persistent_rules[domain]
            del self._persistent_rules[domain]
            self._remove_domain_tracking(domain)

            logger.warning(
                f"Demoted {domain} (was {rule.fetcher_type.name}, {fail_count} failures, rate={failure_rate:.1%})"
            )

    def _maybe_periodic_maintenance(self) -> None:
        """Periodic maintenance: cleanup + heap compaction + async save.

        Trigger conditions:
        - Cleanup: every 60 minutes
        - Heap compaction: when heap size exceeds 3x or every 15 minutes
        - Save: every 5 minutes
        """
        now = time.time()

        if now - self._last_cleanup_time > self._cleanup_interval_minutes * 60:
            self._maintenance.cleanup_inactive_domains(
                self._learning_cache,
                self._persistent_rules,
                self._failure_counters,
                self._remove_domain_tracking,
            )
            self._cleanup_expired_forced_fetchers()
            self._domain_metrics_manager.cleanup_inactive_domains()
            self._last_cleanup_time = now

        persistent_heap_threshold = len(self._persistent_rules) * 3
        learning_heap_threshold = len(self._learning_cache) * 3
        heap_oversized = (
            len(self._persistent_heap) > persistent_heap_threshold or len(self._learning_heap) > learning_heap_threshold
        )

        if heap_oversized or now - self._last_heap_compact_time > 15 * 60:
            self._maintenance.compact_heaps(
                self._learning_cache,
                self._learning_heap,
                self._persistent_rules,
                self._persistent_heap,
            )
            self._last_heap_compact_time = now

        if now - self._last_save_time > self._save_interval_minutes * 60:
            self._persistence.request_save(self._persistent_rules, self._wildcard_rules)
            self._domain_metrics_manager.request_save()
            self._last_save_time = now

    def get_stats(self) -> RouterStats:
        """Get statistics (uses read lock, allows concurrency)."""
        with self._lock.read_lock():
            cost_stats = self._cost_learner.get_cost_stats()
            domain_stats = self._domain_metrics_manager.get_stats()

            return {
                "persistent_rules": len(self._persistent_rules),
                "wildcard_rules": len(self._wildcard_rules),
                "learning_cache": len(self._learning_cache),
                "persistent_hits": self._stats["persistent_hits"],
                "learning_hits": self._stats["learning_hits"],
                "default_hits": self._stats["default_hits"],
                "explorations": self._stats["explorations"],
                "cost_optimized": self._stats["cost_optimized"],
                "cost_learning": cost_stats,
                "domain_metrics": domain_stats,
            }

    def force_fetcher(self, url: str, fetcher_type: FetcherType, ttl_minutes: int = 60) -> None:
        """Force a specific URL to use a particular fetcher (for debugging and ops).

        Args:
            url: Target URL
            fetcher_type: Fetcher to force
            ttl_minutes: Override TTL (minutes)
        """
        domain = self._extract_domain(url)
        expire_time = time.time() + ttl_minutes * 60

        with self._lock.write_lock():
            self._forced_fetchers[domain] = (fetcher_type, expire_time)
            logger.warning(f"Forced {domain} to use {fetcher_type.name} for {ttl_minutes} minutes")

    def clear_forced_fetcher(self, url: str) -> bool:
        """Clear forced fetcher override.

        Returns:
            bool: Whether it existed and was cleared
        """
        domain = self._extract_domain(url)
        with self._lock.write_lock():
            if domain in self._forced_fetchers:
                del self._forced_fetchers[domain]
                logger.warning(f"Cleared forced fetcher for {domain}")
                return True
            return False

    def reset_domain(self, url: str) -> bool:
        """Reset domain learning data (for correcting erroneous learning).

        Returns:
            bool: Whether the domain existed and was reset
        """
        domain = self._extract_domain(url)
        with self._lock.write_lock():
            self._remove_domain_tracking(domain)

        result = self._domain_metrics_manager.reset_domain(domain)
        if result:
            self._persistence.save_rules(self._persistent_rules, self._wildcard_rules)
        return result

    def shutdown(self) -> None:
        """Save state on shutdown (uses write lock to ensure data consistency)."""
        with self._lock.write_lock():
            self._persistence.shutdown(self._persistent_rules, self._wildcard_rules)
            self._domain_metrics_manager.shutdown()

    def _cleanup_inactive_domains(self) -> None:
        """Clean up long-idle domains (delegated to maintenance)."""
        self._maintenance.cleanup_inactive_domains(
            self._learning_cache,
            self._persistent_rules,
            self._failure_counters,
            self._remove_domain_tracking,
        )

    def _save_persistent_rules(self) -> None:
        """Save persistent rules to JSON file (delegated to persistence)."""
        self._persistence.save_rules(self._persistent_rules, self._wildcard_rules)

    def _estimate_cost(self, fetcher_type: FetcherType):
        """Estimate resource cost (delegated to cost_learner)."""
        return self._cost_learner.estimate_cost(fetcher_type)

    def _calculate_expected_cost(self, domain: str, fetcher_type: FetcherType) -> float:
        """Compute expected cost (delegated to cost_learner)."""
        return self._cost_learner.calculate_expected_cost(domain, fetcher_type, self._learning_cache)
