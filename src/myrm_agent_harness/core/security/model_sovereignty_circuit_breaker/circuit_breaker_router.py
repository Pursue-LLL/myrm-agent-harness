"""
[POS] src/myrm_agent_harness/core/security/model_sovereignty_circuit_breaker/circuit_breaker_router.py
[INPUT] time, logging, typing, .types
[OUTPUT] ModelDegradationCircuitBreaker

Dynamic Circuit Breaker & Automatic Fallback Router for degraded model endpoints.
Trips open upon detecting consecutive silent downgrades and automatically fails over
to verified local Ollama/vLLM instances or backup official APIs.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import time

from .types import CircuitState, DegradationSeverity, ModelFingerprintReport

logger = logging.getLogger(__name__)


class ModelDegradationCircuitBreaker:
    """Stateful circuit breaker managing degradation thresholds and automatic fallback rerouting."""

    DEFAULT_FAILURE_THRESHOLD: int = 2
    DEFAULT_COOLDOWN_SECONDS: float = 60.0

    def __init__(
        self,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._states: dict[str, CircuitState] = {}
        self._consecutive_failures: dict[str, int] = {}
        self._tripped_at: dict[str, float] = {}

    def get_circuit_state(self, provider_id: str) -> CircuitState:
        """Query current state for a provider, evaluating cooldown transitions."""
        current = self._states.get(provider_id, CircuitState.CLOSED)
        if current == CircuitState.OPEN:
            tripped = self._tripped_at.get(provider_id, 0.0)
            if time.time() - tripped >= self._cooldown_seconds:
                logger.info("Provider '%s' cooldown elapsed. Transitioning circuit to HALF_OPEN.", provider_id)
                self._states[provider_id] = CircuitState.HALF_OPEN
                return CircuitState.HALF_OPEN
        return current

    def record_inspection_report(self, report: ModelFingerprintReport) -> tuple[CircuitState, bool]:
        """Record report and update circuit state machine. Returns (current_state, did_trip)."""
        provider_id = report.provider_id
        state = self.get_circuit_state(provider_id)
        did_trip = False

        if report.severity in (DegradationSeverity.SEVERE_DOWNGRADE, DegradationSeverity.TOTAL_OUTAGE):
            failures = self._consecutive_failures.get(provider_id, 0) + 1
            self._consecutive_failures[provider_id] = failures
            logger.warning(
                "Provider '%s' recorded degradation failure (%d/%d): %s",
                provider_id,
                failures,
                self._failure_threshold,
                report.diagnostic_reason,
            )

            if failures >= self._failure_threshold or state == CircuitState.HALF_OPEN:
                self._states[provider_id] = CircuitState.OPEN
                self._tripped_at[provider_id] = time.time()
                did_trip = True
                logger.error(
                    "CIRCUIT TRIPPED OPEN for provider '%s'! Rerouting traffic to fallback endpoint.",
                    provider_id,
                )
        else:
            # Recovery or clean execution
            if state == CircuitState.HALF_OPEN:
                logger.info("Provider '%s' successfully passed probe during HALF_OPEN. Resetting to CLOSED.", provider_id)
                self.reset_circuit(provider_id)
            else:
                self._consecutive_failures[provider_id] = 0

        return self.get_circuit_state(provider_id), did_trip

    def route_request(self, provider_id: str, fallback_target: str) -> tuple[str, bool]:
        """Determine routing target based on circuit state. Returns (selected_target, is_fallback)."""
        state = self.get_circuit_state(provider_id)
        if state == CircuitState.OPEN:
            logger.info("Circuit is OPEN for '%s'. Rerouting request to fallback '%s'.", provider_id, fallback_target)
            return fallback_target, True

        # In CLOSED or HALF_OPEN (canary probe) mode, route directly to provider
        return provider_id, False

    def reset_circuit(self, provider_id: str) -> None:
        """Manually or automatically reset a tripped provider circuit back to healthy CLOSED."""
        self._states[provider_id] = CircuitState.CLOSED
        self._consecutive_failures[provider_id] = 0
        self._tripped_at.pop(provider_id, None)
        logger.info("Circuit breaker for provider '%s' has been reset to CLOSED.", provider_id)
