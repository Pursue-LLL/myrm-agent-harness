"""Types and models for ephemeral delta.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- DeltaActionKind: Action type for an ephemeral session delta.
- EphemeralDeltaItem: A lightweight, turn-scoped ephemeral delta to be attached to the Human tail.
- EphemeralDeltaBufferSnapshot: Snapshot representation of the active ephemeral delta buffer for a session.
- ReconciliationBatchReport: Audit report generated when ephemeral deltas are flushed to permanent storage.

[POS]
Types and models for ephemeral delta.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class DeltaActionKind(StrEnum):
    """Action type for an ephemeral session delta."""

    OVERRIDE = "override"
    ADD_FACT = "add_fact"
    RETRACT = "retract"


@dataclass(frozen=True)
class EphemeralDeltaItem:
    """A lightweight, turn-scoped ephemeral delta to be attached to the Human tail.

    Prompt-cache preservation guarantee:
    This item is never injected into the leading SystemPrompt, preserving the
    frozen prefix KV-Cache while overriding stale baseline facts during inference.
    """

    delta_id: str
    target_key: str
    content: str
    action: DeltaActionKind = DeltaActionKind.OVERRIDE
    turn_index: int = 0
    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    source: str = "user_explicit"
    confidence: float = 1.0


@dataclass(frozen=True)
class EphemeralDeltaBufferSnapshot:
    """Snapshot representation of the active ephemeral delta buffer for a session."""

    session_id: str
    deltas: list[EphemeralDeltaItem]
    frozen_snapshot_id: str | None = None
    total_chars: int = 0
    is_reconciled: bool = False


@dataclass(frozen=True)
class ReconciliationBatchReport:
    """Audit report generated when ephemeral deltas are flushed to permanent storage."""

    session_id: str
    reconciled_count: int
    overridden_count: int
    persisted_keys: list[str]
    elapsed_ms: float
    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
