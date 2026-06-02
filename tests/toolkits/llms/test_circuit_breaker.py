"""Unit tests for CircuitBreaker."""

from __future__ import annotations

import time

import pytest

from myrm_agent_harness.toolkits.llms.fallback.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
)


class TestCircuitBreaker:
    """Test suite for CircuitBreaker."""

    def test_initial_state_closed(self) -> None:
        """Circuit starts in CLOSED state."""
        breaker = CircuitBreaker(failure_threshold=3)
        assert breaker.state == CircuitState.CLOSED
        assert not breaker.is_open()

    def test_open_after_threshold_failures(self) -> None:
        """Circuit opens after reaching failure threshold."""
        breaker = CircuitBreaker(failure_threshold=3, timeout_ms=10_000)

        for _ in range(3):
            breaker.record_failure()

        assert breaker.state == CircuitState.OPEN
        assert breaker.is_open()

    def test_failures_below_threshold_stay_closed(self) -> None:
        """Failures below threshold keep circuit closed."""
        breaker = CircuitBreaker(failure_threshold=3)

        breaker.record_failure()
        breaker.record_failure()

        assert breaker.state == CircuitState.CLOSED
        stats = breaker.get_stats()
        assert stats["failure_count"] == 2

    def test_transition_to_half_open_after_timeout(self) -> None:
        """Circuit transitions to HALF_OPEN after timeout."""
        breaker = CircuitBreaker(failure_threshold=2, timeout_ms=100)

        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        time.sleep(0.15)
        assert not breaker.is_open()
        assert breaker.state == CircuitState.HALF_OPEN

    def test_close_after_successful_half_open(self) -> None:
        """Circuit closes after successful calls in HALF_OPEN."""
        breaker = CircuitBreaker(
            failure_threshold=2,
            half_open_max_calls=2,
            timeout_ms=100,
        )

        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        time.sleep(0.15)
        breaker.is_open()
        assert breaker.state == CircuitState.HALF_OPEN

        breaker.record_success()
        breaker.record_success()
        assert breaker.state == CircuitState.CLOSED

    def test_reopen_on_half_open_failure(self) -> None:
        """Circuit reopens if failure occurs in HALF_OPEN."""
        breaker = CircuitBreaker(failure_threshold=2, timeout_ms=100)

        breaker.record_failure()
        breaker.record_failure()
        time.sleep(0.15)
        breaker.is_open()
        assert breaker.state == CircuitState.HALF_OPEN

        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

    def test_manual_reset(self) -> None:
        """Manual reset clears all state."""
        breaker = CircuitBreaker(failure_threshold=2)

        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        breaker.reset()
        assert breaker.state == CircuitState.CLOSED
        assert breaker.get_stats()["failure_count"] == 0

    def test_success_in_closed_state_resets_failures(self) -> None:
        """Recording success in CLOSED state resets failure count."""
        breaker = CircuitBreaker(failure_threshold=5)

        breaker.record_failure()
        breaker.record_failure()
        assert breaker.get_stats()["failure_count"] == 2

        breaker.record_success()
        assert breaker.get_stats()["failure_count"] == 0

    def test_get_stats(self) -> None:
        """get_stats returns correct state information."""
        breaker = CircuitBreaker(failure_threshold=3)

        stats = breaker.get_stats()
        assert stats["state"] == "closed"
        assert stats["failure_count"] == 0
        assert stats["half_open_calls"] == 0

        breaker.record_failure()
        breaker.record_failure()
        breaker.record_failure()

        stats = breaker.get_stats()
        assert stats["state"] == "open"
        assert stats["failure_count"] == 3


@pytest.mark.benchmark(group="circuit_breaker")
def test_benchmark_state_check(benchmark: pytest.fixture) -> None:
    """Benchmark circuit breaker state check performance."""
    breaker = CircuitBreaker()

    def check_state() -> bool:
        return breaker.is_open()

    result = benchmark(check_state)
    assert result is False


@pytest.mark.benchmark(group="circuit_breaker")
def test_benchmark_record_success(benchmark: pytest.fixture) -> None:
    """Benchmark success recording performance."""
    breaker = CircuitBreaker()

    def record() -> None:
        breaker.record_success()

    benchmark(record)


@pytest.mark.benchmark(group="circuit_breaker")
def test_benchmark_record_failure(benchmark: pytest.fixture) -> None:
    """Benchmark failure recording performance."""
    breaker = CircuitBreaker(failure_threshold=100)

    def record() -> None:
        breaker.record_failure()

    benchmark(record)
