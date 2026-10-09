"""Contracts and data models for terminal-missing silent end stream reconciliation.

[INPUT]
- None (pure domain types and enum contracts).

[OUTPUT]
- Exports enumerations and dataclasses for terminal event classification,
  server run reservations, reconcile verdicts, tickets, and outcomes.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.silent_end_reconcile
- Module: silent_end_types.py
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Optional, Sequence


class TerminalEventKind(str, Enum):
    """Business terminal event kinds signaling authentic completion or termination."""

    MESSAGE_END = "message_end"
    RUN_FINISHED = "run_finished"
    RUN_FAILED = "run_failed"
    RUN_CANCELLED = "run_cancelled"


class StreamRunStatus(str, Enum):
    """Server-side reservation state of an active agent stream run."""

    ACTIVE_PROCESSING = "active_processing"
    COMPLETED_ARCHIVED = "completed_archived"
    FAILED_ABORTED = "failed_aborted"
    UNKNOWN_EXPIRED = "unknown_expired"


class ReconcileVerdict(str, Enum):
    """Outcome of reconciling a client-side stream that ended without a terminal event."""

    CONFIRMED_TERMINATED = "confirmed_terminated"
    STILL_RUNNING_RESUME = "still_running_resume"
    UNRECOVERABLE_ABORT = "unrecoverable_abort"


@dataclass(frozen=True)
class SilentEndTicket:
    """Diagnostic ticket generated when an SSE connection completes without terminal envelopes."""

    session_id: str
    run_id: str
    last_event_id: Optional[str]
    total_chunks_received: int
    detected_at_epoch: float
    raw_interruption_reason: str


@dataclass(frozen=True)
class ServerRunReservation:
    """Server-side proof record confirming whether an operation is still alive or completed."""

    session_id: str
    run_id: str
    status: StreamRunStatus
    final_output_digest: Optional[str] = None
    error_diagnostic: Optional[str] = None
    updated_at_epoch: float = 0.0


@dataclass(frozen=True)
class ReconcileOutcome:
    """Final reconciliation result indicating how the client should settle its local state."""

    ticket: SilentEndTicket
    verdict: ReconcileVerdict
    server_reservation: Optional[ServerRunReservation]
    should_clear_loading_state: bool
    recovery_guidance: str


@dataclass(frozen=True)
class SilentEndReconcileConfig:
    """Configuration options governing silent end detection and reconciliation probing."""

    recognized_terminal_events: Sequence[str] = (
        TerminalEventKind.MESSAGE_END.value,
        TerminalEventKind.RUN_FINISHED.value,
        TerminalEventKind.RUN_FAILED.value,
        TerminalEventKind.RUN_CANCELLED.value,
    )
    max_reconcile_retries: int = 3
    reconcile_timeout_seconds: float = 5.0
    auto_settle_unrecoverable_after_seconds: float = 15.0
