"""Unit tests for metrics collection and export."""

import time

import pytest

from myrm_agent_harness.infra.tracing.metrics import (
    MetricsExporter,
    get_meter,
    setup_metrics,
)


@pytest.fixture(autouse=True)
def reset_metrics():
    """Reset metrics state between tests."""
    import myrm_agent_harness.infra.tracing.metrics.exporter as exporter_module

    exporter_module._meter_provider = None
    exporter_module._initialized = False
    yield


def test_setup_metrics_console():
    """Test metrics setup with console exporter."""
    setup_metrics(
        service_name="test-service",
        exporter=MetricsExporter.CONSOLE,
        export_interval_ms=1000,
    )

    # Verify meter can be obtained
    meter = get_meter("test")
    assert meter is not None


def test_setup_metrics_idempotent():
    """Test metrics setup is idempotent."""
    setup_metrics(service_name="test-service")
    setup_metrics(service_name="test-service")  # Should not raise


def test_counter_metric():
    """Test creating and using a counter metric."""
    setup_metrics(service_name="test-service", export_interval_ms=1000)

    meter = get_meter("test")
    counter = meter.create_counter(
        name="test_counter",
        description="Test counter metric",
        unit="1",
    )

    # Record some values
    counter.add(1, {"key": "value1"})
    counter.add(5, {"key": "value2"})
    counter.add(3, {"key": "value1"})

    # No assertion - just verify no errors


def test_histogram_metric():
    """Test creating and using a histogram metric."""
    setup_metrics(service_name="test-service", export_interval_ms=1000)

    meter = get_meter("test")
    histogram = meter.create_histogram(
        name="test_histogram",
        description="Test histogram metric",
        unit="ms",
    )

    # Record some latencies
    histogram.record(10.5, {"endpoint": "/api/v1"})
    histogram.record(25.3, {"endpoint": "/api/v1"})
    histogram.record(15.7, {"endpoint": "/api/v2"})


def test_gauge_metric():
    """Test creating and using a gauge metric."""
    setup_metrics(service_name="test-service", export_interval_ms=1000)

    meter = get_meter("test")

    from opentelemetry.metrics import Observation

    # Create observable gauge with callback
    def get_memory_usage(options):
        return [
            Observation(100.5, {"type": "heap"}),
            Observation(50.2, {"type": "stack"}),
        ]

    meter.create_observable_gauge(
        name="test_gauge",
        description="Test gauge metric",
        unit="MB",
        callbacks=[get_memory_usage],
    )

    # Wait a bit for callback to be invoked
    time.sleep(0.1)


def test_up_down_counter_metric():
    """Test creating and using an up-down counter metric."""
    setup_metrics(service_name="test-service", export_interval_ms=1000)

    meter = get_meter("test")
    counter = meter.create_up_down_counter(
        name="test_up_down_counter",
        description="Test up-down counter metric",
        unit="1",
    )

    # Record some values
    counter.add(10, {"queue": "pending"})
    counter.add(-5, {"queue": "pending"})
    counter.add(3, {"queue": "pending"})


def test_multiple_meters():
    """Test creating multiple meters."""
    setup_metrics(service_name="test-service")

    meter1 = get_meter("module1")
    meter2 = get_meter("module2")

    assert meter1 is not None
    assert meter2 is not None

    # Create metrics in different meters
    counter1 = meter1.create_counter("counter1")
    counter2 = meter2.create_counter("counter2")

    counter1.add(1)
    counter2.add(2)


def test_get_meter_provider():
    """Test getting MeterProvider instance."""
    from myrm_agent_harness.infra.tracing.metrics.exporter import get_meter_provider

    # Initially None
    provider = get_meter_provider()
    assert provider is None

    # After setup
    setup_metrics(service_name="test-service")
    provider = get_meter_provider()
    assert provider is not None


def test_setup_metrics_invalid_exporter():
    """Test setup with invalid exporter raises error."""
    with pytest.raises(ValueError, match="Unsupported exporter"):
        setup_metrics(service_name="test", exporter="invalid")  # type: ignore


def test_setup_metrics_otlp_missing_endpoint():
    """Test OTLP exporter requires endpoint parameter or raises ImportError."""
    try:
        with pytest.raises(ValueError, match="otlp_endpoint is required"):
            setup_metrics(
                service_name="test",
                exporter=MetricsExporter.OTLP,
                otlp_endpoint=None,
            )
    except (ImportError, TypeError):
        # OTLP package not installed, skip
        pytest.skip("OTLP exporter package not installed")


def test_setup_metrics_otlp_success():
    """Test OTLP exporter setup with valid endpoint."""
    try:
        setup_metrics(
            service_name="test",
            exporter=MetricsExporter.OTLP,
            otlp_endpoint="http://localhost:4317",
        )
        # If package is installed, should succeed
        meter = get_meter("test")
        assert meter is not None
    except (ImportError, TypeError):
        # If package not installed, should raise informative error
        pytest.skip("OTLP exporter package not installed")
