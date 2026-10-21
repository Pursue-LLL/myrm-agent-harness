"""Strongly-typed DTOs and Enums for Adaptive Wakeup Driver.

Provides channel definitions, host activity states, and wakeup budget representations.

[INPUT]
- dataclasses
- datetime
- enum

[OUTPUT]
- WakeupChannel
- HostActivityState
- WakeupSourceType
- WakeupEvent
- WakeupBudgetState
- RoutingDecision

[POS]
Strongly-typed DTOs and Enums for Adaptive Wakeup Driver.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class WakeupChannel(StrEnum):
    """The settlement delivery route determined by the adaptive wakeup driver."""

    INJECT = "inject"
    FOLLOWUP = "followup"
    SUPPRESS = "suppress"
    DEGRADE = "degrade"


class HostActivityState(StrEnum):
    """The real-time execution state of the host agent."""

    IDLE = "idle"
    BUSY = "busy"
    STOPPED = "stopped"


class WakeupSourceType(StrEnum):
    """Source domain generating the asynchronous settlement."""

    SUBAGENT = "subagent"
    BACKGROUND_JOB = "background_job"


@dataclass(frozen=True)
class WakeupEvent:
    """Represents an asynchronous settlement completion event."""

    source_type: WakeupSourceType
    source_id: str
    session_id: str
    success: bool
    summary: str
    exit_code: int | None = None
    duration_seconds: float | None = None
    error: str | None = None
    details: dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


@dataclass
class WakeupBudgetState:
    """State tracking consecutive autonomous wakes for runaway loop prevention."""

    consecutive_wakes: int = 0
    max_consecutive_wakes: int = 3
    last_wake_time: datetime | None = None
    last_human_reset_time: datetime | None = None
    is_user_stopped: bool = False

    @property
    def budget_remaining(self) -> int:
        """Remaining autonomous wake budget before degradation."""
        return max(0, self.max_consecutive_wakes - self.consecutive_wakes)

    @property
    def is_exhausted(self) -> bool:
        """Whether the autonomous wake budget has reached the maximum allowed limit."""
        return self.consecutive_wakes >= self.max_consecutive_wakes


@dataclass(frozen=True)
class RoutingDecision:
    """Decision output of the adaptive wakeup router."""

    channel: WakeupChannel
    reason: str
    session_id: str
    source_id: str
    consecutive_wakes: int
    budget_remaining: int
