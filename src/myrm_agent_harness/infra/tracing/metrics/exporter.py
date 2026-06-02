"""Metrics exporter configuration and setup.

Supports export backends: OTLP (push), Console (development).
For Prometheus, business layer should use PrometheusMetricReader directly.

Design Principles:
- Framework provides OpenTelemetry integration (vendor-neutral)
- Business layer decides export strategy (push to OTLP / expose HTTP endpoint)
- No HTTP server startup in framework layer

[INPUT]
- opentelemetry.sdk.metrics (POS: Metrics SDK)
- opentelemetry.exporter.otlp.proto.grpc (POS: OTLP 导出)

[OUTPUT]
- MetricsExporter: 导出器类型枚举
- setup_metrics: 初始化函数

[POS]
Metrics exporter configuration. Provides Console and OTLP export without the HTTP server overhead of Prometheus.

"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any

from opentelemetry.metrics import set_meter_provider

try:
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import (
        ConsoleMetricExporter,
        PeriodicExportingMetricReader,
    )
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource

    HAS_OTEL_SDK = True
except (ImportError, TypeError):
    HAS_OTEL_SDK = False
    MeterProvider = Any  # type: ignore
    ConsoleMetricExporter = Any  # type: ignore
    PeriodicExportingMetricReader = Any  # type: ignore
    Resource = Any  # type: ignore
    SERVICE_NAME = "service.name"  # type: ignore

logger = logging.getLogger(__name__)

_meter_provider: MeterProvider | None = None
_initialized = False


class MetricsExporter(StrEnum):
    """Supported metrics exporters.

    Note: Prometheus is NOT included as it requires starting an HTTP server,
    which is a deployment decision for the business layer.
    """

    CONSOLE = "console"
    OTLP = "otlp"


def setup_metrics(
    service_name: str = "myrm-agent-harness",
    exporter: MetricsExporter = MetricsExporter.CONSOLE,
    export_interval_ms: int = 60_000,
    otlp_endpoint: str | None = None,
) -> None:
    """Setup metrics collection and export.

    This is a convenience function intended for the business layer.
    The framework never calls it automatically — without explicit initialization,
    OpenTelemetry uses its default NoOp MeterProvider (zero overhead).

    Supported exporters:
    - Console: Development/debugging (prints to stdout)
    - OTLP: Push to OpenTelemetry Collector (production)

    For Prometheus, business layer should integrate directly:
        ```python
        from opentelemetry.exporter.prometheus import PrometheusMetricReader
        from opentelemetry.sdk.metrics import MeterProvider
        from prometheus_client import start_http_server

        reader = PrometheusMetricReader()
        provider = MeterProvider(metric_readers=[reader])
        start_http_server(port=9090)  # Business layer controls port/binding
        ```

    Args:
        service_name: Service name for resource attributes
        exporter: Exporter backend to use (console or otlp)
        export_interval_ms: Export interval in milliseconds (for periodic exporters)
        otlp_endpoint: OTLP endpoint URL (required if using otlp exporter)
    """
    global _meter_provider, _initialized

    if not HAS_OTEL_SDK:
        logger.warning(
            "OpenTelemetry SDK not installed. Metrics will run in NoOp mode. Install with `uv add opentelemetry-sdk`"
        )
        return

    if _initialized:
        logger.debug("Metrics already initialized")
        return

    resource = Resource(attributes={SERVICE_NAME: service_name})

    if exporter == MetricsExporter.CONSOLE:
        # Console exporter for development
        reader = PeriodicExportingMetricReader(
            ConsoleMetricExporter(),
            export_interval_millis=export_interval_ms,
        )
        _meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
        logger.info("Metrics initialized with Console exporter")

    elif exporter == MetricsExporter.OTLP:
        # OTLP exporter
        try:
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                OTLPMetricExporter,
            )
        except (ImportError, TypeError):
            logger.error("OTLP exporter not available. Install: uv add opentelemetry-exporter-otlp-proto-grpc")
            raise

        if not otlp_endpoint:
            raise ValueError("otlp_endpoint is required for OTLP exporter")

        otlp_exporter = OTLPMetricExporter(endpoint=otlp_endpoint)
        reader = PeriodicExportingMetricReader(
            otlp_exporter,
            export_interval_millis=export_interval_ms,
        )
        _meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
        logger.info(f"Metrics initialized with OTLP exporter to {otlp_endpoint}")

    else:
        raise ValueError(f"Unsupported exporter: {exporter}")

    set_meter_provider(_meter_provider)
    _initialized = True


def get_meter_provider() -> MeterProvider | None:
    """Get the global MeterProvider instance.

    Returns:
        MeterProvider instance or None if not initialized
    """
    return _meter_provider


def shutdown_metrics() -> None:
    """Gracefully shutdown metrics provider and flush buffered metrics.

    Call on process exit to ensure all buffered metric data points are exported.
    """
    global _meter_provider, _initialized

    if not _initialized or _meter_provider is None:
        return

    try:
        if hasattr(_meter_provider, "shutdown"):
            _meter_provider.shutdown()
        logger.info("Metrics provider shutdown complete")
    except Exception as exc:
        logger.error("Error during metrics shutdown: %s", exc)
    finally:
        _meter_provider = None
        _initialized = False
