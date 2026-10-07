"""Types and models for steering.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- SteeringStatusKind: Lifecycle state of an in-flight steering message.
- SteeringPriorityKind: Priority level for human co-steering directives.
- InFlightSteeringMessage: Immutable representation of a human steering message queued during execution.
- SteeringInjectionPayload: Structured context block atomically synthesized for next LLM turn prompt.
- SteeringQueueSnapshot: Status dashboard of the session steering queue.

[POS]
Types and models for steering.
"""

# ============================================================================
# In-Flight Steering & Human Co-Steering Data Contracts (Item 161)
# Strong typing contracts for mid-turn steering message queue, inter-step atomic
# prompt injection, and non-destructive human co-steering governance.
# ============================================================================

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class SteeringStatusKind(str, Enum):
    """Lifecycle state of an in-flight steering message."""

    PENDING = "pending"  # Queued in-flight, awaiting current micro-step completion
    INJECTED = "injected"  # Atomically injected into subsequent LLM step prompt
    CANCELED = "canceled"  # Recalled/canceled by user prior to injection
    REJECTED = "rejected"  # Expired or rejected due to turn termination


class SteeringPriorityKind(str, Enum):
    """Priority level for human co-steering directives."""

    HIGH = "high"  # Course correction / critical negative constraint
    NORMAL = "normal"  # Supplementary hints or additional context


@dataclass(frozen=True, slots=True)
class InFlightSteeringMessage:
    """Immutable representation of a human steering message queued during execution."""

    message_id: str
    session_id: str
    content: str
    priority: SteeringPriorityKind
    status: SteeringStatusKind
    author_device_id: str | None
    enqueued_at_iso: str
    injected_at_iso: str | None = None
    injected_step_index: int | None = None


@dataclass(frozen=True, slots=True)
class SteeringInjectionPayload:
    """Structured context block atomically synthesized for next LLM turn prompt."""

    injected_block: str
    injected_message_ids: tuple[str, ...]
    count: int


@dataclass(frozen=True, slots=True)
class SteeringQueueSnapshot:
    """Status dashboard of the session steering queue."""

    session_id: str
    pending_messages: tuple[InFlightSteeringMessage, ...]
    total_enqueued: int
    total_injected: int
    total_canceled: int
