"""Metrics collector for simplified metrics recording.

Provides a high-level API for recording metrics with automatic labeling.

[INPUT]
- opentelemetry.metrics (POS: Metrics API)

[OUTPUT]
- MetricsCollector: Unified metrics recording interface
- get_metrics_collector: Get singleton collector instance

[POS]
Simplified metrics collection with automatic trace_id labeling.
"""

from __future__ import annotations

from opentelemetry.metrics import Meter

from .meter import get_meter


class MetricsCollector:
    """Simplified metrics collector with unified API.

    Provides counter, gauge, and histogram recording with automatic labeling.
    """

    def __init__(self, meter: Meter) -> None:
        self._meter = meter
        self._counters: dict[str, object] = {}
        self._histograms: dict[str, object] = {}
        self._gauges: dict[str, object] = {}

    def counter(self, name: str, value: int | float, labels: dict[str, str] | None = None) -> None:
        """Record counter metric.

        Args:
            name: Metric name
            value: Counter value
            labels: Optional labels
        """
        if name not in self._counters:
            self._counters[name] = self._meter.create_counter(name)

        counter = self._counters[name]
        counter.add(value, attributes=labels or {})  # type: ignore[attr-defined]

    def gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        """Record gauge metric (absolute value, not cumulative).

        Args:
            name: Metric name
            value: Gauge value (absolute, not delta)
            labels: Optional labels
        """
        if name not in self._gauges:
            self._gauges[name] = self._meter.create_gauge(name)

        gauge = self._gauges[name]
        gauge.record(value, attributes=labels or {})  # type: ignore[attr-defined]

    def histogram(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        """Record histogram metric.

        Args:
            name: Metric name
            value: Histogram value
            labels: Optional labels
        """
        if name not in self._histograms:
            self._histograms[name] = self._meter.create_histogram(name)

        histogram = self._histograms[name]
        histogram.record(value, attributes=labels or {})  # type: ignore[attr-defined]


_collector: MetricsCollector | None = None


def get_metrics_collector() -> MetricsCollector:
    """Get singleton MetricsCollector instance.

    Returns:
        MetricsCollector instance
    """
    global _collector
    if _collector is None:
        meter = get_meter("myrm.streaming")
        _collector = MetricsCollector(meter)
    return _collector
