"""Metrics utilities for Myrm Agent Harness.

Provides通用metrics工具函数和预定义监控指标，自动添加myrm_前缀，验证命名规范。

[INPUT]
- (none — pure utility module)

[OUTPUT]
- create_counter — 创建Counter metric
- create_gauge — 创建Gauge metric
- create_histogram — 创建Histogram metric

Submodules:
- agent_metrics — Agent execution monitoring (run count, errors, duration)
- goal_metrics — Goal lifecycle monitoring (created, completed, budget_limited, duration, tokens, cost)
- llm_metrics — LLM calling monitoring (call count, token usage, errors, duration)
- circuit_breaker_metrics — Circuit breaker state and failure monitoring
- db_pool_collector — Database connection pool metrics collector
- security_metrics — Security policy denial and action monitoring

[POS]
Harness-layer generic metrics utilities for any project using the Myrm framework.

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

try:
    from prometheus_client import Counter, Gauge, Histogram

    PROMETHEUS_AVAILABLE = True
except (ImportError, TypeError):
    PROMETHEUS_AVAILABLE = False
    Counter = Any  # type: ignore
    Gauge = Any  # type: ignore
    Histogram = Any  # type: ignore

if TYPE_CHECKING:
    from prometheus_client import Counter as Counter
    from prometheus_client import Gauge as Gauge
    from prometheus_client import Histogram as Histogram

import logging

logger = logging.getLogger(__name__)

__all__ = [
    "circuit_breaker_failures_total",
    "circuit_breaker_state",
    "create_counter",
    "create_gauge",
    "create_histogram",
    "get_or_create_counter",
    "get_or_create_histogram",
]


def _require_prometheus(name: str) -> None:
    if not PROMETHEUS_AVAILABLE:
        raise RuntimeError(f"prometheus_client is required for {name}. Install with: uv add prometheus_client")


def create_counter(
    name: str,
    description: str,
    labelnames: tuple[str, ...] = (),
) -> Counter:
    """Create a Counter metric with myrm_ prefix.

    Args:
        name: Metric name (without myrm_ prefix, must end with _total)
        description: Human-readable description
        labelnames: Label names (keep cardinality low)

    Returns:
        Counter instance with myrm_ prefix

    Raises:
        ValueError: If name doesn't end with _total or contains invalid characters

    Example:
        >>> counter = create_counter(
        ...     "agent_run_total",
        ...     "Total number of agent runs",
        ...     ("agent_type",)
        ... )
        >>> counter.labels(agent_type="skill").inc()
    """
    if not PROMETHEUS_AVAILABLE:
        logger.debug("prometheus_client not installed, counter '%s' creation skipped", name)
        return None  # type: ignore[return-value]

    if not name.endswith("_total"):
        raise ValueError(f"Counter name must end with '_total', got: {name}. Did you mean '{name}_total'?")

    full_name = f"myrm_{name}"
    return Counter(full_name, description, labelnames)


def create_gauge(
    name: str,
    description: str,
    labelnames: tuple[str, ...] = (),
) -> Gauge:
    """Create a Gauge metric with myrm_ prefix.

    Args:
        name: Metric name (without myrm_ prefix)
        description: Human-readable description
        labelnames: Label names (keep cardinality low)

    Returns:
        Gauge instance with myrm_ prefix

    Example:
        >>> gauge = create_gauge(
        ...     "db_pool_checked_out",
        ...     "Currently checked-out database connections",
        ...     ("engine",)
        ... )
        >>> gauge.labels(engine="async").set(5)
    """
    if not PROMETHEUS_AVAILABLE:
        logger.debug("prometheus_client not installed, gauge '%s' creation skipped", name)
        return None  # type: ignore[return-value]

    full_name = f"myrm_{name}"
    return Gauge(full_name, description, labelnames)


def create_histogram(
    name: str,
    description: str,
    labelnames: tuple[str, ...] = (),
    buckets: tuple[float, ...] = (),
) -> Histogram:
    """Create a Histogram metric with myrm_ prefix.

    Args:
        name: Metric name (without myrm_ prefix, should end with _seconds or _bytes)
        description: Human-readable description
        labelnames: Label names (keep cardinality low)
        buckets: Histogram buckets (uses prometheus defaults if empty)

    Returns:
        Histogram instance with myrm_ prefix

    Example:
        >>> hist = create_histogram(
        ...     "agent_run_duration_seconds",
        ...     "Agent run duration in seconds",
        ...     ("agent_type",)
        ... )
        >>> with hist.labels(agent_type="skill").time():
        ...     # agent execution
        ...     pass
    """
    if not PROMETHEUS_AVAILABLE:
        logger.debug("prometheus_client not installed, histogram '%s' creation skipped", name)
        return None  # type: ignore[return-value]

    valid_suffixes = ("_seconds", "_bytes", "_total", "_ratio")
    if not any(name.endswith(s) for s in valid_suffixes):
        import warnings

        warnings.warn(
            f"Histogram name should end with one of {valid_suffixes}, got: {name}. "
            f"Consider renaming to '{name}_seconds' for durations or '{name}_bytes' for sizes.",
            UserWarning,
            stacklevel=2,
        )

    full_name = f"myrm_{name}"
    if buckets:
        return Histogram(full_name, description, labelnames, buckets=buckets)
    return Histogram(full_name, description, labelnames)


class _NoOpLabeled:
    def inc(self, amount: float = 1) -> None:
        pass

    def observe(self, amount: float) -> None:
        pass


class _NoOpMetric:
    def labels(self, **kwargs: object) -> _NoOpLabeled:
        return _NoOpLabeled()


def get_or_create_counter(
    name: str,
    documentation: str,
    labelnames: tuple[str, ...] = (),
) -> Counter | _NoOpMetric:
    """Return an existing Prometheus counter or create one (idempotent by name)."""
    if not PROMETHEUS_AVAILABLE:
        return _NoOpMetric()
    from prometheus_client import REGISTRY

    existing = REGISTRY._names_to_collectors.get(name)
    if existing is not None:
        return existing  # type: ignore[return-value]
    return Counter(name, documentation, labelnames)


def get_or_create_histogram(
    name: str,
    documentation: str,
    *,
    labelnames: tuple[str, ...] = (),
    buckets: tuple[float, ...] | None = None,
) -> Histogram | _NoOpMetric:
    """Return an existing Prometheus histogram or create one (idempotent by name)."""
    if not PROMETHEUS_AVAILABLE:
        return _NoOpMetric()
    from prometheus_client import REGISTRY

    existing = REGISTRY._names_to_collectors.get(name)
    if existing is not None:
        return existing  # type: ignore[return-value]
    if buckets is not None:
        return Histogram(name, documentation, labelnames, buckets=buckets)
    return Histogram(name, documentation, labelnames)
