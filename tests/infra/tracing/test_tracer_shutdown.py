"""Unit tests for bounded timeout and daemon thread tracing shutdown."""

import time
from unittest.mock import MagicMock

import myrm_agent_harness.infra.tracing.tracer as tracer_mod
from myrm_agent_harness.infra.tracing.tracer import shutdown_tracing


def test_shutdown_tracing_not_initialized():
    """Returns False when tracer is not initialized."""
    tracer_mod._initialized = False
    tracer_mod._tracer_provider = None
    assert shutdown_tracing() is False


def test_shutdown_tracing_normal_success():
    """Completes cleanly and returns True when provider shuts down normally."""
    mock_provider = MagicMock()
    tracer_mod._initialized = True
    tracer_mod._tracer_provider = mock_provider

    res = shutdown_tracing(timeout_ms=1000.0)
    assert res is True
    assert tracer_mod._initialized is False
    assert tracer_mod._tracer_provider is None
    mock_provider.shutdown.assert_called_once()


def test_shutdown_tracing_bounded_timeout():
    """Gracefully detaches and returns False when shutdown hangs beyond timeout."""
    mock_provider = MagicMock()

    def _hanging_shutdown():
        time.sleep(1.0)

    mock_provider.shutdown.side_effect = _hanging_shutdown

    tracer_mod._initialized = True
    tracer_mod._tracer_provider = mock_provider

    start = time.perf_counter()
    # Provide a tight 50ms timeout
    res = shutdown_tracing(timeout_ms=50.0)
    elapsed = time.perf_counter() - start

    assert res is False
    assert elapsed < 0.3  # Well below the 1.0s hang!
    assert tracer_mod._initialized is False
    assert tracer_mod._tracer_provider is None


def test_shutdown_tracing_with_exception():
    """Handles exceptions raised by provider shutdown without crashing."""
    mock_provider = MagicMock()
    mock_provider.shutdown.side_effect = RuntimeError("network unreachable")

    tracer_mod._initialized = True
    tracer_mod._tracer_provider = mock_provider

    res = shutdown_tracing(timeout_ms=500.0)
    assert res is False
    assert tracer_mod._initialized is False
    assert tracer_mod._tracer_provider is None
