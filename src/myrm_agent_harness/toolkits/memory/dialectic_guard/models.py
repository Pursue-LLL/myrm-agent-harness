"""[POS]: myrm_agent_harness/toolkits/memory/dialectic_guard/models.py
[INPUT]: Configuration options, state slot records, and audit models for dialectic liveness.
[OUTPUT]: Data structures for thread timeout recovery, orphan rejection, stale pivot discard, and telemetry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ExecutionSlotState(StrEnum):
    """Lifecycle state of a dialectic execution slot."""

    IDLE = "idle"
    RUNNING = "running"
    DEAD = "dead"
    COMPLETED = "completed"


@dataclass(frozen=True)
class DialecticLivenessConfig:
    """Configuration governing dialectic execution liveness, pivots, and backoff."""

    base_cadence: int = 5
    timeout_seconds: float = 30.0
    stale_thread_multiplier: float = 2.0
    stale_result_multiplier: float = 2.0
    max_backoff_multiplier: int = 8

    def __post_init__(self) -> None:
        if self.base_cadence < 1:
            raise ValueError(f"base_cadence must be >= 1, got {self.base_cadence}")
        if self.timeout_seconds <= 0.0:
            raise ValueError(f"timeout_seconds must be > 0.0, got {self.timeout_seconds}")
        if self.stale_thread_multiplier < 1.0:
            raise ValueError(
                f"stale_thread_multiplier must be >= 1.0, got {self.stale_thread_multiplier}"
            )
        if self.stale_result_multiplier < 1.0:
            raise ValueError(
                f"stale_result_multiplier must be >= 1.0, got {self.stale_result_multiplier}"
            )
        if self.max_backoff_multiplier < 1:
            raise ValueError(
                f"max_backoff_multiplier must be >= 1, got {self.max_backoff_multiplier}"
            )


@dataclass
class DialecticExecutionSlot:
    """Stateful execution slot tracking an active dialectic cycle."""

    session_id: str
    cycle_token: int = 0
    start_monotonic: float = 0.0
    fired_turn: int = 0
    status: ExecutionSlotState = ExecutionSlotState.IDLE
    timeout_seconds: float = 30.0


@dataclass(frozen=True)
class DialecticPendingResult:
    """Staged dialectic inference result awaiting consumption or pivot invalidation."""

    session_id: str
    cycle_token: int
    fired_turn: int
    fired_monotonic: float
    content: str
    fingerprint: str


@dataclass(frozen=True)
class DialecticLivenessAuditLog:
    """Immutable audit record for lifecycle transitions and discard events."""

    event_id: str
    session_id: str
    action: str
    turn: int
    detail: str
    timestamp_monotonic: float


@dataclass(frozen=True)
class LivenessTelemetry:
    """Telemetry snapshot of dialectic liveness state and counters."""

    session_id: str
    current_turn: int
    effective_cadence: int
    empty_streak: int
    slot_state: str
    active_cycle_token: int
    total_fires: int = 0
    dead_threads_recovered: int = 0
    stale_pivots_discarded: int = 0
    stale_tokens_rejected: int = 0
    successful_consumptions: int = 0
    audit_events: tuple[DialecticLivenessAuditLog, ...] = field(default_factory=tuple)
