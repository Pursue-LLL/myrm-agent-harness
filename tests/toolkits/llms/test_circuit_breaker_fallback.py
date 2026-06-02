"""Tests for toolkits.llms.fallback.circuit_breaker — circuit breaker state machine."""

from __future__ import annotations

import time

from myrm_agent_harness.toolkits.llms.fallback.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
)


class TestCircuitBreakerInit:
    def test_starts_closed(self) -> None:
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED

    def test_custom_params(self) -> None:
        cb = CircuitBreaker(failure_threshold=3, timeout_ms=5000, half_open_max_calls=2)
        assert cb.failure_threshold == 3
        assert cb.timeout_ms == 5000
        assert cb.half_open_max_calls == 2


class TestCircuitBreakerTransitions:
    def test_stays_closed_below_threshold(self) -> None:
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    def test_opens_at_threshold(self) -> None:
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_is_open_returns_true_when_open(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, timeout_ms=60_000)
        cb.record_failure()
        assert cb.is_open() is True

    def test_transitions_to_half_open_after_timeout(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, timeout_ms=1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.01)
        assert cb.is_open() is False
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_success_closes(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, timeout_ms=1, half_open_max_calls=1)
        cb.record_failure()
        time.sleep(0.01)
        cb.is_open()  # triggers transition to HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_failure_reopens(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, timeout_ms=1)
        cb.record_failure()
        time.sleep(0.01)
        cb.is_open()  # triggers transition to HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_success_resets_failure_count(self) -> None:
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED


class TestCircuitBreakerReset:
    def test_reset_from_open(self) -> None:
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED

    def test_reset_clears_counts(self) -> None:
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.reset()
        stats = cb.get_stats()
        assert stats["failure_count"] == 0


class TestCircuitBreakerStats:
    def test_stats_closed(self) -> None:
        cb = CircuitBreaker()
        stats = cb.get_stats()
        assert stats["state"] == "closed"
        assert stats["failure_count"] == 0
        assert stats["half_open_calls"] == 0

    def test_stats_open(self) -> None:
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure()
        stats = cb.get_stats()
        assert stats["state"] == "open"
        assert stats["failure_count"] == 1
