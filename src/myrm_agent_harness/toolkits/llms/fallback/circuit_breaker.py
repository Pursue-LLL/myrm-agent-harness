"""Circuit breaker for model fallback protection.

Prevents cascading failures by opening circuit after consecutive failures.

[INPUT]

[OUTPUT]
- CircuitBreaker: circuit breakerclass
- CircuitState: circuit breakerstateenum

[POS]
Circuit breaker. Opens after consecutive failures to prevent cascading failures.
"""

from __future__ import annotations

import logging
import threading
import time
from enum import Enum

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states.

    CLOSED: Normal operation, requests pass through
    OPEN: Circuit is open, requests fail fast
    HALF_OPEN: Testing if service recovered
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Circuit breaker for model fallback protection.

    Prevents cascading failures by tracking consecutive failures and
    opening the circuit when threshold is exceeded.

    Features:
    - Automatic state transitions (CLOSED → OPEN → HALF_OPEN → CLOSED)
    - Configurable failure threshold and timeout
    - Thread-safe operations
    - Metrics tracking

    Attributes:
        failure_threshold: Number of consecutive failures before opening (default: 5)
        timeout_ms: Time to wait before attempting recovery (default: 30s)
        half_open_max_calls: Max calls allowed in half-open state (default: 1)
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        timeout_ms: int = 30_000,
        half_open_max_calls: int = 1,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.timeout_ms = timeout_ms
        self.half_open_max_calls = half_open_max_calls

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._half_open_calls = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        with self._lock:
            return self._state

    @property
    def retry_after_ms(self) -> int:
        """Remaining cooldown time before retry is possible.

        Returns 0 when circuit is CLOSED or HALF_OPEN (ready for requests).
        When OPEN, returns the remaining milliseconds until automatic
        transition to HALF_OPEN state.
        """
        with self._lock:
            if self._state != CircuitState.OPEN:
                return 0
            now_ms = time.time() * 1000
            remaining = (self._last_failure_time + self.timeout_ms) - now_ms
            return max(0, int(remaining))

    def is_open(self) -> bool:
        """Check if circuit is open (requests should fail fast)."""
        with self._lock:
            # Check if we should transition from OPEN to HALF_OPEN
            if self._state == CircuitState.OPEN:
                now_ms = time.time() * 1000
                if now_ms - self._last_failure_time >= self.timeout_ms:
                    self._transition_to_half_open()
                    return False
            return self._state == CircuitState.OPEN

    def record_success(self) -> None:
        """Record a successful call.

        In CLOSED state: Reset failure count
        In HALF_OPEN state: Transition to CLOSED if enough successes
        """
        with self._lock:
            if self._state == CircuitState.CLOSED:
                self._failure_count = 0
            elif self._state == CircuitState.HALF_OPEN:
                self._half_open_calls += 1
                if self._half_open_calls >= self.half_open_max_calls:
                    self._transition_to_closed()
                    logger.info("Circuit breaker closed after successful recovery")

    def record_failure(self) -> None:
        """Record a failed call.

        In CLOSED state: Increment failure count, open if threshold exceeded
        In HALF_OPEN state: Immediately reopen circuit
        """
        with self._lock:
            now_ms = time.time() * 1000
            self._last_failure_time = now_ms

            if self._state == CircuitState.CLOSED:
                self._failure_count += 1
                if self._failure_count >= self.failure_threshold:
                    self._transition_to_open()
                    logger.warning(f"Circuit breaker opened after {self._failure_count} consecutive failures")
            elif self._state == CircuitState.HALF_OPEN:
                self._transition_to_open()
                logger.warning("Circuit breaker reopened during half-open state")

    def reset(self) -> None:
        """Reset circuit breaker to CLOSED state."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._half_open_calls = 0
            logger.info("Circuit breaker reset to CLOSED state")

    def _transition_to_open(self) -> None:
        """Transition to OPEN state (must hold lock)."""
        self._state = CircuitState.OPEN
        self._half_open_calls = 0

    def _transition_to_half_open(self) -> None:
        """Transition to HALF_OPEN state (must hold lock)."""
        self._state = CircuitState.HALF_OPEN
        self._half_open_calls = 0
        logger.info("Circuit breaker transitioned to HALF_OPEN state")

    def _transition_to_closed(self) -> None:
        """Transition to CLOSED state (must hold lock)."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._half_open_calls = 0

    def get_stats(self) -> dict[str, int | str]:
        """Get circuit breaker statistics.

        Returns:
            Dictionary with state, failure_count, retry_after_ms, and other stats
        """
        with self._lock:
            retry_ms = 0
            if self._state == CircuitState.OPEN:
                now_ms = time.time() * 1000
                retry_ms = max(0, int((self._last_failure_time + self.timeout_ms) - now_ms))

            return {
                "state": self._state.value,
                "failure_count": self._failure_count,
                "half_open_calls": self._half_open_calls,
                "retry_after_ms": retry_ms,
            }
