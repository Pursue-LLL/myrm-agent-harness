# [INPUT]: None
# [OUTPUT]: ActiveWorkerDescriptor, ContextTurnMessage, SanitizedReplayResult, SteerDispatchResult, SteerMessageKind, SteerResolutionStatus, WorkerLifecycleState
# [POS]: agent/context_management/steer_after_compression/steer_compression_types.py

"""Domain contracts for post-compaction steering and out-of-band message sanitization.

[INPUT]
- None (Self-contained strongly typed domain definitions).

[OUTPUT]
- WorkerLifecycleState: Lifecycle states of execution workers across compaction.
- SteerMessageKind: Classification of in-band vs out-of-band messages.
- SteerResolutionStatus: Resolution outcome status of steering dispatch.
- ActiveWorkerDescriptor: Strongly typed representation of an execution worker.
- SteerDispatchResult: Audit receipt for steering instruction delivery.
- ContextTurnMessage: Normalized conversation turn model with OOB flagging.
- SanitizedReplayResult: Filtered context replay result stripping OOB messages while preserving persistence.

[POS]
Domain contracts for post-compaction worker steering and OOB context hygiene.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import time


class WorkerLifecycleState(str, Enum):
    """Lifecycle states of an active execution worker."""

    IDLE = "idle"
    RUNNING = "running"
    FINALIZING = "finalizing"
    SETTLED = "settled"
    STOPPED = "stopped"


class SteerMessageKind(str, Enum):
    """Categories of steer and context messages."""

    IN_BAND_PROMPT = "in_band_prompt"
    OUT_OF_BAND_STEER = "out_of_band_steer"
    OUT_OF_BAND_STOP = "out_of_band_stop"
    SYSTEM_DIRECTIVE = "system_directive"


class SteerResolutionStatus(str, Enum):
    """Outcomes when resolving a target worker for a steer instruction."""

    RESOLVED_DIRECT = "resolved_direct"
    RESOLVED_COMPACTED_ALIAS = "resolved_compacted_alias"
    WORKER_NOT_FOUND = "worker_not_found"
    WORKER_ALREADY_SETTLED = "worker_already_settled"
    STOPPED_IN_PREFLIGHT = "stopped_in_preflight"


@dataclass
class ActiveWorkerDescriptor:
    """Descriptor of an active execution worker bound to a session."""

    worker_id: str
    session_id: str
    state: WorkerLifecycleState = WorkerLifecycleState.RUNNING
    active_run_id: str = ""
    registered_at_utc: float = field(default_factory=time.time)
    settled_at_utc: float | None = None
    steer_inbox: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SteerDispatchResult:
    """Audit receipt describing the dispatch of a steer directive to a worker."""

    status: SteerResolutionStatus
    worker_id: str | None
    session_id: str
    message: str
    kind: SteerMessageKind
    timestamp_utc: float
    delivered: bool


@dataclass(frozen=True)
class ContextTurnMessage:
    """Individual conversation message turn with persistence and replay hygiene attributes."""

    message_id: str
    role: str
    content: str
    is_oob: bool = False
    kind: SteerMessageKind = SteerMessageKind.IN_BAND_PROMPT
    created_at_utc: float = field(default_factory=time.time)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SanitizedReplayResult:
    """Replay assembly result with OOB management instructions stripped."""

    sanitized_messages: list[ContextTurnMessage]
    total_persisted_count: int
    stripped_oob_count: int
    is_clean: bool
    audit_digest: str
