"""Strongly typed contracts for sandbox session pause, resume, and snapshot restoration.

[INPUT]
- None (Domain contract definitions).

[OUTPUT]
- SessionLifecycleState: Lifecycle states of a sandbox execution session.
- PauseResumeActionKind: Supported lifecycle operations (pause, in-place resume, snapshot resume, terminate).
- SandboxSnapshotManifest: Read-only immutable snapshot manifest with sha256 checksum.
- PauseResumeReceipt: Structured operation outcome receipt.
- SandboxSessionRecord: Active runtime session entity.
- compute_state_checksum: Deterministic sha256 checksum calculation for state dictionaries.

[POS]
Domain models for sandbox pause/resume and snapshot branching.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import time


class SessionLifecycleState(str, Enum):
    """Lifecycle states of a sandbox session."""

    RUNNING = "running"
    PAUSED = "paused"
    TERMINATED = "terminated"


class PauseResumeActionKind(str, Enum):
    """Action categories for session lifecycle operations."""

    PAUSE = "pause"
    RESUME_IN_PLACE = "resume_in_place"
    RESUME_FROM_SNAPSHOT = "resume_from_snapshot"
    TERMINATE = "terminate"


def compute_state_checksum(state: dict[str, str]) -> str:
    """Compute deterministic SHA-256 checksum for a state dictionary.

    Args:
        state: String-keyed dictionary representing session memory or environment variables.

    Returns:
        Hex-encoded SHA-256 digest string.
    """
    sorted_items = sorted(state.items())
    payload = json.dumps(sorted_items, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SandboxSnapshotManifest:
    """Read-only immutable snapshot manifest of a sandbox session."""

    snapshot_id: str
    source_session_id: str
    created_at_utc: float
    state_dump: dict[str, str]
    checksum: str
    metadata: dict[str, str] = field(default_factory=dict)

    def verify_integrity(self) -> bool:
        """Verify that the state dump matches the recorded sha256 checksum."""
        return compute_state_checksum(self.state_dump) == self.checksum


@dataclass(frozen=True)
class PauseResumeReceipt:
    """Structured audit receipt returned by pause, resume, and snapshot operations."""

    action: PauseResumeActionKind
    session_id: str
    source_session_id: str | None
    previous_state: SessionLifecycleState
    current_state: SessionLifecycleState
    timestamp_utc: float
    snapshot_id: str | None
    success: bool
    message: str
    state_checksum: str | None


@dataclass
class SandboxSessionRecord:
    """Active runtime representation of a sandbox session."""

    session_id: str
    state: SessionLifecycleState = SessionLifecycleState.RUNNING
    current_memory: dict[str, str] = field(default_factory=dict)
    turn_count: int = 0
    created_at_utc: float = field(default_factory=time.time)
    last_paused_at_utc: float | None = None
    last_resumed_at_utc: float | None = None
    parent_snapshot_id: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)
