"""Failover events for observability and monitoring.

[INPUT]

[OUTPUT]
- FailoverEvent: Failover event data class
- RecoveryEvent: Recovery event data class
- FailoverCallback: Type hint for failover callback function
- RecoveryCallback: Type hint for recovery callback function

[POS]
Defines failover and recovery events that are emitted during model lifecycle.
Used for monitoring, logging, and user notification.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from myrm_agent_harness.toolkits.llms.errors import FailoverReason


@dataclass
class FailoverEvent:
    """Event emitted when model failover occurs.

    Attributes:
        from_model: Name of the model that failed
        to_model: Name of the model being switched to
        reason: Reason for failover (rate_limit, timeout, error, etc.)
        error_message: Optional error message from failed model
        timestamp: When the failover occurred
        cooldown_ms: Cooldown period in milliseconds
        attempt_count: Number of attempts on failed model before failover
        session_id: Optional session ID for request tracking
        request_id: Optional request ID for detailed tracking
        available_candidates: List of available candidate models at failover time
        scenario: Usage scenario (realtime/batch/balanced)
    """

    from_model: str
    to_model: str
    reason: FailoverReason
    error_message: str | None = None
    timestamp: datetime = None  # type: ignore
    cooldown_ms: int = 0
    attempt_count: int = 1
    session_id: str | None = None
    request_id: str | None = None
    available_candidates: list[str] = field(default_factory=list)
    scenario: str | None = None

    def __post_init__(self) -> None:
        """Set default timestamp if not provided."""
        if self.timestamp is None:
            self.timestamp = datetime.now()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
            "from_model": self.from_model,
            "to_model": self.to_model,
            "reason": self.reason.value.lower(),
            "error_message": self.error_message,
            "timestamp": self.timestamp.isoformat(),
            "cooldown_ms": self.cooldown_ms,
            "attempt_count": self.attempt_count,
        }

        # Add optional context fields if present
        if self.session_id:
            result["session_id"] = self.session_id
        if self.request_id:
            result["request_id"] = self.request_id
        if self.available_candidates:
            result["available_candidates"] = self.available_candidates
        if self.scenario:
            result["scenario"] = self.scenario

        return result


@dataclass
class RecoveryEvent:
    """Event emitted when a model recovers from cooldown.

    Attributes:
        model: Name of the model that recovered
        downtime_ms: Duration the model was unavailable (in milliseconds)
        probe_count: Number of probe attempts before successful recovery
        timestamp: When the recovery occurred
        was_in_cooldown: Whether model was in cooldown period
    """

    model: str
    downtime_ms: int
    probe_count: int
    timestamp: datetime = None  # type: ignore
    was_in_cooldown: bool = True

    def __post_init__(self) -> None:
        """Set default timestamp if not provided."""
        if self.timestamp is None:
            self.timestamp = datetime.now()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "model": self.model,
            "downtime_ms": self.downtime_ms,
            "probe_count": self.probe_count,
            "timestamp": self.timestamp.isoformat(),
            "was_in_cooldown": self.was_in_cooldown,
        }


# Type hint for failover callback function
FailoverCallback = Callable[[FailoverEvent], Awaitable[None]]

# Type hint for recovery callback function
RecoveryCallback = Callable[[RecoveryEvent], Awaitable[None]]
