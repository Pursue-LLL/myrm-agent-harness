"""SSOT Data contracts and schemas for Continual Session Overlay.

[INPUT]
- enum, dataclasses, time (POS: Python standard library)

[OUTPUT]
- OverlayScope: SESSION or TASK scope boundary
- OverlayTargetType: Four shell types (PROMPT_PATCH, TEMP_SKILL_VARIANT, SUBAGENT_CONFIG, PROCEDURAL_MEMORY)
- OverlayStatus: Lifecycle states (ACTIVE, EXPIRED, ROLLED_BACK, ADOPTED)
- SessionOverlay: Immutable record for fault-site session shell modifications
- SessionOverlaySnapshot: Snapshot state for physical rollback

[POS]
Continual Harness fault-site session overlay schemas. Provides deterministic,
isolated runtime shell modification contracts with strict TTL and rollback safety.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field


class OverlayScope(enum.StrEnum):
    """Scope boundary for session overlay application."""

    SESSION = "session"  # Active across current conversation session
    TASK = "task"  # Active only within specific child subagent task


class OverlayTargetType(enum.StrEnum):
    """Four canonical shell types for fault-site runtime modification."""

    PROMPT_PATCH = "prompt_patch"  # Dynamic tail directive or tone adjustment
    TEMP_SKILL_VARIANT = "skill_variant"  # Runtime argument adapter / field stripping
    SUBAGENT_CONFIG = "subagent_config"  # Mid-run subagent budget/tool restriction
    PROCEDURAL_MEMORY = "procedural_memory"  # Negative pattern constraint injection


class OverlayStatus(enum.StrEnum):
    """Lifecycle state machine for session overlay."""

    ACTIVE = "active"  # Currently applied to execution pipeline
    EXPIRED = "expired"  # TTL reached zero, gracefully de-escalated
    ROLLED_BACK = "rolled_back"  # Trial failed, physically reverted to snapshot
    ADOPTED = "adopted"  # Verified by task success, candidate for Growth review


@dataclass(frozen=True, slots=True)
class SessionOverlay:
    """Immutable fault-site session overlay specification."""

    overlay_id: str
    scope: OverlayScope
    target_type: OverlayTargetType
    target_name: str  # Tool name, subagent task ID, or 'global'
    patch_payload: dict[str, object]  # Adapter rules, constraints, or config delta
    ttl_turns: int = 3  # Remaining turns before expiration
    max_attempts: int = 1  # Single-shot trial budget before rollback
    attempt_count: int = 0  # Number of attempts executed under this overlay
    failure_signature: str = ""  # Root cause error signature that triggered this
    created_at_turn: int = 0
    created_at_timestamp: float = field(default_factory=time.time)
    status: OverlayStatus = OverlayStatus.ACTIVE
    snapshot_id: str = ""  # ID of original state snapshot for rollback

    def is_alive(self) -> bool:
        """Check whether overlay is active with non-zero TTL."""
        return self.status == OverlayStatus.ACTIVE and self.ttl_turns > 0

    @property
    def shell_type(self) -> OverlayTargetType:
        return self.target_type

    @property
    def patch_data(self) -> dict[str, object]:
        return self.patch_payload

    @property
    def remaining_turns(self) -> int:
        return self.ttl_turns

    @property
    def trigger_reason(self) -> str:
        return self.failure_signature

    def to_dict(self) -> dict[str, object]:
        """Serialize overlay to pure dictionary for audit and telemetry."""
        advisory = str(
            self.patch_payload.get("advisory_instruction")
            or self.patch_payload.get("negative_constraint")
            or ""
        )
        return {
            "overlay_id": self.overlay_id,
            "overlayId": self.overlay_id,
            "scope": self.scope.value,
            "target_type": self.target_type.value,
            "shell_type": self.target_type.value,
            "shellType": self.target_type.value,
            "target_name": self.target_name,
            "patch_payload": dict(self.patch_payload),
            "patch_data": dict(self.patch_payload),
            "ttl_turns": self.ttl_turns,
            "remaining_turns": self.ttl_turns,
            "remainingTurns": self.ttl_turns,
            "max_attempts": self.max_attempts,
            "attempt_count": self.attempt_count,
            "failure_signature": self.failure_signature,
            "trigger_reason": self.failure_signature,
            "triggerReason": self.failure_signature,
            "advisory_instruction": advisory,
            "advisoryText": advisory,
            "created_at_turn": self.created_at_turn,
            "created_at_timestamp": self.created_at_timestamp,
            "status": self.status.value,
            "snapshot_id": self.snapshot_id,
        }


@dataclass(frozen=True, slots=True)
class SessionOverlaySnapshot:
    """Pre-overlay snapshot capture for physical state rollback."""

    snapshot_id: str
    target_name: str
    original_args_example: dict[str, object] = field(default_factory=dict)
    captured_at: float = field(default_factory=time.time)


DEFAULT_OVERLAY_TTL: int = 3
DEFAULT_OVERLAY_TTL_TURNS: int = 3
