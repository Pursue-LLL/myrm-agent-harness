"""Strongly typed contracts for Handoff-then-Compact checkpoint pipeline.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- HandoffCompactStage: Lifecycle stages of the handoff-then-compact procedure.
- CheckpointRenderFormat: Supported presentation formats for task checkpoints.
- TaskCheckpoint: Six-dimensional structured task checkpoint ensuring zero-loss context compaction.
- HandoffThenCompactResult: Execution receipt for two-phase handoff-then-compact pipeline.

[POS]
Strongly typed contracts for Handoff-then-Compact checkpoint pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json


class HandoffCompactStage(str, Enum):
    """Lifecycle stages of the handoff-then-compact procedure."""

    COMPILED = "compiled"
    PERSISTED = "persisted"
    COMPACTED = "compacted"
    RESTORED = "restored"


class CheckpointRenderFormat(str, Enum):
    """Supported presentation formats for task checkpoints."""

    STRUCTURED_MARKDOWN = "structured_markdown"
    JSON = "json"


@dataclass(frozen=True)
class TaskCheckpoint:
    """Six-dimensional structured task checkpoint ensuring zero-loss context compaction."""

    session_id: str
    ultimate_goal: str
    completed_items: list[str] = field(default_factory=list)
    important_constraints: list[str] = field(default_factory=list)
    modified_files: list[str] = field(default_factory=list)
    pending_issues: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    created_at_epoch_ms: int = 0
    checkpoint_hash: str = ""

    def calculate_digest(self) -> str:
        """Calculate deterministic SHA-256 digest over checkpoint fields."""
        payload = {
            "session_id": self.session_id,
            "ultimate_goal": self.ultimate_goal,
            "completed_items": sorted(self.completed_items),
            "important_constraints": sorted(self.important_constraints),
            "modified_files": sorted(self.modified_files),
            "pending_issues": sorted(self.pending_issues),
            "next_actions": sorted(self.next_actions),
        }
        serialized = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class HandoffThenCompactResult:
    """Execution receipt for two-phase handoff-then-compact pipeline."""

    session_id: str
    checkpoint: TaskCheckpoint
    checkpoint_uri: str
    pre_compact_tokens: int
    post_compact_tokens: int
    tokens_reduced: int
    compression_ratio: float
    stage: HandoffCompactStage
    success: bool
    error_message: str | None = None
