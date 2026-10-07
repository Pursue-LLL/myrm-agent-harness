"""Strongly typed contracts for IPC Message Clamping and Large Artifact Spillover Suite (Item 216).

[INPUT]
- None (self-contained, standard library only).

[OUTPUT]
- IpcClampingAction: Routing decision for inter-agent messages.
- SpilloverArtifactSpec: Descriptor of an offloaded large communication payload.
- IpcClampingOutcome: Telemetry outcome with effective rewritten message and spillover metadata.
- IpcClampingConfig: Tunable configurations for clamping floors, storage prefixes, and previews.

[POS]
- Prevents context window detonation and downstream agent amnesia in multi-agent workflows
- by clamping oversized IPC payloads and spilling large data into read-only artifact files.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field


class IpcClampingAction(str, enum.Enum):
    """Action taken by the IPC gateway when evaluating an inter-agent message."""

    PASSTHROUGH = "passthrough"
    SPILLOVER_REPLACED = "spillover_replaced"
    REJECTED_OVERSIZE = "rejected_oversize"


@dataclass(frozen=True, slots=True)
class SpilloverArtifactSpec:
    """Strongly typed descriptor representing an offloaded IPC payload stored in sandbox volume."""

    artifact_id: str
    sender_agent_id: str
    receiver_agent_id: str
    artifact_path: str
    sha256: str
    original_char_count: int
    summary: str
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Serializes spillover artifact spec to dictionary."""
        return {
            "artifact_id": self.artifact_id,
            "sender_agent_id": self.sender_agent_id,
            "receiver_agent_id": self.receiver_agent_id,
            "artifact_path": self.artifact_path,
            "sha256": self.sha256,
            "original_char_count": self.original_char_count,
            "summary": self.summary,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class IpcClampingOutcome:
    """Comprehensive telemetry report for clamped inter-agent communication."""

    action: IpcClampingAction
    sender_agent_id: str
    receiver_agent_id: str
    effective_message: str
    original_char_count: int
    effective_char_count: int
    spillover_artifact: SpilloverArtifactSpec | None
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, object]:
        """Serializes outcome to dictionary."""
        return {
            "action": self.action.value,
            "sender_agent_id": self.sender_agent_id,
            "receiver_agent_id": self.receiver_agent_id,
            "effective_message": self.effective_message,
            "original_char_count": self.original_char_count,
            "effective_char_count": self.effective_char_count,
            "spillover_artifact": (
                self.spillover_artifact.to_dict() if self.spillover_artifact else None
            ),
            "duration_ms": self.duration_ms,
        }


@dataclass(slots=True)
class IpcClampingConfig:
    """Configuration governing IPC payload clamping and artifact spillover behavior."""

    enabled: bool = True
    max_clamped_chars: int = 4000
    summary_preview_chars: int = 400
    artifact_storage_prefix: str = "/workspace/artifacts/spillover"
    auto_spillover: bool = True
