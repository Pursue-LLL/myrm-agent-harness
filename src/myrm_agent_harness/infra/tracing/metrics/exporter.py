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
import threading
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

    from ...git.git_resolver import resolve_git_metadata
    from ..gen_ai_conventions import (
        VCS_REF_HEAD_NAME,
        VCS_REPOSITORY_CHANGE_ID,
        VCS_REPOSITORY_REF_TYPE,
    )

    # Resolve VCS Git metadata via pure filesystem inspection (zero subprocess)
    git_meta = resolve_git_metadata()
    resource_attributes: dict[str, Any] = {
        SERVICE_NAME: service_name,
    }
    if git_meta.branch:
        resource_attributes[VCS_REF_HEAD_NAME] = git_meta.branch
        resource_attributes[VCS_REPOSITORY_REF_TYPE] = "branch"
    if git_meta.commit:
        resource_attributes[VCS_REPOSITORY_CHANGE_ID] = git_meta.commit

    resource = Resource(attributes=resource_attributes)

    if exporter == MetricsExporter.CONSOLE:
        # Console exporter for development
        reader = PeriodicExportingMetricReader(
            ConsoleMetricExporter(),
            export_interval_millis=export_interval_ms,
        )
        _meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
        logger.info("Metrics initialized with Console exporter")

    elif exporter == MetricsExporter.OTLP:
        if not otlp_endpoint:
            raise ValueError("otlp_endpoint is required for OTLP exporter")

        # OTLP exporter
        try:
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                OTLPMetricExporter,
            )
        except (ImportError, TypeError):
            logger.error("OTLP exporter not available. Install: uv add opentelemetry-exporter-otlp-proto-grpc")
            raise

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


def is_metrics_initialized() -> bool:
    """Return True when ``setup_metrics()`` has configured a real MeterProvider."""
    return _initialized


def get_meter_provider() -> MeterProvider | None:
    """Get the global MeterProvider instance.

    Returns:
        MeterProvider instance or None if not initialized
    """
    return _meter_provider


def force_flush_metrics(timeout_ms: float = 1500.0) -> bool:
    """Force flush buffered metrics with bounded timeout and daemon thread isolation.

    Args:
        timeout_ms: Maximum wait duration in milliseconds (default 1500ms).

    Returns:
        True if flush completed within timeout, False if it timed out or uninitialized.
    """
    global _meter_provider, _initialized

    if not _initialized or _meter_provider is None:
        return False

    provider = _meter_provider
    if not hasattr(provider, "force_flush"):
        return True

    flush_error: list[Exception] = []

    def _worker() -> None:
        try:
            provider.force_flush()
        except Exception as exc:
            flush_error.append(exc)

    thread = threading.Thread(target=_worker, name="otel-metrics-bounded-flush", daemon=True)
    thread.start()
    timeout_sec = max(0.01, timeout_ms / 1000.0)
    thread.join(timeout=timeout_sec)

    if thread.is_alive():
        logger.warning(
            "Metrics force_flush timed out after %.1fms (daemon thread detached)",
            timeout_ms,
        )
        return False

    if flush_error:
        logger.error("Error during metrics force_flush: %s", flush_error[0])
        return False

    return True


def shutdown_metrics(timeout_ms: float = 1500.0) -> bool:
    """Gracefully shutdown metrics provider with bounded timeout and daemon thread isolation.

    Uses a dedicated daemon thread to invoke meter provider shutdown so that if remote
    OTLP endpoints hang or network lags, the process/session exit is not blocked indefinitely,
    preventing process hangs and deadlocks.

    Args:
        timeout_ms: Maximum wait duration in milliseconds (default 1500ms).

    Returns:
        True if shutdown completed within timeout, False if it timed out or was already uninitialized.
    """
    global _meter_provider, _initialized

    if not _initialized or _meter_provider is None:
        return False

    provider = _meter_provider
    _meter_provider = None
    _initialized = False

    if not hasattr(provider, "shutdown"):
        return True

    shutdown_error: list[Exception] = []

    def _worker() -> None:
        try:
            provider.shutdown()
        except Exception as exc:
            shutdown_error.append(exc)

    thread = threading.Thread(target=_worker, name="otel-metrics-bounded-shutdown", daemon=True)
    thread.start()
    timeout_sec = max(0.01, timeout_ms / 1000.0)
    thread.join(timeout=timeout_sec)

    if thread.is_alive():
        logger.warning(
            "Metrics provider shutdown timed out after %.1fms (daemon thread detached)",
            timeout_ms,
        )
        return False

    if shutdown_error:
        logger.error("Error during metrics shutdown: %s", shutdown_error[0])
        return False

    logger.info("Metrics provider shutdown complete")
    return True
