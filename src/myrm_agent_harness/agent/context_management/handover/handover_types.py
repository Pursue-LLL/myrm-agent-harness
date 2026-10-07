"""Types and models for handover.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- DeviceKind: Client device platform classification.
- AttachmentMode: Device attachment permission mode.
- SessionExecutionState: Lifecycle state of an active session in runtime.
- DeviceInfo: Connected client device identity and metadata.
- TerminalOutputChunk: Incremental chunk of terminal output stream (stdout/stderr).
- HandoverSessionHandle: Descriptor for an active session available for cross-device handover.
- AttachmentCatchupSnapshot: Instantaneous snapshot replayed to new device upon attach.

[POS]
Types and models for handover.
"""

# ============================================================================
# Cross-Device Session Handover & Attachment Data Contracts (Item 159)
# Strong typing contracts for bidirectional cross-device session attachment,
# terminal PTY ring buffer catch-up, and background detachment handover.
# ============================================================================

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class DeviceKind(str, Enum):
    """Client device platform classification."""

    MOBILE = "mobile"
    DESKTOP = "desktop"
    WEB = "web"
    CLI = "cli"


class AttachmentMode(str, Enum):
    """Device attachment permission mode."""

    EXCLUSIVE_STEER = "exclusive_steer"  # Exclusive active execution and steering control
    SHARED_OBSERVE = "shared_observe"  # Read-only real-time observation mirroring


class SessionExecutionState(str, Enum):
    """Lifecycle state of an active session in runtime."""

    RUNNING = "running"
    WAITING_USER_INPUT = "waiting_user_input"
    IDLE = "idle"
    COMPLETED = "completed"
    DETACHED_BACKGROUND = "detached_background"


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """Connected client device identity and metadata."""

    device_id: str
    kind: DeviceKind
    device_name: str
    connected_at_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    last_heartbeat_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(frozen=True, slots=True)
class TerminalOutputChunk:
    """Incremental chunk of terminal output stream (stdout/stderr)."""

    chunk_id: int
    stream: str  # "stdout" | "stderr"
    content: str
    timestamp_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(frozen=True, slots=True)
class HandoverSessionHandle:
    """Descriptor for an active session available for cross-device handover."""

    session_id: str
    title: str
    state: SessionExecutionState
    active_controller_device_id: str | None
    attached_observers: tuple[str, ...]
    created_at_iso: str
    updated_at_iso: str


@dataclass(frozen=True, slots=True)
class AttachmentCatchupSnapshot:
    """Instantaneous snapshot replayed to new device upon attach."""

    session_id: str
    state: SessionExecutionState
    history_output_chunks: tuple[TerminalOutputChunk, ...]
    last_chunk_id: int
    active_controller_device_id: str | None
    reconnect_token: str
