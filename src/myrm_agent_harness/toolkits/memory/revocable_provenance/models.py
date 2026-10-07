"""[POS]: src/myrm_agent_harness/toolkits/memory/revocable_provenance/models.py
[INPUT]: Provenance attributes, memory statements, dreaming session metadata, and timestamps.
[OUTPUT]: Immutable models for provenance-qualified memories, dreaming diary entries, and revocation results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal


@dataclass(frozen=True)
class ProvenanceMetadata:
    """Exact source linkage anchoring a long-term memory to raw conversational turns."""

    session_id: str
    message_id: str
    turn_index: int
    quote_snippet: str
    extracted_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    confidence_score: float = 1.0


@dataclass
class ProvenanceQualifiedMemory:
    """Promoted long-term memory asset with strict provenance qualification and revocation state."""

    memory_id: str
    statement: str
    category: str
    provenance: ProvenanceMetadata
    is_revoked: bool = False
    revoked_at: datetime | None = None
    revocation_reason: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def fingerprint(self) -> str:
        """Deterministic fingerprint binding the memory statement to its source message."""
        return f"{self.provenance.session_id}:{self.provenance.message_id}:{self.statement.strip().lower()}"


@dataclass(frozen=True)
class ForgetResult:
    """Outcome report of a targeted atomic memory revocation."""

    memory_id: str
    revoked: bool
    source_session_id: str
    source_message_id: str
    message: str
    transcript_intact: bool = True


@dataclass
class ProvenanceDreamDiaryEntry:
    """Transparent diary log capturing background memory distillation, pruning, and promotion."""

    dream_id: str
    agent_id: str
    scanned_turns: int
    promoted_memory_ids: list[str] = field(default_factory=list)
    pruned_duplicates_count: int = 0
    duration_ms: float = 0.0
    status: Literal["completed", "skipped", "failed"] = "completed"
    notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
