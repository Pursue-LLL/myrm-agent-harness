"""Data models for Grounded Dreaming and Surgical Memory Unlearning.

Defines schemas for cross-session consolidation candidates, human-readable
dream diary entries, and audit reports for surgical session memory erasure.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class DreamDiaryStatus(StrEnum):
    """Lifecycle status of an AI cognitive insight in the dream diary."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass(frozen=True)
class DreamSessionFragment:
    """A fragment of memories and context extracted from a single chat session."""

    session_id: str
    memories: list[dict[str, object]] = field(default_factory=list)
    topic_keywords: list[str] = field(default_factory=list)
    chat_turn_count: int = 0
    extracted_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class DreamDiaryEntry:
    """An evolved cognitive insight distilled from across multiple sessions."""

    entry_id: str
    cognitive_statement: str
    source_session_ids: list[str]
    evidence_snippets: list[str]
    confidence_delta: float
    status: DreamDiaryStatus = DreamDiaryStatus.PENDING
    rejection_reason: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create(
        cls,
        cognitive_statement: str,
        source_session_ids: list[str],
        evidence_snippets: list[str],
        confidence_delta: float = 0.2,
    ) -> DreamDiaryEntry:
        """Factory method generating a unique entry identifier."""
        return cls(
            entry_id=f"dream_{uuid.uuid4().hex[:12]}",
            cognitive_statement=cognitive_statement,
            source_session_ids=list(source_session_ids),
            evidence_snippets=list(evidence_snippets),
            confidence_delta=confidence_delta,
            status=DreamDiaryStatus.PENDING,
        )

    def to_dict(self) -> dict[str, object]:
        """Convert entry into serializable dictionary representation."""
        return {
            "entry_id": self.entry_id,
            "cognitive_statement": self.cognitive_statement,
            "source_session_ids": self.source_session_ids,
            "evidence_snippets": self.evidence_snippets,
            "confidence_delta": self.confidence_delta,
            "status": self.status.value,
            "rejection_reason": self.rejection_reason,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> DreamDiaryEntry:
        """Construct entry from dictionary representation."""
        created_val = data.get("created_at")
        created_dt = (
            datetime.fromisoformat(str(created_val))
            if created_val
            else datetime.now(UTC)
        )
        status_val = str(data.get("status", "pending"))
        status_enum = DreamDiaryStatus(status_val) if status_val in DreamDiaryStatus._value2member_map_ else DreamDiaryStatus.PENDING

        raw_sessions = data.get("source_session_ids")
        sessions = [str(s) for s in raw_sessions] if isinstance(raw_sessions, list) else []

        raw_evidences = data.get("evidence_snippets")
        evidences = [str(e) for e in raw_evidences] if isinstance(raw_evidences, list) else []

        rejection = data.get("rejection_reason")
        rejection_str = str(rejection) if rejection is not None else None

        return cls(
            entry_id=str(data.get("entry_id", f"dream_{uuid.uuid4().hex[:12]}")),
            cognitive_statement=str(data.get("cognitive_statement", "")),
            source_session_ids=sessions,
            evidence_snippets=evidences,
            confidence_delta=float(data.get("confidence_delta", 0.2)),  # type: ignore[arg-type]
            status=status_enum,
            rejection_reason=rejection_str,
            created_at=created_dt,
        )


@dataclass(frozen=True)
class SurgicalUnlearnReport:
    """Audit report for surgical session memory erasure."""

    session_id: str
    unlearned_memory_ids: list[str]
    purged_vector_count: int
    status: str
    preserved_chat_turns: int
    execution_time_ms: float

    def to_dict(self) -> dict[str, object]:
        """Convert report to serializable dictionary representation."""
        return {
            "session_id": self.session_id,
            "unlearned_memory_ids": self.unlearned_memory_ids,
            "purged_vector_count": self.purged_vector_count,
            "status": self.status,
            "preserved_chat_turns": self.preserved_chat_turns,
            "execution_time_ms": self.execution_time_ms,
        }
