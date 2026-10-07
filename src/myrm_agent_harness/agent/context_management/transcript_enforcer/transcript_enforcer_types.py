# ============================================================================
# Transcript Append-Only Invariant Enforcer Data Contracts (Item 169)
# Strong typing contracts for historical transcript byte-level immutability,
# violation categorization, turn snapshot fingerprints, and delta evolution.
# ============================================================================

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class ViolationKind(str, Enum):
    """Classification of append-only invariant violation."""

    CONTENT_MUTATED = "content_mutated"
    MESSAGE_TRUNCATED = "message_truncated"
    MESSAGE_DELETED = "message_deleted"
    MESSAGE_INSERTED_INTERMEDIATE = "message_inserted_intermediate"
    ROLE_CHANGED = "role_changed"


@dataclass(frozen=True, slots=True)
class MessageFingerprint:
    """Cryptographic hash fingerprint of an individual message in turn history."""

    index: int
    role: str
    content_sha256: str
    content_length: int


@dataclass(frozen=True, slots=True)
class ViolationRecord:
    """Record describing a specific breach of transcript immutability."""

    violation_kind: ViolationKind
    message_index: int
    expected_fingerprint: MessageFingerprint | None
    actual_content_preview: str
    detail: str


@dataclass(frozen=True, slots=True)
class TurnTranscriptSnapshot:
    """Immutable checkpoint of committed message sequence for a turn."""

    turn_index: int
    message_count: int
    aggregate_prefix_sha256: str
    fingerprints: tuple[MessageFingerprint, ...]
    captured_at_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(frozen=True, slots=True)
class AppendOnlyEnforcementResult:
    """Outcome of validating incoming message sequence against historical snapshot."""

    is_valid_append_only: bool
    appended_message_count: int
    violations: tuple[ViolationRecord, ...]
    diagnostic_message: str


@dataclass(frozen=True, slots=True)
class DeltaCorrectionNote:
    """Structured delta evolution message appended to tail without touching history."""

    target_message_index: int
    correction_summary: str
    rendered_delta_content: str
