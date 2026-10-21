"""Router data models and concurrency primitives.

Contains:
- Data classes: FetcherDecision, DomainStats, PersistentRule, ResourceCost, HeapEntry, DomainMetrics
- Concurrency primitives: RWLock (read-write lock)

[INPUT]
- (none)

[OUTPUT]
- RWLock: Async read-write lock allowing multiple concurrent readers.
- FetcherDecision: Routing decision result
- DomainStats: Domainstatistics
- PersistentRule: Persistent rule (with access time tracking)
- ResourceCost: Multi-dimensional resource cost

[POS]
Router data models and concurrency primitives.
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from ..fetchers.protocols import FetcherType


class RWLock:
    """Read-write lock: allows concurrent readers, exclusive writers.

    Implementation strategy:
    - Read operations can be concurrent（select, get_stats）
    - Write operations are exclusive（report_result, shutdown）
    - Simple fair strategy, no starvation risk
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._readers = 0
        self._writer = False
        self._read_ready = threading.Condition(self._lock)
        self._write_ready = threading.Condition(self._lock)

    @contextlib.contextmanager
    def read_lock(self):
        """Read lock context manager"""
        self._acquire_read()
        try:
            yield
        finally:
            self._release_read()

    @contextlib.contextmanager
    def write_lock(self):
        """Write lock context manager"""
        self._acquire_write()
        try:
            yield
        finally:
            self._release_write()

    def _acquire_read(self) -> None:
        with self._lock:
            while self._writer:
                self._read_ready.wait()
            self._readers += 1

    def _release_read(self) -> None:
        with self._lock:
            self._readers -= 1
            if self._readers == 0:
                self._write_ready.notify()

    def _acquire_write(self) -> None:
        with self._lock:
            while self._writer or self._readers > 0:
                self._write_ready.wait()
            self._writer = True

    def _release_write(self) -> None:
        with self._lock:
            self._writer = False
            self._write_ready.notify()
            self._read_ready.notify_all()


@dataclass
class FetcherDecision:
    """Routing decision result

    Private fields for deferred stats update (avoid writes under read lock)：
    - _hit_type: "persistent" | "learning" | "default"
    - _explored: Whether exploration occurred
    - _cost_optimized: Whether cost optimization occurred
    """

    fetcher_type: FetcherType
    reason: str
    _hit_type: str | None = field(default=None, repr=False, compare=False)
    _explored: bool = field(default=False, repr=False, compare=False)
    _cost_optimized: bool = field(default=False, repr=False, compare=False)


@dataclass
class DomainStats:
    """Domainstatistics"""

    fetcher_type: FetcherType
    total_attempts: int
    successful_attempts: int
    last_access_time: float


@dataclass
class PersistentRule:
    """Persistent rule (with access time tracking)"""

    fetcher_type: FetcherType
    last_access_time: float

    def to_dict(self) -> dict[str, str | float]:
        """Serialize to JSON-storable dict"""
        return {"fetcher_type": self.fetcher_type.name, "last_access_time": self.last_access_time}

    @classmethod
    def from_dict(cls, data: dict[str, str | float]) -> PersistentRule:
        """Deserialize from dict"""
        return cls(fetcher_type=FetcherType[data["fetcher_type"]], last_access_time=float(data["last_access_time"]))


@dataclass
class ResourceCost:
    """Multi-dimensional resource cost"""

    latency_ms: float = 0.0
    cpu_percent: float = 0.0
    memory_mb: float = 0.0


class HeapEntry:
    """Heap entry (for LRU eviction)"""

    __slots__ = ("domain", "timestamp")

    def __init__(self, timestamp: float, domain: str):
        self.timestamp = timestamp
        self.domain = domain

    def __lt__(self, other: HeapEntry) -> bool:
        return self.timestamp < other.timestamp


