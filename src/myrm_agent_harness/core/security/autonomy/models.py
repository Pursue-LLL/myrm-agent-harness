"""Autonomy governance protocol models and telemetry contracts.

[INPUT]
- Python stdlib enum, dataclasses, typing

[OUTPUT]
- AutonomyLevel: 5-stage autonomy protocol (L1..L5)
- BreakerState: 3-state circuit breaker enum (CLOSED, OPEN, HALF_OPEN)
- AutonomyMetrics: sliding-window performance metrics
- AutonomyBreakerEvent: structured circuit breaker tripped telemetry
- AutonomyPromotionResult: gate evaluation recommendation

[POS]
Foundational data contracts for data-driven autonomy level escalation
and exception-driven circuit breaker governance suite.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum


class AutonomyLevel(IntEnum):
    """5-stage autonomy protocol governing agent execution rights."""

    L1_ADVISOR = 1  # Read-only suggestions; all mutating actions strictly prohibited
    L2_COLLABORATOR = 2  # Baseline: Single-step human-in-the-loop approval for write/exec
    L3_SUPERVISOR = 3  # Batch intent inspection and supervised execution
    L4_CONDITIONAL = 4  # Autonomous in bounded trusted territory; trips to L2 on anomaly
    L5_AUTONOMOUS = 5  # Full autonomy inside bounded audit sandbox


class BreakerState(StrEnum):
    """Circuit breaker operational states."""

    CLOSED = "closed"  # Normal operation: metrics monitored, requests allowed
    OPEN = "open"  # Tripped / Blown: execution halted, fallback to L2 enforced
    HALF_OPEN = "half_open"  # Trial probe: limited operations allowed to test recovery


@dataclass(frozen=True, slots=True)
class AutonomyMetrics:
    """Snapshot of agent runtime telemetry inside sliding window."""

    window_size: int
    total_invocations: int
    successful_invocations: int
    failed_invocations: int
    destructive_invocations: int
    security_violations: int
    success_rate: float
    destructive_ratio: float

    @property
    def is_reliable(self) -> bool:
        """Determines if the sample size is sufficient to avoid cold-start bias."""
        return self.total_invocations >= 20


@dataclass(frozen=True, slots=True)
class AutonomyBreakerEvent:
    """Structured event emitted when the autonomy circuit breaker trips."""

    event_id: str
    session_id: str
    reason: str
    error_details: str
    triggered_tool: str
    previous_level: AutonomyLevel
    degraded_level: AutonomyLevel
    breaker_state: BreakerState
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        return {
            "eventId": self.event_id,
            "sessionId": self.session_id,
            "reason": self.reason,
            "errorDetails": self.error_details,
            "triggeredTool": self.triggered_tool,
            "previousLevel": int(self.previous_level),
            "degradedLevel": int(self.degraded_level),
            "breakerState": self.breaker_state.value,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True, slots=True)
class AutonomyPromotionResult:
    """Outcome of promotion gate evaluation."""

    eligible: bool
    current_level: AutonomyLevel
    recommended_level: AutonomyLevel | None
    reason: str
    metrics: AutonomyMetrics
