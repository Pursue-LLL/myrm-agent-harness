"""Data types and protocol models for remote sandbox live thread physical compaction.

Defines wire formats, synchronization signals, acknowledgments, and
drift telemetry for host-to-remote sandbox live thread compaction.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- CompactionSyncStatus: Synchronization outcome status between host and remote live thread.
- LiveThreadCompactionSignal: Outbound compaction signal dispatched from host to remote live thread.
- LiveThreadCompactionResult: Inbound acknowledgment and telemetry received from remote live thread.
- RemoteThreadSnapshot: Physical state snapshot of a live remote sandbox thread.

[POS]
Data types and protocol models for remote sandbox live thread physical compaction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class CompactionSyncStatus(StrEnum):
    """Synchronization outcome status between host and remote live thread."""

    SUCCESS = "success"
    PARTIAL_DRIFT = "partial_drift"
    REJECTED_STALE = "rejected_stale"
    FAILED_ROLLBACK = "failed_rollback"


@dataclass(frozen=True)
class LiveThreadCompactionSignal:
    """Outbound compaction signal dispatched from host to remote live thread."""

    session_id: str
    thread_id: str
    sequence_number: int
    compacted_summary: str
    retained_tail_turns: tuple[str, ...]
    target_token_budget: int
    timestamp: float
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LiveThreadCompactionResult:
    """Inbound acknowledgment and telemetry received from remote live thread."""

    status: CompactionSyncStatus
    thread_id: str
    sequence_number: int
    before_token_count: int
    after_token_count: int
    compression_ratio: float
    drift_percentage: float
    ack_timestamp: float
    error_message: str | None = None
    applied_summary: str | None = None


@dataclass(frozen=True)
class RemoteThreadSnapshot:
    """Physical state snapshot of a live remote sandbox thread."""

    thread_id: str
    total_turns: int
    active_token_count: int
    last_applied_sequence: int
    history_messages: tuple[str, ...]
    is_compacted: bool
