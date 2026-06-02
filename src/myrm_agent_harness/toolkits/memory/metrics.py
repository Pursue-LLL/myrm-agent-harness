"""Memory search quality metrics — lightweight, thread-safe counters.

Tracks retrieval effectiveness: zero-result rate, score distribution,
latency, and per-type hit rates. Designed for production diagnostics
without impacting search performance.

Dual-channel architecture:
- In-memory snapshot for real-time diagnostics (SearchSnapshot)
- OTEL instruments for persistent monitoring/alerting (zero overhead when OTEL is not configured)

Thread-safe via threading.Lock for concurrent access.

[INPUT]
- (none)

[OUTPUT]
- SearchSnapshot: Immutable snapshot of search metrics at a point in time.
- SearchMetrics: Accumulates memory search quality statistics.
- StorageSnapshot: Immutable snapshot of storage metrics.
- StorageMetrics: Tracks memory storage size and usage.
- get_search_metrics: Get or create the global SearchMetrics singleton.

[POS]
Memory search quality metrics — lightweight, thread-safe counters.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from collections.abc import Generator
from contextlib import contextmanager, suppress
from dataclasses import dataclass

from opentelemetry.metrics import Counter, Histogram

from myrm_agent_harness.toolkits.memory.types import MemoryType

logger = logging.getLogger(__name__)


@dataclass
class SearchSnapshot:
    """Immutable snapshot of search metrics at a point in time."""

    total_searches: int
    zero_result_count: int
    zero_result_rate: float
    avg_score: float
    min_score: float
    max_score: float
    avg_result_count: float
    avg_latency_ms: float
    p95_latency_ms: float
    hit_rate_by_type: dict[str, float]
    cross_session_hits: int
    total_sourced_hits: int
    cross_session_hit_rate: float


class SearchMetrics:
    """Accumulates memory search quality statistics.

    Usage:
        metrics = SearchMetrics()

        with metrics.track_search() as tracker:
            results = retriever.rank(...)
            tracker.record(results)

        snapshot = metrics.snapshot()
        print(f"Zero result rate: {snapshot.zero_result_rate:.1%}")
    """

    __slots__ = (
        "_cross_session_hits",
        "_latencies_ms",
        "_latency_max_stored",
        "_lock",
        "_otel_assistant_reference_query_count",
        "_otel_keyword_boost_count",
        "_otel_latency_ms",
        "_otel_preference_boost_count",
        "_otel_result_score",
        "_otel_search_total",
        "_otel_temporal_boost_count",
        "_otel_two_pass_execution_count",
        "_otel_two_pass_latency_ms",
        "_otel_zero_result_total",
        "_result_count_sum",
        "_score_count",
        "_score_max",
        "_score_min",
        "_score_sum",
        "_total_searches",
        "_total_sourced_hits",
        "_type_hits",
        "_type_searches",
        "_zero_result_count",
    )

    def __init__(self, latency_buffer_size: int = 1000) -> None:
        self._lock = threading.Lock()
        self._total_searches = 0
        self._zero_result_count = 0
        self._score_sum = 0.0
        self._score_count = 0
        self._score_min = float("inf")
        self._score_max = 0.0
        self._result_count_sum = 0
        self._latencies_ms: list[float] = []
        self._latency_max_stored = latency_buffer_size
        self._type_hits: dict[str, int] = defaultdict(int)
        self._type_searches: dict[str, int] = defaultdict(int)
        self._cross_session_hits = 0
        self._total_sourced_hits = 0

        self._otel_search_total: Counter | None = None
        self._otel_zero_result_total: Counter | None = None
        self._otel_latency_ms: Histogram | None = None
        self._otel_result_score: Histogram | None = None
        self._otel_assistant_reference_query_count: Counter | None = None
        self._otel_two_pass_execution_count: Counter | None = None
        self._otel_two_pass_latency_ms: Histogram | None = None
        self._otel_keyword_boost_count: Counter | None = None
        self._otel_temporal_boost_count: Counter | None = None
        self._otel_preference_boost_count: Counter | None = None
        self._init_otel_instruments()

    def _init_otel_instruments(self) -> None:
        """Lazily create OTEL instruments. NoOp when OTEL is not configured."""
        try:
            from myrm_agent_harness.infra.tracing.metrics.meter import get_meter

            meter = get_meter("myrm.memory.search")
            self._otel_search_total = meter.create_counter(
                "memory_search_total",
                description="Total memory searches performed",
            )
            self._otel_zero_result_total = meter.create_counter(
                "memory_search_zero_result_total",
                description="Memory searches that returned zero results",
            )
            self._otel_latency_ms = meter.create_histogram(
                "memory_search_latency_ms",
                unit="ms",
                description="Memory search latency distribution",
            )
            self._otel_result_score = meter.create_histogram(
                "memory_search_result_score",
                description="Memory search result score distribution",
            )
            self._otel_assistant_reference_query_count = meter.create_counter(
                "memory_assistant_reference_query_total",
                description="Total assistant-reference queries detected (MemPalace Two-Pass)",
            )
            self._otel_two_pass_execution_count = meter.create_counter(
                "memory_two_pass_execution_total",
                description="Total Two-Pass retrieval executions (MemPalace Two-Pass)",
            )
            self._otel_two_pass_latency_ms = meter.create_histogram(
                "memory_two_pass_latency_ms",
                unit="ms",
                description="Two-Pass retrieval latency distribution (MemPalace Two-Pass)",
            )
            self._otel_keyword_boost_count = meter.create_counter(
                "memory_keyword_boost_total",
                description="Total results boosted by keyword overlap (MemPalace ResultBooster)",
            )
            self._otel_temporal_boost_count = meter.create_counter(
                "memory_temporal_boost_total",
                description="Total results boosted by temporal proximity (MemPalace ResultBooster)",
            )
            self._otel_preference_boost_count = meter.create_counter(
                "memory_preference_boost_total",
                description="Total results boosted by preference strength (MemPalace ResultBooster)",
            )
        except Exception:
            logger.debug("OTEL instruments not available, metrics will be in-memory only")

    def _push_otel(
        self,
        result_count: int,
        scored_types: list[tuple[float, str]],
        latency_ms: float,
    ) -> None:
        """Push metrics to OTEL instruments. Called outside lock for minimal contention."""
        if self._otel_search_total is None:
            return
        try:
            self._otel_search_total.add(1)
            if result_count == 0:
                self._otel_zero_result_total.add(1)
            self._otel_latency_ms.record(latency_ms)
            for score, mem_type in scored_types:
                self._otel_result_score.record(score, attributes={"memory_type": mem_type})
        except Exception:
            pass

    @contextmanager
    def track_search(
        self,
        searched_types: list[MemoryType] | None = None,
        current_chat_id: str | None = None,
    ) -> Generator[_SearchTracker]:
        """Context manager that times a search and records results.

        Args:
            searched_types: Memory types included in this search
            current_chat_id: Active chat/session ID for cross-session hit tracking
        """
        tracker = _SearchTracker(self, searched_types or [], current_chat_id=current_chat_id)
        tracker.start()
        yield tracker
        tracker.finish()

    def _record(
        self,
        result_count: int,
        scored_types: list[tuple[float, str]],
        latency_ms: float,
        searched_types: list[MemoryType],
        hit_types: set[str],
        cross_session_hits: int = 0,
        total_sourced_hits: int = 0,
    ) -> None:
        with self._lock:
            self._total_searches += 1
            self._result_count_sum += result_count

            if result_count == 0:
                self._zero_result_count += 1

            for s, _ in scored_types:
                self._score_sum += s
                self._score_count += 1
                if s < self._score_min:
                    self._score_min = s
                if s > self._score_max:
                    self._score_max = s

            if len(self._latencies_ms) < self._latency_max_stored:
                self._latencies_ms.append(latency_ms)
            else:
                idx = self._total_searches % self._latency_max_stored
                self._latencies_ms[idx] = latency_ms

            for t in searched_types:
                self._type_searches[t.value] += 1
            for t in hit_types:
                self._type_hits[t] += 1

            self._cross_session_hits += cross_session_hits
            self._total_sourced_hits += total_sourced_hits

        self._push_otel(result_count, scored_types, latency_ms)

    def snapshot(self) -> SearchSnapshot:
        """Create an immutable snapshot of current metrics."""
        with self._lock:
            total = self._total_searches
            zero = self._zero_result_count
            zero_rate = zero / total if total > 0 else 0.0

            avg_score = self._score_sum / self._score_count if self._score_count > 0 else 0.0
            min_score = self._score_min if self._score_count > 0 else 0.0
            max_score = self._score_max

            avg_results = self._result_count_sum / total if total > 0 else 0.0

            latencies = sorted(self._latencies_ms) if self._latencies_ms else [0.0]
            avg_lat = sum(latencies) / len(latencies)
            p95_idx = int(len(latencies) * 0.95)
            p95_lat = latencies[min(p95_idx, len(latencies) - 1)]

            hit_rate: dict[str, float] = {}
            for type_name, search_count in self._type_searches.items():
                if search_count > 0:
                    hit_rate[type_name] = self._type_hits.get(type_name, 0) / search_count

            cs_hits = self._cross_session_hits
            sourced = self._total_sourced_hits
            cs_rate = cs_hits / sourced if sourced > 0 else 0.0

            return SearchSnapshot(
                total_searches=total,
                zero_result_count=zero,
                zero_result_rate=zero_rate,
                avg_score=round(avg_score, 4),
                min_score=round(min_score, 4),
                max_score=round(max_score, 4),
                avg_result_count=round(avg_results, 2),
                avg_latency_ms=round(avg_lat, 2),
                p95_latency_ms=round(p95_lat, 2),
                hit_rate_by_type=hit_rate,
                cross_session_hits=cs_hits,
                total_sourced_hits=sourced,
                cross_session_hit_rate=round(cs_rate, 4),
            )

    def reset(self) -> None:
        """Reset all counters (for testing)."""
        with self._lock:
            self._total_searches = 0
            self._zero_result_count = 0
            self._score_sum = 0.0
            self._score_count = 0
            self._score_min = float("inf")
            self._score_max = 0.0
            self._result_count_sum = 0
            self._latencies_ms.clear()
            self._type_hits.clear()
            self._type_searches.clear()
            self._cross_session_hits = 0
            self._total_sourced_hits = 0

    def record_assistant_reference_query(self) -> None:
        """Record assistant-reference query detection (MemPalace Two-Pass)."""
        if self._otel_assistant_reference_query_count:
            with suppress(Exception):
                self._otel_assistant_reference_query_count.add(1)

    def record_two_pass_execution(self, latency_ms: float) -> None:
        """Record Two-Pass retrieval execution (MemPalace Two-Pass)."""
        if self._otel_two_pass_execution_count:
            with suppress(Exception):
                self._otel_two_pass_execution_count.add(1)
        if self._otel_two_pass_latency_ms:
            with suppress(Exception):
                self._otel_two_pass_latency_ms.record(latency_ms)

    def record_keyword_boost(self, count: int) -> None:
        """Record keyword boost applications (MemPalace ResultBooster)."""
        if self._otel_keyword_boost_count and count > 0:
            with suppress(Exception):
                self._otel_keyword_boost_count.add(count)

    def record_temporal_boost(self, count: int) -> None:
        """Record temporal boost applications (MemPalace ResultBooster)."""
        if self._otel_temporal_boost_count and count > 0:
            with suppress(Exception):
                self._otel_temporal_boost_count.add(count)

    def record_preference_boost(self, count: int) -> None:
        """Record preference boost applications (MemPalace ResultBooster)."""
        if self._otel_preference_boost_count and count > 0:
            with suppress(Exception):
                self._otel_preference_boost_count.add(count)


class _SearchTracker:
    """Tracks a single search invocation's timing and results."""

    __slots__ = ("_current_chat_id", "_metrics", "_recorded", "_searched_types", "_start_ns")

    def __init__(
        self, metrics: SearchMetrics, searched_types: list[MemoryType], current_chat_id: str | None = None,
    ) -> None:
        self._metrics = metrics
        self._searched_types = searched_types
        self._current_chat_id = current_chat_id
        self._start_ns = 0
        self._recorded = False

    def start(self) -> None:
        self._start_ns = time.perf_counter_ns()

    def record(self, results: list[object]) -> None:
        """Record search results. Call this before the context manager exits.

        Args:
            results: List of MemorySearchResult objects
        """
        if self._recorded:
            return
        self._recorded = True

        elapsed_ms = (time.perf_counter_ns() - self._start_ns) / 1_000_000

        scored_types: list[tuple[float, str]] = []
        hit_types: set[str] = set()
        cross_session = 0
        total_sourced = 0
        for r in results:
            score = getattr(r, "score", 0.0)
            mem_type = getattr(r, "memory_type", None)
            type_str = str(mem_type) if mem_type is not None else "unknown"
            scored_types.append((score, type_str))
            if mem_type is not None:
                hit_types.add(type_str)
            if self._current_chat_id is not None:
                src = getattr(getattr(r, "memory", None), "source_chat_id", None)
                if src is not None:
                    total_sourced += 1
                    if src != self._current_chat_id:
                        cross_session += 1

        self._metrics._record(
            result_count=len(results),
            scored_types=scored_types,
            latency_ms=elapsed_ms,
            searched_types=self._searched_types,
            hit_types=hit_types,
            cross_session_hits=cross_session,
            total_sourced_hits=total_sourced,
        )

    def finish(self) -> None:
        if not self._recorded:
            self._metrics._record(
                result_count=0,
                scored_types=[],
                latency_ms=(time.perf_counter_ns() - self._start_ns) / 1_000_000,
                searched_types=self._searched_types,
                hit_types=set(),
            )


