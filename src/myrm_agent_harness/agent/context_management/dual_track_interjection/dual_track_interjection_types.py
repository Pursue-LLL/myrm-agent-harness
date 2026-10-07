"""Strongly typed contracts for Long-Running Task Dual-Track Interjection and Preemption Queue Suite (Item 212).

[INPUT]
- None (self-contained, standard library only).

[OUTPUT]
- InterventionTrack: Classification of dynamic intervention (immediate interjection vs. queue preemption).
- InterventionStatus: Lifecycle status of an intervention directive.
- UserInterventionDirective: Strongly typed directive carrying prompt text, priority, and timestamps.
- StepBoundaryInjectionResult: Outcome of draining immediate interjections at step/turn boundaries.
- PreemptionQueueSnapshot: Snapshot of prioritized tasks waiting in the preemption queue.
- DualTrackInterventionConfig: Tunable configurations for queue capacities and formatting.

[POS]
- Provides deterministic mid-flight task steering, eliminating the dilemma between aborting long tasks
- and burning tokens unchecked, by separating step-boundary guidance from task-queue preemption.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field


class InterventionTrack(str, enum.Enum):
    """Routing track for mid-flight user directives."""

    IMMEDIATE_INTERJECT = "immediate_interject"
    QUEUE_PREEMPTION = "queue_preemption"


class InterventionStatus(str, enum.Enum):
    """Lifecycle phase of an intervention directive."""

    PENDING = "pending"
    CONSUMED = "consumed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass(slots=True)
class UserInterventionDirective:
    """Strongly typed record for mid-flight interjections or prioritized queue items."""

    directive_id: str
    session_id: str
    track: InterventionTrack
    prompt_text: str
    priority: int = 100
    status: InterventionStatus = InterventionStatus.PENDING
    created_at: float = field(default_factory=time.time)
    consumed_at: float | None = None

    def to_dict(self) -> dict[str, object]:
        """Serializes directive to dictionary."""
        return {
            "directive_id": self.directive_id,
            "session_id": self.session_id,
            "track": self.track.value,
            "prompt_text": self.prompt_text,
            "priority": self.priority,
            "status": self.status.value,
            "created_at": self.created_at,
            "consumed_at": self.consumed_at,
        }


@dataclass(frozen=True, slots=True)
class StepBoundaryInjectionResult:
    """Outcome of draining and applying pending interjections at a safe execution boundary."""

    interjection_applied: bool
    injected_message: dict[str, object] | None
    consumed_directive_ids: list[str]
    remaining_pending_count: int

    def to_dict(self) -> dict[str, object]:
        """Serializes step boundary injection outcome."""
        return {
            "interjection_applied": self.interjection_applied,
            "injected_message": self.injected_message,
            "consumed_directive_ids": list(self.consumed_directive_ids),
            "remaining_pending_count": self.remaining_pending_count,
        }


@dataclass(frozen=True, slots=True)
class PreemptionQueueSnapshot:
    """State inspection snapshot of pending preemption queue items."""

    session_id: str
    queued_directives: list[UserInterventionDirective]
    queue_length: int

    def to_dict(self) -> dict[str, object]:
        """Serializes preemption queue snapshot."""
        return {
            "session_id": self.session_id,
            "queue_length": self.queue_length,
            "queued_directives": [d.to_dict() for d in self.queued_directives],
        }


@dataclass(slots=True)
class DualTrackInterventionConfig:
    """Configuration governing queue limits, expiration, and prompt injection templates."""

    max_pending_interjections: int = 5
    max_preemption_queue_depth: int = 20
    interjection_xml_tag: str = "human-interjection"
    expiration_seconds: float = 3600.0
    interjection_prefix_label: str = (
        "User mid-flight clarification received during step boundary. Please adapt current execution without discarding prior valid accomplishments:"
    )
