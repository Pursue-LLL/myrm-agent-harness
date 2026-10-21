"""Circuit Breaker Prometheus metrics

Provides metrics for monitoring circuit breaker state and failures.

[INPUT]
- None (POS: Metric definitions only)

[OUTPUT]
- circuit_breaker_state: Gauge for circuit breaker state
- circuit_breaker_failures_total: Counter for circuit breaker failures

[POS]
Prometheus metrics for circuit breaker monitoring.
Allows operators to visualize circuit breaker state and set up alerts.

Usage:
    from myrm_agent_harness.observability.metrics.circuit_breaker_metrics import (
        circuit_breaker_state,
        circuit_breaker_failures_total,
    )

    # Record circuit breaker state
    circuit_breaker_state.labels(component="summarize").set(2)  # 0=CLOSED, 1=HALF_OPEN, 2=OPEN

    # Record failure
    circuit_breaker_failures_total.labels(
        component="summarize",
        error_type="auth",
    ).inc()
"""

from __future__ import annotations

from typing import Any

from myrm_agent_harness.observability.metrics import create_counter, create_gauge


class _NoOpMetric:
    """No-op metric fallback when prometheus_client is not installed."""

    def labels(self, **kwargs: Any) -> _NoOpMetric:
        return self

    def set(self, value: float) -> None:
        pass

    def inc(self, amount: float = 1.0) -> None:
        pass


_NOOP_METRIC = _NoOpMetric()

_circuit_breaker_state = create_gauge(
    name="circuit_breaker_state",
    description="Circuit breaker state: 0=CLOSED, 1=HALF_OPEN, 2=OPEN",
    labelnames=["component"],
)
circuit_breaker_state = _circuit_breaker_state if _circuit_breaker_state is not None else _NOOP_METRIC
"""Circuit breaker state gauge

Labels:
- component: Component name (summarize, session_notes)

States:
- 0: CLOSED (normal operation)
- 1: HALF_OPEN (probing for recovery)
- 2: OPEN (circuit breaker tripped, using fallback)
"""

_circuit_breaker_failures_total = create_counter(
    name="circuit_breaker_failures_total",
    description="Total circuit breaker failures by component and error type",
    labelnames=["component", "error_type"],
)
circuit_breaker_failures_total = (
    _circuit_breaker_failures_total if _circuit_breaker_failures_total is not None else _NOOP_METRIC
)
"""Circuit breaker failures counter

Labels:
- component: Component name (summarize, session_notes)
- error_type: Error type (auth, network, timeout, other)
"""
