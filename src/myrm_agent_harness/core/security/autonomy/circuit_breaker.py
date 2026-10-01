"""Autonomy exception circuit breaker state machine.

[INPUT]
- models.py: AutonomyLevel, BreakerState, AutonomyBreakerEvent

[OUTPUT]
- AutonomyCircuitBreaker: 3-state circuit breaker with probe recovery

[POS]
Provides instant hardware-style break protection (<10ms) when agent
encounters repetitive failures or critical boundary exceptions.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Final

from myrm_agent_harness.core.security.autonomy.models import (
    AutonomyBreakerEvent,
    AutonomyLevel,
    BreakerState,
)

DEFAULT_FAILURE_THRESHOLD: Final[int] = 2
DEFAULT_RECOVERY_THRESHOLD: Final[int] = 5
DEFAULT_COOLDOWN_SECONDS: Final[float] = 30.0


class AutonomyCircuitBreaker:
    """3-State circuit breaker for runtime autonomy anomaly governance."""

    def __init__(
        self,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        recovery_threshold: int = DEFAULT_RECOVERY_THRESHOLD,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
    ) -> None:
        self._failure_threshold: Final[int] = max(1, failure_threshold)
        self._recovery_threshold: Final[int] = max(1, recovery_threshold)
        self._cooldown_seconds: Final[float] = max(0.01, cooldown_seconds)

        self._state: BreakerState = BreakerState.CLOSED
        self._consecutive_failures: int = 0
        self._consecutive_successes: int = 0
        self._last_tripped_at: float = 0.0
        self._last_error_details: str = ""
        self._lock: threading.Lock = threading.Lock()

    @property
    def state(self) -> BreakerState:
        with self._lock:
            self._evaluate_state_timeout_locked()
            return self._state

    @property
    def consecutive_failures(self) -> int:
        with self._lock:
            return self._consecutive_failures

    @property
    def consecutive_successes(self) -> int:
        with self._lock:
            return self._consecutive_successes

    def on_success(self) -> bool:
        """Records an operation success.

        Returns True if breaker transitioned from HALF_OPEN to CLOSED (fully healed).
        """
        with self._lock:
            self._consecutive_failures = 0
            if self._state == BreakerState.HALF_OPEN:
                self._consecutive_successes += 1
                if self._consecutive_successes >= self._recovery_threshold:
                    self._state = BreakerState.CLOSED
                    self._consecutive_successes = 0
                    return True
            return False

    def on_failure(
        self,
        error_msg: str,
        tool_name: str,
        session_id: str,
        current_level: AutonomyLevel,
    ) -> AutonomyBreakerEvent | None:
        """Records an operation failure.

        If consecutive failures exceed threshold or in HALF_OPEN, trips the breaker immediately.
        """
        with self._lock:
            self._consecutive_failures += 1
            self._consecutive_successes = 0
            self._last_error_details = error_msg

            if self._state == BreakerState.HALF_OPEN:
                # Any failure in trial probe trips breaker back to OPEN
                return self._trip_locked(
                    reason="Failure during trial probe in HALF_OPEN state",
                    error_msg=error_msg,
                    tool_name=tool_name,
                    session_id=session_id,
                    current_level=current_level,
                )

            if self._consecutive_failures >= self._failure_threshold:
                return self._trip_locked(
                    reason=f"Consecutive failures exceeded threshold ({self._consecutive_failures}/{self._failure_threshold})",
                    error_msg=error_msg,
                    tool_name=tool_name,
                    session_id=session_id,
                    current_level=current_level,
                )

            return None

    def trip_manually(
        self,
        reason: str,
        error_msg: str,
        tool_name: str,
        session_id: str,
        current_level: AutonomyLevel,
    ) -> AutonomyBreakerEvent:
        """Forces the breaker to trip immediately (e.g. policy violation or boundary escape)."""
        with self._lock:
            return self._trip_locked(
                reason=reason,
                error_msg=error_msg,
                tool_name=tool_name,
                session_id=session_id,
                current_level=current_level,
            )

    def manual_reset(self, to_half_open: bool = True) -> None:
        """Called when user intervenes and approves continuation."""
        with self._lock:
            self._consecutive_failures = 0
            self._consecutive_successes = 0
            if to_half_open:
                self._state = BreakerState.HALF_OPEN
            else:
                self._state = BreakerState.CLOSED

    def _trip_locked(
        self,
        reason: str,
        error_msg: str,
        tool_name: str,
        session_id: str,
        current_level: AutonomyLevel,
    ) -> AutonomyBreakerEvent:
        self._state = BreakerState.OPEN
        self._last_tripped_at = time.time()
        self._consecutive_successes = 0

        # When breaker is open, degrade autonomy back to L2 collaborator
        degraded = AutonomyLevel.L2_COLLABORATOR if current_level > AutonomyLevel.L2_COLLABORATOR else current_level

        return AutonomyBreakerEvent(
            event_id=f"breaker-{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            reason=reason,
            error_details=error_msg,
            triggered_tool=tool_name,
            previous_level=current_level,
            degraded_level=degraded,
            breaker_state=BreakerState.OPEN,
            timestamp=self._last_tripped_at,
        )

    def _evaluate_state_timeout_locked(self) -> None:
        if self._state == BreakerState.OPEN:
            elapsed = time.time() - self._last_tripped_at
            if elapsed >= self._cooldown_seconds:
                # Transition to HALF_OPEN trial probe
                self._state = BreakerState.HALF_OPEN
                self._consecutive_successes = 0