@dataclass
class DomainMetrics:
    """Unified domain learning metrics

    Responsibility: aggregate domain-level learning data from web_fetch and browser

    Core data:
    - fetcher_latencies: Per-fetcher latency history (all requests)
    - fetcher_success_latencies: Per-fetcher success latency history (for cost estimation)
    - fetcher_success_counts: Per-fetcher success count (exact)
    - fetcher_total_counts: Per-fetcher total count (exact)
    - wait_strategy_latencies: Per-wait-strategy latency history (domain-level)
    - networkidle_success_count: networkidle Success count
    - networkidle_fail_count: networkidle Failure count
    - failure_timestamps: Per-fetcher failure timestamps (for time decay)
    - total_accesses: Total access count (for adaptive exploration rate)
    - last_access: Last access time

    Storage locations:
    - Local deployment: ~/.myrm/domain_metrics.json
    - Per-user cloud sandbox: /workspace/.myrm/domain_metrics.json
    - Per-task cloud sandbox: /tmp/domain_metrics.json (isolated) or /mnt/shared/ (shared)

    Concurrency safety:
    - Internally uses threading.Lock to protect all mutations
    - File-level uses fcntl.flock (cloud sandbox multi-process)
    """

    domain: str
    fetcher_latencies: dict[FetcherType, deque[float]] = field(default_factory=dict)
    fetcher_success_latencies: dict[FetcherType, deque[float]] = field(default_factory=dict)
    fetcher_success_counts: dict[FetcherType, int] = field(default_factory=dict)
    fetcher_total_counts: dict[FetcherType, int] = field(default_factory=dict)
    wait_strategy_latencies: dict[str, deque[float]] = field(default_factory=dict)
    networkidle_success_count: int = 0
    networkidle_fail_count: int = 0
    failure_timestamps: dict[FetcherType, deque[float]] = field(default_factory=dict)
    total_accesses: int = 0
    last_access: float = field(default_factory=time.time)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Initialize default dicts and queues"""
        if not hasattr(self, "_lock"):
            self._lock = threading.Lock()

        if not hasattr(self, "fetcher_latencies") or self.fetcher_latencies is None:
            self.fetcher_latencies = {}
        if not hasattr(self, "fetcher_success_latencies") or self.fetcher_success_latencies is None:
            self.fetcher_success_latencies = {}
        if not hasattr(self, "fetcher_success_counts") or self.fetcher_success_counts is None:
            self.fetcher_success_counts = {}
        if not hasattr(self, "fetcher_total_counts") or self.fetcher_total_counts is None:
            self.fetcher_total_counts = {}
        if not hasattr(self, "failure_timestamps") or self.failure_timestamps is None:
            self.failure_timestamps = {}

        for ft in FetcherType:
            if ft not in self.fetcher_latencies:
                self.fetcher_latencies[ft] = deque(maxlen=200)
            if ft not in self.fetcher_success_latencies:
                self.fetcher_success_latencies[ft] = deque(maxlen=200)
            if ft not in self.fetcher_success_counts:
                self.fetcher_success_counts[ft] = 0
            if ft not in self.fetcher_total_counts:
                self.fetcher_total_counts[ft] = 0
            if ft not in self.failure_timestamps:
                self.failure_timestamps[ft] = deque(maxlen=100)

    def __getstate__(self) -> dict[str, object]:
        """Custom serialization (excludes lock objects)"""
        state = self.__dict__.copy()
        state.pop("_lock", None)
        return state

    def __setstate__(self, state: dict[str, object]) -> None:
        """Custom deserialization (rebuilds lock objects)"""
        self.__dict__.update(state)
        self._lock = threading.Lock()

    def to_dict(self) -> dict[str, object]:
        """Serialize to JSON-storable dict"""
        return {
            "domain": self.domain,
            "fetcher_latencies": {ft.name: list(dq) for ft, dq in self.fetcher_latencies.items()},
            "fetcher_success_latencies": {ft.name: list(dq) for ft, dq in self.fetcher_success_latencies.items()},
            "fetcher_success_counts": {ft.name: count for ft, count in self.fetcher_success_counts.items()},
            "fetcher_total_counts": {ft.name: count for ft, count in self.fetcher_total_counts.items()},
            "wait_strategy_latencies": {strategy: list(dq) for strategy, dq in self.wait_strategy_latencies.items()},
            "networkidle_success_count": self.networkidle_success_count,
            "networkidle_fail_count": self.networkidle_fail_count,
            "failure_timestamps": {ft.name: list(dq) for ft, dq in self.failure_timestamps.items()},
            "total_accesses": self.total_accesses,
            "last_access": self.last_access,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> DomainMetrics:
        """Deserialize from dict"""
        metrics = cls(domain=data["domain"])
        metrics.fetcher_latencies = {
            FetcherType[ft_name]: deque(latencies, maxlen=200)
            for ft_name, latencies in data.get("fetcher_latencies", {}).items()
        }
        metrics.fetcher_success_latencies = {
            FetcherType[ft_name]: deque(latencies, maxlen=200)
            for ft_name, latencies in data.get("fetcher_success_latencies", {}).items()
        }
        metrics.fetcher_success_counts = {
            FetcherType[ft_name]: count for ft_name, count in data.get("fetcher_success_counts", {}).items()
        }
        metrics.fetcher_total_counts = {
            FetcherType[ft_name]: count for ft_name, count in data.get("fetcher_total_counts", {}).items()
        }
        metrics.wait_strategy_latencies = {
            strategy: deque(latencies, maxlen=200)
            for strategy, latencies in data.get("wait_strategy_latencies", {}).items()
        }
        metrics.networkidle_success_count = data.get("networkidle_success_count", 0)
        metrics.networkidle_fail_count = data.get("networkidle_fail_count", 0)
        metrics.failure_timestamps = {
            FetcherType[ft_name]: deque(timestamps, maxlen=100)
            for ft_name, timestamps in data.get("failure_timestamps", {}).items()
        }
        metrics.total_accesses = data.get("total_accesses", 0)
        metrics.last_access = data.get("last_access", time.time())
        return metrics

    def record_fetcher_result(
        self,
        fetcher_type: FetcherType,
        success: bool,
        latency_ms: float | None = None,
    ) -> None:
        """Record fetcher result (thread-safe)"""
        with self._lock:
            self.total_accesses += 1
            self.last_access = time.time()

            self.fetcher_total_counts[fetcher_type] += 1
            if success:
                self.fetcher_success_counts[fetcher_type] += 1

            if latency_ms is not None and latency_ms > 0:
                self.fetcher_latencies[fetcher_type].append(latency_ms)
                if success:
                    self.fetcher_success_latencies[fetcher_type].append(latency_ms)

            if not success:
                self.failure_timestamps[fetcher_type].append(time.time())

    def get_success_rate(self, fetcher_type: FetcherType) -> float:
        """Get exact fetcher success rate (based on historical counts, thread-safe)"""
        with self._lock:
            total = self.fetcher_total_counts.get(fetcher_type, 0)
            if total == 0:
                return 0.8

            success = self.fetcher_success_counts.get(fetcher_type, 0)
            return success / total

    def record_wait_strategy(self, strategy: str, elapsed_ms: int) -> None:
        """Record wait strategy latency (thread-safe)"""
        with self._lock:
            if strategy not in self.wait_strategy_latencies:
                self.wait_strategy_latencies[strategy] = deque(maxlen=200)
            self.wait_strategy_latencies[strategy].append(float(elapsed_ms))

    def record_networkidle_result(self, success: bool) -> None:
        """Record networkidle detection result (thread-safe)"""
        with self._lock:
            if success:
                self.networkidle_success_count += 1
            else:
                self.networkidle_fail_count += 1

    def get_recent_failures_count(self, fetcher_type: FetcherType, window_hours: int = 24) -> int:
        """Get failure count within time window (time-decayed, thread-safe)"""
        with self._lock:
            now = time.time()
            cutoff = now - window_hours * 3600
            return sum(1 for ts in self.failure_timestamps[fetcher_type] if ts >= cutoff)

    def get_average_latency(self, fetcher_type: FetcherType) -> float | None:
        """Get average fetcher latency (all requests, thread-safe)"""
        with self._lock:
            latencies = self.fetcher_latencies.get(fetcher_type)
            if not latencies or len(latencies) == 0:
                return None
            return sum(latencies) / len(latencies)

    def get_average_success_latency(self, fetcher_type: FetcherType) -> float | None:
        """Get average fetcher success latency (success only, for cost estimation, thread-safe)"""
        with self._lock:
            latencies = self.fetcher_success_latencies.get(fetcher_type)
            if not latencies or len(latencies) == 0:
                return None
            return sum(latencies) / len(latencies)

    def get_smart_fast_timeout(self) -> int | None:
        """Compute SMART strategy fast_timeout_ms from historical data (thread-safe)

        Strategy:
        - Sample count < 20: return None (use default)
        - networkidle success rate < 50%: return None (skip fast path)
        - Otherwise return P95 latency * 1.2 (capped at 500ms)
        """
        with self._lock:
            total = self.networkidle_success_count + self.networkidle_fail_count
            if total < 20:
                return None

            success_rate = self.networkidle_success_count / total
            if success_rate < 0.5:
                return None

            latencies = self.wait_strategy_latencies.get("networkidle")
            if not latencies or len(latencies) < 20:
                return None

            sorted_latencies = sorted(latencies)
            p95_idx = int(len(sorted_latencies) * 0.95)
            p95_latency = sorted_latencies[p95_idx]

            return min(int(p95_latency * 1.2), 500)
