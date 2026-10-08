"""Adaptive tri-state circuit breaker for vector providers.

[POS]
Lightweight in-memory circuit breaker protecting vector search from
cascading timeouts, network jitter, and provider outages with auto-healing.

[INPUT]
- time.monotonic
- .models.CircuitState

[OUTPUT]
- AdaptiveCircuitBreaker
"""

from __future__ import annotations

import time

from myrm_agent_harness.toolkits.memory.hybrid_search.models import CircuitState


class AdaptiveCircuitBreaker:
    """Manages failure thresholds and self-healing transitions for search providers."""

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout_seconds: float = 30.0,
    ) -> None:
        """Initialize circuit breaker.

        Args:
            failure_threshold: Consecutive failures needed to trip breaker.
            recovery_timeout_seconds: Seconds to wait in OPEN state before testing HALF_OPEN.
        """
        self._failure_threshold = max(1, failure_threshold)
        self._recovery_timeout = max(0.001, recovery_timeout_seconds)
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_state_change = time.monotonic()

    @property
    def state(self) -> CircuitState:
        """Current effective circuit breaker state taking elapsed time into account."""
        now = time.monotonic()
        if self._state == CircuitState.OPEN and now - self._last_state_change >= self._recovery_timeout:
            self._state = CircuitState.HALF_OPEN
            self._last_state_change = now
        return self._state

    @property
    def failure_count(self) -> int:
        """Current consecutive failure count."""
        return self._failure_count

    def should_allow_request(self) -> bool:
        """Determine whether request should be allowed through to provider."""
        current = self.state
        return current in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    def record_success(self) -> None:
        """Record successful invocation, resetting failures and healing breaker."""
        self._failure_count = 0
        self._state = CircuitState.CLOSED
        self._last_state_change = time.monotonic()

    def record_failure(self) -> None:
        """Record failed or timed-out invocation, advancing breaker towards OPEN."""
        self._failure_count += 1
        now = time.monotonic()
        if self._state == CircuitState.HALF_OPEN or self._failure_count >= self._failure_threshold:
            self._state = CircuitState.OPEN
            self._last_state_change = now

    def force_state(self, state: CircuitState) -> None:
        """Explicitly override circuit state (useful in test harnesses and manual failover)."""
        self._state = state
        self._failure_count = self._failure_threshold if state == CircuitState.OPEN else 0
        self._last_state_change = time.monotonic()
