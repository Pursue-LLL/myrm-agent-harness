"""Type contracts for single-kernel multi-transport decoupling and async-ack RPC protocol.

Defines schemas for kernel states, lifecycle event frames, async acknowledgments,
and transport mode specifications. Strictly adheres to 0 Any and typed dataclasses.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum


class TransportModeKind(StrEnum):
    """Transport presentation mode (One Kernel, Three Faces)."""

    INTERACTIVE = "interactive"
    PRINT_BATCH = "print_batch"
    RPC = "rpc"


class KernelLifecycleState(StrEnum):
    """Operational lifecycle state of the AgentSession kernel."""

    IDLE = "idle"
    QUEUED = "queued"
    PROCESSING = "processing"
    PAUSED = "paused"
    ABORTING = "aborting"
    ABORTED = "aborted"
    ERROR = "error"
    DISPOSED = "disposed"


class KernelEventType(StrEnum):
    """Event classifications emitted by the kernel event stream."""

    TASK_ACCEPTED = "task_accepted"
    TASK_STARTED = "task_started"
    THINKING_CHUNK = "thinking_chunk"
    TEXT_DELTA = "text_delta"
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_COMPLETED = "tool_call_completed"
    TASK_COMPLETED = "task_completed"
    TASK_ABORTED = "task_aborted"
    TASK_FAILED = "task_failed"
    STATE_CHANGED = "state_changed"


@dataclass(frozen=True, slots=True)
class KernelEventFrame:
    """Immutable sequence-numbered event emitted to the independent event stream."""

    event_id: str
    seq_id: int
    task_id: str
    event_type: KernelEventType
    payload: dict[str, str] = field(default_factory=dict)
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))


@dataclass(frozen=True, slots=True)
class AsyncAckFrame:
    """Immediate handshake acknowledgment returned before long-running task execution."""

    task_id: str
    accepted: bool
    status: KernelLifecycleState
    initial_seq_id: int
    session_id: str
    message: str = ""
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self) -> dict[str, object]:
        """Convert acknowledgment frame to serializable dictionary."""
        return {
            "task_id": self.task_id,
            "accepted": self.accepted,
            "status": self.status.value,
            "initial_seq_id": self.initial_seq_id,
            "session_id": self.session_id,
            "message": self.message,
            "timestamp_ms": self.timestamp_ms,
        }


@dataclass(frozen=True, slots=True)
class KernelCommandRequest:
    """Standardized prompt or steering request submitted into the kernel."""

    prompt: str
    task_id: str = field(default_factory=lambda: f"task-{uuid.uuid4().hex[:8]}")
    session_id: str = "default_session"
    attachments: tuple[str, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReattachResumeRequest:
    """Client reconnection request to replay missed stream events."""

    task_id: str
    last_seen_seq_id: int
    session_id: str
