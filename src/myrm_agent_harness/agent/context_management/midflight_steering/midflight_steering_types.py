"""Strongly typed contracts for Mid-Flight Steering and Interactive Execution Intervention.

[INPUT]
- None (self-contained, standard library only).

[OUTPUT]
- SteeringIntentKind: Classification of in-flight user intervention intent.
- SteeringDirectiveStatus: Lifecycle status of an individual steering directive.
- MidFlightDirective: Atomic user steering directive issued during active execution.
- SteeringInjectionEnvelope: Composed payload ready for atomic injection at execution checkpoints.
- SteeringExecutionTelemetry: Observability metrics capturing steering turnaround and acknowledgement.

[POS]
Defines data structures powering non-blocking mid-flight instruction appending,
checkpoint-based dynamic reorientation, and execution intervention.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field


class SteeringIntentKind(str, enum.Enum):
    """Classification of user intervention intent during ongoing execution."""

    REORIENT = "reorient"
    APPEND_REQUIREMENT = "append_requirement"
    PAUSE_AND_CONFIRM = "pause_and_confirm"
    ABORT_SUBTASK = "abort_subtask"


class SteeringDirectiveStatus(str, enum.Enum):
    """Lifecycle phase of an in-flight steering directive."""

    QUEUED = "queued"
    INJECTED = "injected"
    ACKNOWLEDGED = "acknowledged"
    SUPERSEDED = "superseded"


@dataclass(slots=True)
class MidFlightDirective:
    """Atomic user steering directive submitted while a long-running agent task executes."""

    directive_id: str
    session_id: str
    task_id: str
    content: str
    intent: SteeringIntentKind = SteeringIntentKind.APPEND_REQUIREMENT
    priority: int = 10
    status: SteeringDirectiveStatus = SteeringDirectiveStatus.QUEUED
    created_at: float = field(default_factory=time.time)
    injected_at: float | None = None
    acknowledged_at: float | None = None

    def mark_injected(self) -> None:
        """Transitions status to INJECTED."""
        self.status = SteeringDirectiveStatus.INJECTED
        self.injected_at = time.time()

    def mark_acknowledged(self) -> None:
        """Transitions status to ACKNOWLEDGED."""
        self.status = SteeringDirectiveStatus.ACKNOWLEDGED
        self.acknowledged_at = time.time()

    def to_dict(self) -> dict[str, object]:
        """Serializes directive to dictionary."""
        return {
            "directive_id": self.directive_id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "content": self.content,
            "intent": self.intent.value,
            "priority": self.priority,
            "status": self.status.value,
            "created_at": self.created_at,
            "injected_at": self.injected_at,
            "acknowledged_at": self.acknowledged_at,
        }


@dataclass(frozen=True, slots=True)
class SteeringInjectionEnvelope:
    """Composed steering directive envelope injected at execution checkpoints."""

    session_id: str
    checkpoint_step_index: int
    injected_directives: list[MidFlightDirective]
    composed_steering_prompt: str
    injected_timestamp: float = field(default_factory=time.time)


@dataclass(slots=True)
class SteeringExecutionTelemetry:
    """Runtime telemetry tracking mid-flight steering responsiveness."""

    session_id: str
    total_received: int
    injected_count: int
    acknowledged_count: int
    pending_queue_length: int
    avg_latency_to_injection_ms: float
    active_directives: list[MidFlightDirective]

    def to_dict(self) -> dict[str, object]:
        """Serializes telemetry metrics to dictionary."""
        return {
            "session_id": self.session_id,
            "total_received": self.total_received,
            "injected_count": self.injected_count,
            "acknowledged_count": self.acknowledged_count,
            "pending_queue_length": self.pending_queue_length,
            "avg_latency_to_injection_ms": self.avg_latency_to_injection_ms,
            "active_directives": [d.to_dict() for d in self.active_directives],
        }
