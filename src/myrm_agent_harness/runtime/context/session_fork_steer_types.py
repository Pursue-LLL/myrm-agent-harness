"""Session fork and in-flight steer control types.

Defines schemas for non-blocking background forks (/bg), context snapshot
explorations (/btw), in-flight steering interventions (/steer), and asynchronous
pipe-back payloads.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class ForkCommandKind(StrEnum):
    """Classification of background session fork command."""

    BG = "bg"
    BTW = "btw"
    STEER = "steer"


class ForkSessionState(StrEnum):
    """Lifecycle state of a background forked session."""

    STAGED = "staged"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class BackgroundForkDescriptor:
    """Descriptor of an asynchronous background session derived from a main session."""

    fork_id: str
    parent_session_id: str
    kind: ForkCommandKind
    prompt: str
    state: ForkSessionState = ForkSessionState.STAGED
    snapshot_context: str | None = None
    result_summary: str | None = None
    created_at_ms: int = 0
    completed_at_ms: int | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class InFlightSteerInstruction:
    """Human steering guidance injected in-flight before the next decision checkpoint."""

    steer_id: str
    session_id: str
    instruction: str
    priority_weight: int = 10
    created_at_ms: int = 0
    consumed_at_ms: int | None = None


@dataclass(frozen=True)
class PipeBackPayload:
    """Completed result payload piped back from a background session to the main session."""

    pipe_id: str
    fork_id: str
    parent_session_id: str
    kind: ForkCommandKind
    output_content: str
    status: ForkSessionState
    artifacts: tuple[str, ...] = field(default_factory=tuple)
    piped_at_ms: int = 0
