"""Multi-dimensional cost learning module.

Responsibilities:
- Estimate fetcher resource cost (latency + CPU + memory).
- Progressive learning (seed cost -> weighted blend -> fully trusted).
- Compute expected cost (normalized + multi-dimensional weighting + success-rate adjustment).
- Domain-level cost learning (prefer domain-level data, fall back to global data).

[INPUT]
- (none)

[OUTPUT]
- CostLearner: Multi-dimensional cost learner.

[POS]
Multi-dimensional cost learning module.
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, ClassVar

from ..fetchers.protocols import FetcherType
from .models import ResourceCost

if TYPE_CHECKING:
    from .domain_metrics import DomainMetricsManager
    from .models import DomainStats


class CostLearner:
    """Multi-dimensional cost learner.

    Core capabilities:
    - Three-dimensional cost: latency (ms) + CPU (%) + memory (MB).
    - Normalization: latency / 1000 (s), CPU / 100 (ratio), memory / 1000 (GB).
    - Progressive learning: <10 samples use seed cost, 10-99 weighted blend, >=100 fully measured.
    - Configurable weights: latency_weight, cpu_weight, memory_weight.
    - Domain-level learning: prefer domain-level data (DomainMetrics), fall back to global data.
    """

    SEED_COSTS: ClassVar[dict[FetcherType, ResourceCost]] = {
        FetcherType.HTTP: ResourceCost(latency_ms=100.0, cpu_percent=2.0, memory_mb=10.0),
        FetcherType.BROWSER: ResourceCost(latency_ms=1500.0, cpu_percent=15.0, memory_mb=200.0),
        FetcherType.STEALTH: ResourceCost(latency_ms=3500.0, cpu_percent=25.0, memory_mb=300.0),
    }

    MIN_SAMPLES_FOR_LEARNING = 10
    MIN_SAMPLES_FOR_FULL_TRUST = 100

    def __init__(
        self,
        *,
        latency_weight: float = 1.0,
        cpu_weight: float = 0.3,
        memory_weight: float = 0.2,
        domain_metrics_manager: DomainMetricsManager | None = None,
    ):
        self._latency_weight = latency_weight
        self._cpu_weight = cpu_weight
        self._memory_weight = memory_weight
        self._domain_metrics_manager = domain_metrics_manager

        self._latency_history: dict[FetcherType, deque[float]] = {ft: deque(maxlen=1000) for ft in FetcherType}
        self._cpu_history: dict[FetcherType, deque[float]] = {ft: deque(maxlen=1000) for ft in FetcherType}
        self._memory_history: dict[FetcherType, deque[float]] = {ft: deque(maxlen=1000) for ft in FetcherType}

    def record_cost(
        self,
        fetcher_type: FetcherType,
        latency_ms: float | None = None,
        cpu_percent: float | None = None,
        memory_mb: float | None = None,
        domain: str | None = None,
    ) -> None:
        """Record measured cost (global + domain-level).

        Args:
            fetcher_type: Fetcher type.
            latency_ms: Latency in milliseconds.
            cpu_percent: CPU usage percentage.
            memory_mb: Memory usage in MB.
            domain: Domain name (for domain-level learning).
        """
        if latency_ms is not None and latency_ms > 0:
            self._latency_history[fetcher_type].append(latency_ms)

            if domain and self._domain_metrics_manager:
                metrics = self._domain_metrics_manager.get_or_create(domain)
                metrics.fetcher_latencies[fetcher_type].append(latency_ms)

        if cpu_percent is not None and cpu_percent > 0:
            self._cpu_history[fetcher_type].append(cpu_percent)

        if memory_mb is not None and memory_mb > 0:
            self._memory_history[fetcher_type].append(memory_mb)

    def estimate_cost(self, fetcher_type: FetcherType, domain: str | None = None) -> ResourceCost:
        """Estimate multi-dimensional resource cost (latency + CPU + memory).

        Progressive learning strategy:
        - <10 samples: seed cost.
        - 10-99 samples: weighted average (seed * (1-n/100) + measured * n/100).
        - >=100 samples: fully measured data.

        Data source selection:
        - Latency: prefer domain-level success latency (DomainMetrics.fetcher_success_latencies), fall back to global.
        - CPU / memory: global data (not domain-specific).
        """
        seed = self.SEED_COSTS[fetcher_type]

        latency_hist = None
        if domain and self._domain_metrics_manager:
            metrics = self._domain_metrics_manager.get(domain)
            if metrics:
                latency_hist = metrics.fetcher_success_latencies.get(fetcher_type)
                if not latency_hist or len(latency_hist) == 0:
                    latency_hist = metrics.fetcher_latencies.get(fetcher_type)

        if not latency_hist or len(latency_hist) == 0:
            latency_hist = self._latency_history[fetcher_type]

        cpu_hist = self._cpu_history[fetcher_type]
        memory_hist = self._memory_history[fetcher_type]
        n = len(latency_hist)

        if n < self.MIN_SAMPLES_FOR_LEARNING:
            return seed

        measured_latency = sum(latency_hist) / n
        measured_cpu = sum(cpu_hist) / len(cpu_hist) if cpu_hist else seed.cpu_percent
        measured_memory = sum(memory_hist) / len(memory_hist) if memory_hist else seed.memory_mb

        if n < self.MIN_SAMPLES_FOR_FULL_TRUST:
            weight = n / self.MIN_SAMPLES_FOR_FULL_TRUST
            return ResourceCost(
                latency_ms=seed.latency_ms * (1 - weight) + measured_latency * weight,
                cpu_percent=seed.cpu_percent * (1 - weight) + measured_cpu * weight,
                memory_mb=seed.memory_mb * (1 - weight) + measured_memory * weight,
            )

        return ResourceCost(
            latency_ms=measured_latency,
            cpu_percent=measured_cpu,
            memory_mb=measured_memory,
        )

    def calculate_expected_cost(
        self,
        domain: str,
        fetcher_type: FetcherType,
        learning_cache: dict[str, DomainStats],
    ) -> float:
        """Compute期望成本（多Dimension加权 + Success率调整）

        归一化Strategy:
        - latency: ms → s（÷1000）
        - cpu: % → ratio（÷100）
        - memory: MB → GB（÷1000）
        使三个Dimension量纲统一，权重Configure生效

        Success率Data源（优先级）：
        1. DomainMetrics（Domain级exact计数）
        2. learning_cache（短期Statistics）
        3. default value 0.8
        """
        success_rate = 0.8
        if self._domain_metrics_manager:
            metrics = self._domain_metrics_manager.get(domain)
            if metrics:
                success_rate = metrics.get_success_rate(fetcher_type)
        elif domain in learning_cache:
            stats = learning_cache[domain]
            success_rate = stats.successful_attempts / stats.total_attempts if stats.total_attempts > 0 else 0.8

        resource_cost = self.estimate_cost(fetcher_type, domain=domain)

        normalized_latency = resource_cost.latency_ms / 1000.0
        normalized_cpu = resource_cost.cpu_percent / 100.0
        normalized_memory = resource_cost.memory_mb / 1000.0

        weighted_cost = (
            normalized_latency * self._latency_weight
            + normalized_cpu * self._cpu_weight
            + normalized_memory * self._memory_weight
        )

        if success_rate < 0.01:
            return weighted_cost * 100.0

        return weighted_cost / success_rate

    def get_cost_stats(self) -> dict[str, dict[str, float]]:
        """Get成本Statisticsinformation"""
        return {
            ft.name: {
                "samples": len(self._latency_history[ft]),
                "avg_latency_ms": sum(self._latency_history[ft]) / len(self._latency_history[ft])
                if self._latency_history[ft]
                else self.SEED_COSTS[ft].latency_ms,
                "avg_cpu_percent": sum(self._cpu_history[ft]) / len(self._cpu_history[ft])
                if self._cpu_history[ft]
                else self.SEED_COSTS[ft].cpu_percent,
                "avg_memory_mb": sum(self._memory_history[ft]) / len(self._memory_history[ft])
                if self._memory_history[ft]
                else self.SEED_COSTS[ft].memory_mb,
            }
            for ft in FetcherType
        }
