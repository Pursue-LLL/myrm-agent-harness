"""Lightweight thread-safe circuit breaker for embedding providers.

[INPUT]
- dataclasses, logging, threading, time, typing
- toolkits.memory.hybrid_engine.models::CircuitBreakerConfig, CircuitBreakerState, CircuitBreakerStats

[OUTPUT]
- CircuitBreakerOpenError: Exception raised when circuit breaker is active.
- EmbeddingCircuitBreaker: Circuit breaker protecting against vector provider outages.

[POS]
Item 133 DualEngineHybridSearchAndGracefulFallbackSuite.
Guards dense vector embedding retrieval channel with fast-trip (<0.1ms),
exponential recovery probes, and fallback to local SQLite FTS5.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import TypeVar

from myrm_agent_harness.toolkits.memory.hybrid_engine.models import (
    CircuitBreakerConfig,
    CircuitBreakerState,
    CircuitBreakerStats,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitBreakerOpenError(RuntimeError):
    """Raised when an operation is attempted while circuit breaker is OPEN."""


class EmbeddingCircuitBreaker:
    """Thread-safe circuit breaker for protecting vector embedding provider operations."""

    def __init__(self, config: CircuitBreakerConfig | None = None) -> None:
        self._config = config or CircuitBreakerConfig()
        self._lock = threading.Lock()
        self._state: CircuitBreakerState = CircuitBreakerState.CLOSED
        self._failure_count: int = 0
        self._consecutive_successes: int = 0
        self._last_failure_time: float = 0.0
        self._last_state_change: float = time.time()
        self._tripped_count: int = 0

    @property
    def config(self) -> CircuitBreakerConfig:
        return self._config

    @property
    def state(self) -> CircuitBreakerState:
        with self._lock:
            self._evaluate_state_transition_locked()
            return self._state

    def _evaluate_state_transition_locked(self) -> None:
        """Evaluate automatic transition from OPEN to HALF_OPEN after cooldown."""
        if self._state == CircuitBreakerState.OPEN:
            now = time.time()
            cooldown = self._config.recovery_timeout_seconds
            if now - self._last_state_change >= cooldown:
                logger.info("Circuit breaker entering HALF_OPEN probe state after %ss cooldown", cooldown)
                self._state = CircuitBreakerState.HALF_OPEN
                self._last_state_change = now
                self._consecutive_successes = 0

    def execute(self, func: Callable[[], T]) -> T:
        """Execute protected provider call with circuit breaking protection."""
        with self._lock:
            self._evaluate_state_transition_locked()
            if self._state == CircuitBreakerState.OPEN:
                raise CircuitBreakerOpenError(
                    f"Embedding circuit breaker is OPEN (tripped {self._tripped_count} times). "
                    f"Fast-failing to trigger graceful local FTS5 fallback."
                )

        # Execute provider call outside lock to avoid contention
        try:
            result = func()
        except Exception as exc:
            self._on_failure()
            raise exc

        self._on_success()
        return result

    def _on_failure(self) -> None:
        """Handle execution failure."""
        with self._lock:
            now = time.time()
            self._last_failure_time = now
            self._consecutive_successes = 0

            if self._state == CircuitBreakerState.HALF_OPEN:
                # Failed probe in HALF_OPEN trips immediately back to OPEN
                self._state = CircuitBreakerState.OPEN
                self._last_state_change = now
                self._tripped_count += 1
                logger.warning("Probe failed in HALF_OPEN. Tripping back to OPEN state.")
            elif self._state == CircuitBreakerState.CLOSED:
                self._failure_count += 1
                if self._failure_count >= self._config.failure_threshold:
                    self._state = CircuitBreakerState.OPEN
                    self._last_state_change = now
                    self._tripped_count += 1
                    logger.warning(
                        "Circuit breaker tripped to OPEN after %d consecutive failures.",
                        self._failure_count,
                    )

    def _on_success(self) -> None:
        """Handle execution success."""
        with self._lock:
            if self._state == CircuitBreakerState.HALF_OPEN:
                self._consecutive_successes += 1
                if self._consecutive_successes >= 1:
                    logger.info("Probe succeeded in HALF_OPEN. Resetting circuit breaker to CLOSED.")
                    self._state = CircuitBreakerState.CLOSED
                    self._failure_count = 0
                    self._last_state_change = time.time()
            elif self._state == CircuitBreakerState.CLOSED:
                self._failure_count = 0

    def trip(self, reason: str = "manual") -> None:
        """Manually trip circuit breaker to OPEN for disaster simulation or tests."""
        with self._lock:
            self._state = CircuitBreakerState.OPEN
            self._last_state_change = time.time()
            self._tripped_count += 1
            logger.info("Circuit breaker manually tripped to OPEN: %s", reason)

    def reset(self) -> None:
        """Manually reset circuit breaker to CLOSED."""
        with self._lock:
            self._state = CircuitBreakerState.CLOSED
            self._failure_count = 0
            self._consecutive_successes = 0
            self._last_state_change = time.time()
            logger.info("Circuit breaker manually reset to CLOSED.")

    def get_stats(self) -> CircuitBreakerStats:
        """Return snapshot telemetry of circuit breaker."""
        with self._lock:
            self._evaluate_state_transition_locked()
            return CircuitBreakerStats(
                state=self._state,
                failure_count=self._failure_count,
                consecutive_successes=self._consecutive_successes,
                last_failure_time=self._last_failure_time,
                last_state_change=self._last_state_change,
                tripped_count=self._tripped_count,
            )
