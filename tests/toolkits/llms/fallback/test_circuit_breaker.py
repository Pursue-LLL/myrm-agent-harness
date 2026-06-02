"""Tests for circuit breaker functionality."""

import time

from myrm_agent_harness.toolkits.llms.fallback.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
)


def test_circuit_breaker_initial_state():
    """Circuit breaker starts in CLOSED state."""
    cb = CircuitBreaker()
    assert cb.state == CircuitState.CLOSED
    assert not cb.is_open()


def test_circuit_breaker_opens_after_threshold():
    """Circuit opens after reaching failure threshold."""
    cb = CircuitBreaker(failure_threshold=3)

    # Record failures
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED
    cb.record_failure()

    # Should transition to OPEN
    assert cb.state == CircuitState.OPEN
    assert cb.is_open()


def test_circuit_breaker_reset_on_success():
    """Success resets failure count in CLOSED state."""
    cb = CircuitBreaker(failure_threshold=3)

    # Record some failures
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED

    # Success should reset count
    cb.record_success()

    # Need 3 more failures to open
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED
    cb.record_failure()
    assert cb.state == CircuitState.OPEN


def test_circuit_breaker_half_open_transition():
    """Circuit transitions from OPEN to HALF_OPEN after timeout."""
    cb = CircuitBreaker(failure_threshold=2, timeout_ms=100)

    # Open the circuit
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert cb.is_open()

    # Wait for timeout
    time.sleep(0.15)

    # Should transition to HALF_OPEN
    assert not cb.is_open()
    assert cb.state == CircuitState.HALF_OPEN


def test_circuit_breaker_half_open_to_closed():
    """Circuit closes after successful call in HALF_OPEN."""
    cb = CircuitBreaker(failure_threshold=2, timeout_ms=100, half_open_max_calls=1)

    # Open the circuit
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.OPEN

    # Wait and transition to HALF_OPEN
    time.sleep(0.15)
    _ = cb.is_open()
    assert cb.state == CircuitState.HALF_OPEN

    # Success should close circuit
    cb.record_success()
    assert cb.state == CircuitState.CLOSED


def test_circuit_breaker_half_open_to_open():
    """Circuit reopens on failure in HALF_OPEN."""
    cb = CircuitBreaker(failure_threshold=2, timeout_ms=100)

    # Open the circuit
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.OPEN

    # Wait and transition to HALF_OPEN
    time.sleep(0.15)
    _ = cb.is_open()
    assert cb.state == CircuitState.HALF_OPEN

    # Failure should reopen circuit
    cb.record_failure()
    assert cb.state == CircuitState.OPEN


def test_circuit_breaker_custom_thresholds():
    """Circuit breaker works with custom thresholds."""
    cb = CircuitBreaker(failure_threshold=10, timeout_ms=5000)

    # Record 9 failures
    for _ in range(9):
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    # 10th failure opens circuit
    cb.record_failure()
    assert cb.state == CircuitState.OPEN


def test_circuit_breaker_state_property():
    """State property returns current state safely."""
    cb = CircuitBreaker()

    assert cb.state == CircuitState.CLOSED

    cb.record_failure()
    cb.record_failure()
    cb.record_failure()
    cb.record_failure()
    cb.record_failure()

    assert cb.state == CircuitState.OPEN


def test_circuit_breaker_multiple_half_open_calls():
    """Circuit tracks half-open call count correctly."""
    cb = CircuitBreaker(failure_threshold=2, timeout_ms=100, half_open_max_calls=2)

    # Open the circuit
    cb.record_failure()
    cb.record_failure()

    # Wait and transition to HALF_OPEN
    time.sleep(0.15)
    _ = cb.is_open()
    assert cb.state == CircuitState.HALF_OPEN

    # First success
    cb.record_success()
    assert cb.state == CircuitState.HALF_OPEN

    # Second success should close
    cb.record_success()
    assert cb.state == CircuitState.CLOSED


def test_circuit_breaker_thread_safety():
    """Circuit breaker is thread-safe (smoke test)."""
    cb = CircuitBreaker()

    # Multiple operations should not raise exceptions
    cb.record_failure()
    _ = cb.is_open()
    _ = cb.state
    cb.record_success()
    _ = cb.is_open()


def test_retry_after_ms_closed():
    """retry_after_ms returns 0 when circuit is CLOSED."""
    cb = CircuitBreaker()
    assert cb.retry_after_ms == 0


def test_retry_after_ms_open():
    """retry_after_ms returns remaining cooldown when circuit is OPEN."""
    cb = CircuitBreaker(failure_threshold=2, timeout_ms=5000)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.OPEN

    remaining = cb.retry_after_ms
    assert 3000 < remaining <= 5000


def test_retry_after_ms_half_open():
    """retry_after_ms returns 0 when circuit is HALF_OPEN."""
    cb = CircuitBreaker(failure_threshold=2, timeout_ms=100)
    cb.record_failure()
    cb.record_failure()
    time.sleep(0.15)
    _ = cb.is_open()
    assert cb.state == CircuitState.HALF_OPEN
    assert cb.retry_after_ms == 0


def test_retry_after_ms_decreases():
    """retry_after_ms decreases over time."""
    cb = CircuitBreaker(failure_threshold=2, timeout_ms=2000)
    cb.record_failure()
    cb.record_failure()

    first = cb.retry_after_ms
    time.sleep(0.2)
    second = cb.retry_after_ms

    assert second < first
