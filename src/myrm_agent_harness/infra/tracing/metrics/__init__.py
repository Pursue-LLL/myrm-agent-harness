"""Metrics collection and export for OpenTelemetry.

Provides unified API for metrics collection and export to various backends.

[INPUT]
- opentelemetry.metrics (POS: Metrics API)
- opentelemetry.sdk.metrics (POS: Metrics SDK)

[OUTPUT]
- setup_metrics: 初始化 Metrics 导出
- get_meter: 获取 Meter 实例
- MetricsExporter: 导出器接口
- get_metrics_collector: 获取 MetricsCollector 单例

[POS]
Metrics export module. Supports Prometheus, OTLP, Console, and other exporters.

"""

from .cardinality import DynamicLabelManager, sanitize_metric_labels
from .collector import MetricsCollector, get_metrics_collector
from .exporter import (
    MetricsExporter,
    force_flush_metrics,
    get_meter_provider,
    is_metrics_initialized,
    setup_metrics,
    shutdown_metrics,
)
from .meter import get_meter

__all__ = [
    "DynamicLabelManager",
    "MetricsCollector",
    "MetricsExporter",
    "force_flush_metrics",
    "get_meter",
    "get_meter_provider",
    "get_metrics_collector",
    "is_metrics_initialized",
    "sanitize_metric_labels",
    "setup_metrics",
    "shutdown_metrics",
]
