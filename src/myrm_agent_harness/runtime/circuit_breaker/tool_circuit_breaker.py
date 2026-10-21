"""Tool-level adaptive circuit breaker with state machine and retry execution.

Transitions between CLOSED, OPEN, and HALF_OPEN states to shield external
APIs from retry storms and maintain agent responsiveness during outages.

[INPUT]
- __future__
- asyncio
- time
- collections
- circuit_breaker_types
- error_classifier_and_backoff

[OUTPUT]
- ToolCallable
- FallbackCallable
- ToolCircuitBreaker

[POS]
Tool-level adaptive circuit breaker with state machine and retry execution.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Coroutine

from .circuit_breaker_types import (
    CircuitBreakerConfig,
    CircuitBreakerSnapshot,
    CircuitState,
    ErrorCategory,
    ToolExecutionOutcome,
)
from .error_classifier_and_backoff import (
    ErrorClassifier,
    FullJitterBackoff,
)

ToolCallable = Callable[..., Coroutine[object, object, str] | str]
FallbackCallable = Callable[[], str]


class ToolCircuitBreaker:
    """Manages adaptive circuit breaking and jittered retries for a single tool."""

    def __init__(
        self,
        tool_name: str,
        config: CircuitBreakerConfig | None = None,
    ) -> None:
        self.tool_name = tool_name
        self.config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._total_calls = 0
        self._total_failures = 0
        self._total_fallbacks = 0
        self._last_state_change = time.time()
        self._half_open_probe_in_flight = False

    @property
    def state(self) -> CircuitState:
        """Return the current circuit state, automatically checking recovery cooldown."""
        now = time.time()
        if (
            self._state == CircuitState.OPEN
            and now - self._last_state_change >= self.config.recovery_timeout_s
        ):
            self._state = CircuitState.HALF_OPEN
            self._last_state_change = now
            self._half_open_probe_in_flight = False
        return self._state

    async def execute_with_resilience(
        self,
        func: ToolCallable,
        fallback_fn: FallbackCallable,
        *args: object,
        **kwargs: object,
    ) -> ToolExecutionOutcome:
        """Execute a tool function under circuit breaker protection and bounded jitter retries."""
        start_t = time.time()
        cur_state = self.state

        # 1. OPEN State: Immediate 0ms fast-fail into fallback
        if cur_state == CircuitState.OPEN:
            self._total_fallbacks += 1
            fallback_val = fallback_fn()
            return ToolExecutionOutcome(
                success=True,
                return_value=fallback_val,
                is_fallback=True,
                circuit_state=CircuitState.OPEN,
                retries_attempted=0,
                duration_s=time.time() - start_t,
            )

        # 2. HALF_OPEN State: Only permit a single probe request
        if cur_state == CircuitState.HALF_OPEN:
            if self._half_open_probe_in_flight:
                # Concurrent requests during probe cooldown route to fallback
                self._total_fallbacks += 1
                fallback_val = fallback_fn()
                return ToolExecutionOutcome(
                    success=True,
                    return_value=fallback_val,
                    is_fallback=True,
                    circuit_state=CircuitState.HALF_OPEN,
                    retries_attempted=0,
                    duration_s=time.time() - start_t,
                )
            self._half_open_probe_in_flight = True

        # 3. Execution with classified jittered retries
        self._total_calls += 1
        retries = 0
        last_error_msg = ""

        while retries <= self.config.max_retries:
            try:
                res = func(*args, **kwargs)
                if asyncio.iscoroutine(res):
                    val = await res
                else:
                    val = str(res)

                self._record_success()
                return ToolExecutionOutcome(
                    success=True,
                    return_value=str(val),
                    is_fallback=False,
                    circuit_state=self._state,
                    retries_attempted=retries,
                    duration_s=time.time() - start_t,
                )
            except Exception as exc:
                last_error_msg = str(exc)
                category = ErrorClassifier.classify(exc)

                # Fatal non-retryable errors abort retry loop immediately
                if category == ErrorCategory.NON_RETRYABLE_FATAL:
                    self._record_failure()
                    return ToolExecutionOutcome(
                        success=False,
                        error_msg=f"Fatal error in {self.tool_name}: {last_error_msg}",
                        is_fallback=False,
                        circuit_state=self._state,
                        retries_attempted=retries,
                        duration_s=time.time() - start_t,
                    )

                # Retryable transient fault: apply Full Jitter backoff if retries remain
                if retries < self.config.max_retries:
                    delay = FullJitterBackoff.compute_delay(
                        retries,
                        self.config.base_backoff_s,
                        self.config.max_backoff_s,
                    )
                    await asyncio.sleep(delay)
                    retries += 1
                else:
                    # Retries exhausted
                    break

        # Retries exhausted: record failure and route to graceful fallback
        self._record_failure()
        self._total_fallbacks += 1
        fallback_val = fallback_fn()

        return ToolExecutionOutcome(
            success=True,
            return_value=fallback_val,
            error_msg=f"Transient failures exhausted for {self.tool_name}: {last_error_msg}",
            is_fallback=True,
            circuit_state=self._state,
            retries_attempted=retries,
            duration_s=time.time() - start_t,
        )

    def _record_success(self) -> None:
        """Record a successful execution and reset failure counters."""
        self._consecutive_failures = 0
        self._half_open_probe_in_flight = False
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.CLOSED
            self._last_state_change = time.time()

    def _record_failure(self) -> None:
        """Record an execution failure and trip circuit to OPEN if threshold breached."""
        self._total_failures += 1
        self._consecutive_failures += 1
        self._half_open_probe_in_flight = False
        now = time.time()

        if self._state == CircuitState.HALF_OPEN:
            # Probe failed in HALF_OPEN: immediately re-trip to OPEN
            self._state = CircuitState.OPEN
            self._last_state_change = now
        elif self._state == CircuitState.CLOSED:
            if self._consecutive_failures >= self.config.failure_threshold:
                self._state = CircuitState.OPEN
                self._last_state_change = now

    def force_state(self, state: CircuitState) -> None:
        """Force the circuit breaker into a designated state for manual testing or overrides."""
        self._state = state
        self._last_state_change = time.time()
        self._half_open_probe_in_flight = False

    def get_snapshot(self) -> CircuitBreakerSnapshot:
        """Return a point-in-time telemetry snapshot of this circuit breaker."""
        return CircuitBreakerSnapshot(
            tool_name=self.tool_name,
            state=self.state,
            consecutive_failures=self._consecutive_failures,
            total_calls=self._total_calls,
            total_failures=self._total_failures,
            total_fallbacks=self._total_fallbacks,
            last_state_change=self._last_state_change,
        )
