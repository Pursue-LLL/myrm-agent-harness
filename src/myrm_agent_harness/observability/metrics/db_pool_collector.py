"""Database Pool Metrics collector for SQLAlchemy.

Provides通用的数据库连接池监控collector，适用于任何使用SQLAlchemy的项目。

[INPUT]

[OUTPUT]
- DatabasePoolCollector — Prometheus自定义collector

[POS]
Harness-layer generic database connection pool monitor reusable by any Myrm-based project.

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

try:
    from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily
    from prometheus_client.registry import Collector

    HAS_PROMETHEUS = True
except (ImportError, TypeError):
    HAS_PROMETHEUS = False
    Collector = object  # type: ignore
    CounterMetricFamily = Any  # type: ignore
    GaugeMetricFamily = Any  # type: ignore

if TYPE_CHECKING:
    from collections.abc import Generator

    from sqlalchemy.engine import Engine


class DatabasePoolCollector(Collector):
    """Custom Prometheus collector for SQLAlchemy connection pool metrics.

    Monitors connection pool state for sync/async/readonly engines.

    Metrics:
        - myrm_db_pool_checked_out: Currently checked-out connections
        - myrm_db_pool_checked_in: Idle connections available in pool
        - myrm_db_pool_overflow: Current overflow connections beyond pool_size
        - myrm_db_pool_size: Configured pool size (constant)

    Example:
        >>> from sqlalchemy import create_engine
        >>> from prometheus_client import CollectorRegistry
        >>>
        >>> engine = create_engine("postgresql://...")
        >>> registry = CollectorRegistry()
        >>> collector = DatabasePoolCollector(engine, "async")
        >>> registry.register(collector)
    """

    def __init__(self, engine: Engine, engine_name: str) -> None:
        """Initialize Database Pool collector.

        Args:
            engine: SQLAlchemy Engine instance
            engine_name: Engine label (e.g., "sync", "async", "readonly")
        """
        self.engine = engine
        self.engine_name = engine_name

    def collect(self) -> Generator[GaugeMetricFamily | CounterMetricFamily]:
        """Collect connection pool metrics.

        Called by Prometheus on each scrape.

        Yields:
            Prometheus metric families
        """
        if not HAS_PROMETHEUS:
            return

        pool = self.engine.pool

        checked_out_metric = GaugeMetricFamily(
            "myrm_db_pool_checked_out",
            "Currently checked-out connections",
            labels=["engine"],
        )
        checked_out_metric.add_metric([self.engine_name], pool.checkedout())
        yield checked_out_metric

        checked_in_metric = GaugeMetricFamily(
            "myrm_db_pool_checked_in",
            "Idle connections available in pool",
            labels=["engine"],
        )
        checked_in_metric.add_metric([self.engine_name], pool.checkedin())
        yield checked_in_metric

        overflow_metric = GaugeMetricFamily(
            "myrm_db_pool_overflow",
            "Current overflow connections beyond pool_size",
            labels=["engine"],
        )
        overflow_metric.add_metric([self.engine_name], pool.overflow())
        yield overflow_metric

        size_metric = GaugeMetricFamily(
            "myrm_db_pool_size",
            "Configured pool size (constant)",
            labels=["engine"],
        )
        size_metric.add_metric([self.engine_name], pool.size())
        yield size_metric
