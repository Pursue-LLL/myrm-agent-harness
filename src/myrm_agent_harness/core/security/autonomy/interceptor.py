"""Execution interceptor governing runtime autonomy transitions.

[INPUT]
- models.py: AutonomyLevel, BreakerState, AutonomyBreakerEvent
- gate_calculator.py: PromotionGateCalculator
- circuit_breaker.py: AutonomyCircuitBreaker

[OUTPUT]
- AutonomyExecutionInterceptor: session-level interceptor tying metrics, breaker, and gates

[POS]
Main entry point for agent execution pipeline to check permission,
record invocation results, and trigger instant circuit breaker fallback.
"""

from __future__ import annotations

import threading
from typing import Final

from myrm_agent_harness.core.security.autonomy.circuit_breaker import AutonomyCircuitBreaker
from myrm_agent_harness.core.security.autonomy.gate_calculator import PromotionGateCalculator
from myrm_agent_harness.core.security.autonomy.models import (
    AutonomyBreakerEvent,
    AutonomyLevel,
    AutonomyPromotionResult,
    BreakerState,
)


class AutonomyExecutionInterceptor:
    """Interceps tool execution, coordinates promotion evaluation and circuit breaker."""

    def __init__(
        self,
        session_id: str,
        initial_level: AutonomyLevel = AutonomyLevel.L2_COLLABORATOR,
        max_allowed_level: AutonomyLevel = AutonomyLevel.L5_AUTONOMOUS,
    ) -> None:
        self._session_id: Final[str] = session_id
        self._configured_level: AutonomyLevel = initial_level
        self._effective_level: AutonomyLevel = initial_level
        self._max_allowed_level: Final[AutonomyLevel] = max_allowed_level

        self._calculator: PromotionGateCalculator = PromotionGateCalculator()
        self._breaker: AutonomyCircuitBreaker = AutonomyCircuitBreaker()
        self._lock: threading.Lock = threading.Lock()

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def effective_level(self) -> AutonomyLevel:
        with self._lock:
            # If breaker is OPEN, enforce downgrade to L2 regardless of configured level
            if self._breaker.state == BreakerState.OPEN and self._effective_level > AutonomyLevel.L2_COLLABORATOR:
                return AutonomyLevel.L2_COLLABORATOR
            return self._effective_level

    @property
    def configured_level(self) -> AutonomyLevel:
        with self._lock:
            return self._configured_level

    @property
    def breaker_state(self) -> BreakerState:
        return self._breaker.state

    def check_permission(self, tool_name: str, is_write: bool) -> tuple[bool, str]:
        """Evaluates whether tool execution can proceed silently or requires intervention.

        Returns:
            (can_execute_silently, reason)
        """
        level = self.effective_level
        b_state = self.breaker_state

        if b_state == BreakerState.OPEN:
            return False, "Autonomy circuit breaker is OPEN; human approval strictly required"

        if level == AutonomyLevel.L1_ADVISOR:
            if is_write:
                return False, "L1 Advisor strictly disallows mutating/write operations"
            return True, "L1 read-only operation allowed"

        if level == AutonomyLevel.L2_COLLABORATOR:
            if is_write:
                return False, "L2 Collaborator requires explicit approval for write operation"
            return True, "L2 read-only operation allowed"

        if level == AutonomyLevel.L3_SUPERVISOR:
            # Supervised execution allows batch execution under supervisory logs
            return True, "L3 Supervisor allowed within batch"

        if level >= AutonomyLevel.L4_CONDITIONAL:
            # In L4/L5, regular operations execute autonomously unless breaker trips
            return True, "L4/L5 Autonomous execution granted"

        return False, "Unknown autonomy level; failing closed"

    def record_result(
        self,
        tool_name: str,
        is_write: bool,
        is_success: bool,
        error_msg: str | None = None,
        is_violation: bool = False,
    ) -> AutonomyBreakerEvent | None:
        """Records execution result, updates sliding window, and triggers breaker if needed."""
        self._calculator.record_invocation(
            is_success=is_success,
            is_destructive=is_write,
            is_violation=is_violation,
        )

        with self._lock:
            curr_level = self._effective_level

            # If this is a deliberate security policy violation, trip breaker immediately
            if is_violation:
                event = self._breaker.trip_manually(
                    reason="Security policy violation detected during execution",
                    error_msg=error_msg or "Unauthorized capability or boundary escape attempt",
                    tool_name=tool_name,
                    session_id=self._session_id,
                    current_level=curr_level,
                )
                self._effective_level = event.degraded_level
                return event

            if is_success:
                healed = self._breaker.on_success()
                if healed and self._effective_level < self._configured_level:
                    # Breaker healed from HALF_OPEN back to CLOSED, restore configured level
                    self._effective_level = self._configured_level
                return None
            else:
                event = self._breaker.on_failure(
                    error_msg=error_msg or "Tool execution failed",
                    tool_name=tool_name,
                    session_id=self._session_id,
                    current_level=curr_level,
                )
                if event is not None:
                    self._effective_level = event.degraded_level
                return event

    def evaluate_promotion(self) -> AutonomyPromotionResult:
        """Checks if current performance meets promotion threshold to upgrade autonomy."""
        with self._lock:
            result = self._calculator.evaluate_promotion(self._effective_level)
            # Cap at max_allowed_level
            if (
                result.eligible
                and result.recommended_level is not None
                and result.recommended_level > self._max_allowed_level
            ):
                return AutonomyPromotionResult(
                        eligible=False,
                        current_level=self._effective_level,
                        recommended_level=None,
                        reason=f"Promotion recommendation capped by organization ceiling (max: L{int(self._max_allowed_level)})",
                        metrics=result.metrics,
                    )
            return result

    def set_level(self, level: AutonomyLevel) -> None:
        """Manually sets the autonomy level (e.g. by user interaction)."""
        with self._lock:
            target = min(level, self._max_allowed_level)
            self._configured_level = target
            self._effective_level = target
            if self._breaker.state == BreakerState.OPEN:
                self._breaker.manual_reset(to_half_open=False)

    def manual_recover(self, restore_configured_level: bool = True) -> None:
        """Called when user acknowledges breaker alert and approves continuation."""
        with self._lock:
            self._breaker.manual_reset(to_half_open=True)
            if restore_configured_level:
                self._effective_level = self._configured_level

    def get_telemetry_snapshot(self) -> dict[str, object]:
        """Exports diagnostic telemetry dictionary."""
        metrics = self._calculator.get_metrics()
        return {
            "sessionId": self._session_id,
            "configuredLevel": int(self._configured_level),
            "effectiveLevel": int(self.effective_level),
            "breakerState": self.breaker_state.value,
            "consecutiveFailures": self._breaker.consecutive_failures,
            "consecutiveSuccesses": self._breaker.consecutive_successes,
            "metrics": {
                "total": metrics.total_invocations,
                "successes": metrics.successful_invocations,
                "fails": metrics.failed_invocations,
                "destructives": metrics.destructive_invocations,
                "violations": metrics.security_violations,
                "successRate": metrics.success_rate,
                "destructiveRatio": metrics.destructive_ratio,
            },
        }