_global_metrics: SearchMetrics | None = None
_global_lock = threading.Lock()


def get_search_metrics() -> SearchMetrics:
    """Get or create the global SearchMetrics singleton."""
    global _global_metrics
    if _global_metrics is None:
        with _global_lock:
            if _global_metrics is None:
                _global_metrics = SearchMetrics()
    return _global_metrics


@dataclass
class StorageSnapshot:
    """Immutable snapshot of storage metrics."""

    total_collections: int
    total_documents: int
    total_size_bytes: int
    size_by_collection: dict[str, int]
    documents_by_collection: dict[str, int]
    user_storage_bytes: dict[str, int]
    alert_triggered: bool
    alert_threshold_bytes: int


class StorageMetrics:
    """Tracks memory storage size and usage.

    Monitors per-collection and per-user storage to detect bloat
    and trigger alerts when thresholds are exceeded.

    Usage:
        metrics = StorageMetrics(alert_threshold_gb=1.0)
        metrics.record_collection_size("semantic_text-ada-002", 50_000_000, 1000)
        metrics.record_user_storage("user_123", 120_000_000)

        snapshot = metrics.snapshot()
        if snapshot.alert_triggered:
            logger.warning("Storage alert: %s bytes exceeds threshold", snapshot.total_size_bytes)
    """

    __slots__ = (
        "_alert_threshold_bytes",
        "_alert_triggered",
        "_collection_counts",
        "_collection_sizes",
        "_lock",
        "_otel_document_count",
        "_otel_storage_bytes",
        "_user_storage",
    )

    def __init__(self, alert_threshold_gb: float = 1.0) -> None:
        """Initialize storage metrics.

        Args:
            alert_threshold_gb: Threshold in GB for storage alert (default 1GB).
        """
        self._lock = threading.Lock()
        self._alert_threshold_bytes = int(alert_threshold_gb * 1024 * 1024 * 1024)
        self._collection_sizes: dict[str, int] = {}
        self._collection_counts: dict[str, int] = {}
        self._user_storage: dict[str, int] = {}
        self._alert_triggered = False

        self._otel_storage_bytes: Histogram | None = None
        self._otel_document_count: Counter | None = None
        self._init_otel_instruments()

    def _init_otel_instruments(self) -> None:
        """Initialize OTEL instruments if meter provider is configured."""
        try:
            from opentelemetry.metrics import get_meter

            meter = get_meter("myrm.memory.storage")

            self._otel_storage_bytes = meter.create_histogram(
                "myrm.memory.storage.bytes",
                description="Memory storage size in bytes",
                unit="bytes",
            )
            self._otel_document_count = meter.create_counter(
                "myrm.memory.storage.documents",
                description="Total documents stored",
                unit="documents",
            )
        except Exception:
            pass

    def record_collection_size(self, collection: str, size_bytes: int, document_count: int) -> None:
        """Record storage size for a collection."""
        with self._lock:
            self._collection_sizes[collection] = size_bytes
            self._collection_counts[collection] = document_count

            total_size = sum(self._collection_sizes.values())
            if total_size > self._alert_threshold_bytes:
                if not self._alert_triggered:
                    logger.warning(
                        "Storage alert triggered: total size %.2f GB exceeds threshold %.2f GB",
                        total_size / (1024**3),
                        self._alert_threshold_bytes / (1024**3),
                    )
                    self._alert_triggered = True
            else:
                self._alert_triggered = False

            if self._otel_storage_bytes:
                self._otel_storage_bytes.record(size_bytes, {"collection": collection})
            if self._otel_document_count:
                self._otel_document_count.add(document_count, {"collection": collection})

    def record_user_storage(self, user_id: str, size_bytes: int) -> None:
        """Record total storage size for a user."""
        with self._lock:
            self._user_storage[user_id] = size_bytes

            if size_bytes > self._alert_threshold_bytes:
                logger.warning(
                    "User %s storage %.2f GB exceeds threshold %.2f GB",
                    user_id,
                    size_bytes / (1024**3),
                    self._alert_threshold_bytes / (1024**3),
                )

    def snapshot(self) -> StorageSnapshot:
        """Capture current storage metrics snapshot."""
        with self._lock:
            return StorageSnapshot(
                total_collections=len(self._collection_sizes),
                total_documents=sum(self._collection_counts.values()),
                total_size_bytes=sum(self._collection_sizes.values()),
                size_by_collection=dict(self._collection_sizes),
                documents_by_collection=dict(self._collection_counts),
                user_storage_bytes=dict(self._user_storage),
                alert_triggered=self._alert_triggered,
                alert_threshold_bytes=self._alert_threshold_bytes,
            )

    def reset(self) -> None:
        """Reset all storage metrics (for testing)."""
        with self._lock:
            self._collection_sizes.clear()
            self._collection_counts.clear()
            self._user_storage.clear()
            self._alert_triggered = False


_global_storage_metrics: StorageMetrics | None = None
_storage_lock = threading.Lock()


def get_storage_metrics() -> StorageMetrics:
    """Get or create the global StorageMetrics singleton."""
    global _global_storage_metrics
    if _global_storage_metrics is None:
        with _storage_lock:
            if _global_storage_metrics is None:
                _global_storage_metrics = StorageMetrics()
    return _global_storage_metrics
