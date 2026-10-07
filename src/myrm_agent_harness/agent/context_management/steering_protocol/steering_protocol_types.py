"""Type definitions for In-Flight Steering and Follow-Up Queue Injection Protocol.

Provides immutable data contracts for hierarchical inbox message models (steer/followUp/nextRun),
atomic turn-boundary drain pipelines, and compaction-safe secondary pickup.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- SteeringKind: Hierarchical classification of pending in-flight messages.
- SteeringConsumptionMode: Consumption strategy for steering queues.
- SteeringMessage: An immutable in-flight steering message submitted during execution.
- DrainResult: Atomic drain event capturing extracted steering messages at a turn boundary.
- SteeredTurnContext: Context modification descriptor after injecting steering messages.

[POS]
Type definitions for In-Flight Steering and Follow-Up Queue Injection Protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SteeringKind(str, Enum):
    """Hierarchical classification of pending in-flight messages."""

    STEER = "STEER"  # Immediate course correction injected before next LLM turn
    FOLLOW_UP = "FOLLOW_UP"  # Sequential continuation executed after current task steps complete
    NEXT_RUN = "NEXT_RUN"  # Queued prompt for next session run


class SteeringConsumptionMode(str, Enum):
    """Consumption strategy for steering queues."""

    ONE_AT_A_TIME = "ONE_AT_A_TIME"  # Single step guidance
    ALL = "ALL"  # Composite batch steering


@dataclass(frozen=True)
class SteeringMessage:
    """An immutable in-flight steering message submitted during execution."""

    message_id: str
    session_id: str
    kind: SteeringKind
    content: str
    enqueued_at: float
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DrainResult:
    """Atomic drain event capturing extracted steering messages at a turn boundary."""

    session_id: str
    drained_messages: tuple[SteeringMessage, ...]
    injection_phase: str
    timestamp: float


@dataclass(frozen=True)
class SteeredTurnContext:
    """Context modification descriptor after injecting steering messages."""

    session_id: str
    original_message_count: int
    steered_message_count: int
    injected_steering_ids: tuple[str, ...]
