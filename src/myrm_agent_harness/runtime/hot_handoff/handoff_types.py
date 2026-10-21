"""Strongly typed data contracts for local-to-cloud task hot handoff and input integrity verification.

[OUTPUT]
- HandoffPhase: State progression of a hot migration operation.
- ExecutionEnvironment: Execution environment tier (LOCAL_DESKTOP, CLOUD_SANDBOX).
- MaterialDigest: Cryptographic input artifact digest (SHA-256 and byte size).
- HandoffPayload: Portable state machine payload and workspace delta metadata.
- HandoffReceipt: Audit receipt recording handoff outcome and material consistency.

[INPUT]
- __future__
- time
- dataclasses
- enum

[OUTPUT]
- HandoffPhase
- ExecutionEnvironment
- MaterialDigest
- HandoffPayload
- HandoffReceipt

[POS]
Strongly typed data contracts for local-to-cloud task hot handoff and input integrity verification.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class HandoffPhase(StrEnum):
    """Lifecycle phase of task hot handoff."""

    INITIALIZING = "initializing"
    LOCAL_FROZEN = "local_frozen"
    WORKSPACE_SYNCING = "workspace_syncing"
    INPUT_VERIFYING = "input_verifying"
    CLOUD_RUNNING = "cloud_running"
    RECALLING = "recalling"
    COMPLETED = "completed"
    FAILED = "failed"


class ExecutionEnvironment(StrEnum):
    """Runtime environment where task execution is currently hosted."""

    LOCAL_DESKTOP = "local_desktop"
    CLOUD_SANDBOX = "cloud_sandbox"


@dataclass(frozen=True)
class MaterialDigest:
    """Cryptographic signature and byte size of an input file or asset."""

    relative_path: str
    size_bytes: int
    sha256_hash: str
    verified_at: float = field(default_factory=time.time)

    def matches(self, other: MaterialDigest) -> bool:
        """Compare two digests for byte-exact and hash-exact equality."""
        return (
            self.relative_path == other.relative_path
            and self.size_bytes == other.size_bytes
            and self.sha256_hash.lower() == other.sha256_hash.lower()
        )


@dataclass(frozen=True)
class HandoffPayload:
    """Portable task execution state snapshot and input materials for remote relay."""

    handoff_id: str
    task_id: str
    session_id: str
    origin_env: ExecutionEnvironment
    target_env: ExecutionEnvironment
    frozen_step_index: int
    state_vector: dict[str, str | int | float | bool]
    materials: tuple[MaterialDigest, ...] = field(default_factory=tuple)
    delta_files: tuple[str, ...] = field(default_factory=tuple)
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class HandoffReceipt:
    """Cryptographic audit receipt recording handoff verification and transition."""

    handoff_id: str
    task_id: str
    phase: HandoffPhase
    is_success: bool
    material_consistency_passed: bool
    active_env: ExecutionEnvironment
    error_message: str | None = None
    transferred_bytes: int = 0
    duration_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)
