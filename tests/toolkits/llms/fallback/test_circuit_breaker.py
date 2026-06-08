"""Tests for circuit breaker — state transitions, thread safety, metrics.

Covers: CLOSED→OPEN→HALF_OPEN→CLOSED transitions, failure threshold, timeout recovery,
half-open max calls, reset, thread safety, and stats reporting.
"""

from __future__ import annotations

import threading
import time

import pytest

from myrm_agent_harness.toolkits.llms.fallback.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
)


class TestCircuitState:
    def test_values(self):
        assert CircuitState.CLOSED.value == "closed"
        assert CircuitState.OPEN.value == "open"
        assert CircuitState.HALF_OPEN.value == "half_open"


class TestCircuitBreakerInit:
    def test_default_params(self):
        cb = CircuitBreaker()
        assert cb.failure_threshold == 5
        assert cb.timeout_ms == 30_000
        assert cb.half_open_max_calls == 1
        assert cb.state == CircuitState.CLOSED

    def test_custom_params(self):
        cb = CircuitBreaker(failure_threshold=3, timeout_ms=1000, half_open_max_calls=2)
        assert cb.failure_threshold == 3
        assert cb.timeout_ms == 1000
        assert cb.half_open_max_calls == 2


class TestCircuitBreakerTransitions:
    def test_starts_closed(self):
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED
        assert cb.is_open() is False

    def test_opens_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.is_open() is True

    def test_stays_closed_below_threshold(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()  # resets count
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=1, timeout_ms=50)
        cb.record_failure()
        assert cb.is_open() is True
        time.sleep(0.1)
        assert cb.is_open() is False  # transitions to HALF_OPEN
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_to_closed_on_success(self):
        cb = CircuitBreaker(failure_threshold=1, timeout_ms=50, half_open_max_calls=1)
        cb.record_failure()
        time.sleep(0.1)
        cb.is_open()  # trigger transition
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_to_open_on_failure(self):
        cb = CircuitBreaker(failure_threshold=1, timeout_ms=50)
        cb.record_failure()
        time.sleep(0.1)
        cb.is_open()  # trigger transition to HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN


class TestCircuitBreakerReset:
    def test_reset_from_open(self):
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED

    def test_reset_clears_failure_count(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.reset()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED  # count was reset


class TestCircuitBreakerRetryAfter:
    def test_retry_after_zero_when_closed(self):
        cb = CircuitBreaker()
        assert cb.retry_after_ms == 0

    def test_retry_after_positive_when_open(self):
        cb = CircuitBreaker(failure_threshold=1, timeout_ms=10_000)
        cb.record_failure()
        assert cb.retry_after_ms > 0
        assert cb.retry_after_ms <= 10_000


class TestCircuitBreakerStats:
    def test_stats_closed(self):
        cb = CircuitBreaker()
        stats = cb.get_stats()
        assert stats["state"] == "closed"
        assert stats["failure_count"] == 0

    def test_stats_open(self):
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        stats = cb.get_stats()
        assert stats["state"] == "open"
        assert stats["failure_count"] == 2
        assert stats["retry_after_ms"] > 0


class TestCircuitBreakerThreadSafety:
    def test_concurrent_failures(self):
        cb = CircuitBreaker(failure_threshold=100)
        errors: list[Exception] = []

        def hammer():
            try:
                for _ in range(50):
                    cb.record_failure()
                    cb.record_success()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=hammer) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(errors) == 0
        assert cb.state in (CircuitState.CLOSED, CircuitState.OPEN, CircuitState.HALF_OPEN)

    def test_concurrent_state_reads(self):
        cb = CircuitBreaker(failure_threshold=1, timeout_ms=10)
        cb.record_failure()
        errors: list[Exception] = []

        def read_state():
            try:
                for _ in range(100):
                    _ = cb.state
                    _ = cb.is_open()
                    _ = cb.retry_after_ms
                    _ = cb.get_stats()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=read_state) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(errors) == 0
