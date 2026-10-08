"""Decoupled action watchdog daemon.

Runs in an isolated sub-context decoupled from the main agent's reasoning loop.
Evaluates proposed actions solely against the user's original intent, contract
rules, and environmental snapshots.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import time

from .contract_invariance_asserter import ActionContractInvarianceAsserter
from .types import (
    ActionContractSpec,
    InvarianceAssertionRule,
    ThreatSeverity,
    WatchdogInspectionResult,
    WatchdogVerdictStatus,
)


class DecoupledWatchdogDaemon:
    """Independent security watchdog daemon that arbitrates action dispatch."""

    def __init__(self) -> None:
        self.asserter = ActionContractInvarianceAsserter()
        self._circuit_breaker_count: int = 0

    def inspect_action(
        self,
        spec: ActionContractSpec,
        rule: InvarianceAssertionRule | None = None,
    ) -> WatchdogInspectionResult:
        """Inspect a proposed action against intent invariants and security boundaries."""
        start_time = time.perf_counter()

        # Execute deterministic contract invariance assertions
        violations = self.asserter.assert_invariance(spec, rule)

        has_critical = any(v.threat_severity == ThreatSeverity.CRITICAL for v in violations)
        has_high = any(v.threat_severity == ThreatSeverity.HIGH for v in violations)

        latency = (time.perf_counter() - start_time) * 1000.0

        if has_critical:
            self._circuit_breaker_count += 1
            reasons = [f"{v.violation_type}: {v.description}" for v in violations]
            return WatchdogInspectionResult(
                action_id=spec.action_id,
                verdict=WatchdogVerdictStatus.CIRCUIT_BREAKER_TRIGGERED,
                confidence_score=0.99,
                violations=violations,
                circuit_breaker_active=True,
                latency_ms=latency,
                rationale="Critical invariance drift detected; action tripped watchdog circuit breaker: "
                + "; ".join(reasons),
            )

        if has_high:
            reasons = [f"{v.violation_type}: {v.description}" for v in violations]
            return WatchdogInspectionResult(
                action_id=spec.action_id,
                verdict=WatchdogVerdictStatus.NEEDS_CONFIRMATION,
                confidence_score=0.85,
                violations=violations,
                circuit_breaker_active=False,
                latency_ms=latency,
                rationale="High severity policy deviation; human confirmation required: " + "; ".join(reasons),
            )

        return WatchdogInspectionResult(
            action_id=spec.action_id,
            verdict=WatchdogVerdictStatus.APPROVED,
            confidence_score=1.0,
            violations=[],
            circuit_breaker_active=False,
            latency_ms=latency,
            rationale="Action contract conforms strictly with user intent and safety invariants.",
        )

    @property
    def total_circuit_breaker_trips(self) -> int:
        """Total number of times the circuit breaker was tripped."""
        return self._circuit_breaker_count
