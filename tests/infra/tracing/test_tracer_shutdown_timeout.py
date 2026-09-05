"""Unit tests for bounded force-flush and timeout resilience in tracer shutdown."""

import time
from unittest.mock import MagicMock

from myrm_agent_harness.infra.tracing import tracer


def test_shutdown_tracing_uninitialized():
    """Shutdown when not initialized should return False safely."""
    # Ensure uninitialized
    tracer._initialized = False
    tracer._tracer_provider = None

    res = tracer.shutdown_tracing(timeout_ms=500.0)
    assert res is False


def test_shutdown_tracing_success_within_timeout():
    """Shutdown completes cleanly within timeout bound."""
    mock_provider = MagicMock()
    mock_provider.shutdown.return_value = None

    tracer._initialized = True
    tracer._tracer_provider = mock_provider

    res = tracer.shutdown_tracing(timeout_ms=1000.0)
    assert res is True
    mock_provider.shutdown.assert_called_once()
    assert tracer._initialized is False
    assert tracer._tracer_provider is None


def test_shutdown_tracing_hang_fails_open_with_timeout():
    """Simulate remote endpoint hang; shutdown should abort after timeout_ms without deadlocking."""
    mock_provider = MagicMock()

    def _hanging_shutdown():
        # Hang for 2 seconds
        time.sleep(2.0)

    mock_provider.shutdown.side_effect = _hanging_shutdown

    tracer._initialized = True
    tracer._tracer_provider = mock_provider

    start = time.perf_counter()
    # 100ms timeout
    res = tracer.shutdown_tracing(timeout_ms=100.0)
    elapsed = time.perf_counter() - start

    assert res is False
    # Should complete shortly after 100ms, definitely well under 1.5s
    assert elapsed < 1.0
    assert tracer._initialized is False
    assert tracer._tracer_provider is None
