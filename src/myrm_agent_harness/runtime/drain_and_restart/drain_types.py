"""Domain types for graceful drain and session-preserving restart suite.

Provides strong-typed abstractions for service draining states, multi-service
restart receipts, in-flight task tracking, and verified launch outcomes.

[OUTPUT]
- DrainState: Lifecycle states of a draining service.
- RestartState: Lifecycle states of clean generation restart machine.
- RestartOutcome: Rigorous classification of restart verification.
- DrainNotice: Structured notification broadcast to connected clients.
- InFlightTaskInfo: Snapshot of an active task executing during drain.
- RestartReceipt: Final settlement receipt of a restart cycle.
- ServiceDrainingError: Exception raised when new tasks arrive during drain.

[INPUT]
- __future__
- time
- dataclasses
- typing

[OUTPUT]
- DrainState
- RestartState
- RestartOutcome
- VALID_DRAIN_STATES
- VALID_RESTART_STATES
- VALID_RESTART_OUTCOMES
- ServiceDrainingError
- InFlightTaskInfo
- DrainNotice
- RestartReceipt

[POS]
Domain types for graceful drain and session-preserving restart suite.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

DrainState = Literal[
    "RUNNING",
    "DRAINING",
    "DRAINED",
    "CANCELLED",
]

RestartState = Literal[
    "IDLE",
    "DRAINING",
    "LAUNCHING",
    "VERIFYING",
    "VERIFIED",
    "RELAUNCH_ATTEMPTED",
    "FAILED",
]

RestartOutcome = Literal[
    "verified",
    "relaunch_attempted",
    "failed",
]

VALID_DRAIN_STATES: tuple[DrainState, ...] = (
    "RUNNING",
    "DRAINING",
    "DRAINED",
    "CANCELLED",
)

VALID_RESTART_STATES: tuple[RestartState, ...] = (
    "IDLE",
    "DRAINING",
    "LAUNCHING",
    "VERIFYING",
    "VERIFIED",
    "RELAUNCH_ATTEMPTED",
    "FAILED",
)

VALID_RESTART_OUTCOMES: tuple[RestartOutcome, ...] = (
    "verified",
    "relaunch_attempted",
    "failed",
)


class ServiceDrainingError(RuntimeError):
    """Raised when an incoming root task is rejected because the service is draining."""


@dataclass(frozen=True, slots=True)
class InFlightTaskInfo:
    """Record of a task actively executing inside the service."""

    task_id: str
    task_type: str
    is_leaf: bool
    started_at: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class DrainNotice:
    """Broadcast notice indicating service is gracefully draining for update."""

    notice_id: str
    reason: str
    drain_budget_seconds: float
    initiated_at: float
    in_flight_count: int


@dataclass(frozen=True, slots=True)
class RestartReceipt:
    """Consolidated outcome of an automated service restart cycle."""

    outcome: RestartOutcome
    state: RestartState
    old_pid: int
    new_pid: int | None
    expected_version: str
    verified_at: float | None
    error: str | None = None
