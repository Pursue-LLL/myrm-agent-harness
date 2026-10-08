"""Type contracts and definitions for Mid-Run Barge-In Steering and Non-Destructive Intervention Suite.

Defines intervention modes, queuing models, safe steering gate evaluation results,
and runtime configuration aligned with Alibaba Qoder's barge-in paradigm.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- InterventionMode: Execution disposition when an in-flight intervention arrives.
- InterventionStatus: Lifecycle status of a queued barge-in intervention.
- BargeInMessage: An asynchronous user intervention directive submitted while the agent is running.
- SteeringPointGateResult: Decision emitted by the safe steering gate between tool call or reasoning steps.
- BargeInSteeringConfig: Configuration governing mid-run barge-in steering and gate checkpoints.

[POS]
Type contracts and definitions for Mid-Run Barge-In Steering and Non-Destructive Intervention Suite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import time


class InterventionMode(StrEnum):
    """Execution disposition when an in-flight intervention arrives."""

    BARGE_IN_STEER = "barge_in_steer"  # Inject steering message at safe step gap without killing process
    HARD_ABORT = "hard_abort"  # Immediately terminate execution loop and drain actions
    QUEUE_FOLLOW_UP = "queue_follow_up"  # Defer instruction until current run finishes completely


class InterventionStatus(StrEnum):
    """Lifecycle status of a queued barge-in intervention."""

    PENDING = "pending"  # Queued, awaiting arrival at the next safe steering gate
    APPLIED_AT_GATE = "applied_at_gate"  # Injected into context at safe step boundary
    DISCARDED = "discarded"  # Cancelled or purged before arrival
    SUPERSEDED = "superseded"  # Replaced by a newer barge-in directive


@dataclass(frozen=True)
class BargeInMessage:
    """An asynchronous user intervention directive submitted while the agent is running."""

    intervention_id: str
    session_id: str
    content: str
    mode: InterventionMode
    metadata: dict[str, str] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class SteeringPointGateResult:
    """Decision emitted by the safe steering gate between tool call or reasoning steps."""

    has_intervention: bool
    should_suspend: bool
    is_hard_abort: bool
    injected_message: dict[str, str] | None
    applied_intervention_id: str | None
    remaining_pending_count: int


@dataclass(frozen=True)
class BargeInSteeringConfig:
    """Configuration governing mid-run barge-in steering and gate checkpoints."""

    default_mode: InterventionMode = InterventionMode.BARGE_IN_STEER
    max_pending_queue_size: int = 10
    steering_instruction_prefix: str = "[MID-RUN BARGE-IN USER INTERVENTION]: "
    drain_on_abort: bool = True
