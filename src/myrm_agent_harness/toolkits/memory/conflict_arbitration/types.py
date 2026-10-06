# [POS] src/myrm_agent_harness/toolkits/memory/conflict_arbitration/types.py
# [INPUT] standard library typing, enum, dataclasses, datetime, hashlib
# [OUTPUT] ConflictResolutionKind, ConflictSeverity, SemanticConflictRecord, UserConfirmedFreezeLock, ArbitrationAssessment, HumanArbitrationDecision, UserConfirmedFreezeViolationError

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class ConflictResolutionKind(StrEnum):
    """Resolution kind determined by semantic arbitration or human judgment."""

    MERGE = "merge"
    OVERRIDE = "override"
    CONTRADICTION = "contradiction"
    FREEZE_BLOCKED = "freeze_blocked"


class ConflictSeverity(StrEnum):
    """Severity level of semantic divergence."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class UserConfirmedFreezeViolationError(Exception):
    """Raised when an automated process attempts to overwrite or alter a user-confirmed frozen memory."""

    def __init__(self, memory_id: str, reason: str) -> None:
        super().__init__(f"User confirmed frozen memory '{memory_id}' is immutable: {reason}")
        self.memory_id: str = memory_id
        self.reason: str = reason


@dataclass(frozen=True)
class UserConfirmedFreezeLock:
    """Represents an immutable freeze lock placed upon user-confirmed facts."""

    memory_id: str
    frozen_content: str
    confirmed_by: str
    confirmed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    is_active: bool = True
    lock_version: int = 1
    immutable_hash: str = field(default="")

    def __post_init__(self) -> None:
        if not self.immutable_hash:
            computed = hashlib.sha256(
                f"{self.memory_id}:{self.frozen_content}:{self.confirmed_by}:{self.lock_version}".encode()
            ).hexdigest()
            object.__setattr__(self, "immutable_hash", computed)

    def verify_integrity(self) -> bool:
        """Verify that the immutable hash matches the lock payload."""
        expected = hashlib.sha256(
            f"{self.memory_id}:{self.frozen_content}:{self.confirmed_by}:{self.lock_version}".encode()
        ).hexdigest()
        return self.immutable_hash == expected


@dataclass(frozen=True)
class SemanticConflictRecord:
    """Detailed record of a detected conflict between existing memory and incoming candidate fact."""

    conflict_id: str
    entity_key: str
    attribute_name: str
    existing_memory_id: str
    existing_fact_text: str
    candidate_fact_text: str
    severity: ConflictSeverity = ConflictSeverity.MEDIUM
    detected_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    source_context: str = ""
    is_existing_frozen: bool = False


@dataclass(frozen=True)
class ArbitrationAssessment:
    """Assessment produced by the semantic arbitrator."""

    conflict_id: str
    resolution_kind: ConflictResolutionKind
    confidence: float
    reasoning: str
    suggested_text: str
    requires_human_confirmation: bool


@dataclass(frozen=True)
class HumanArbitrationDecision:
    """Decision submitted by human operator to finalize a conflict."""

    conflict_id: str
    chosen_resolution: ConflictResolutionKind
    final_fact_text: str
    operator_id: str
    should_freeze_lock: bool = True
    comment: str = ""
    decided_at: datetime = field(default_factory=lambda: datetime.now(UTC))
