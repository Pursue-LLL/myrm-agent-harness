# [POS]: src/myrm_agent_harness/toolkits/memory/procedure_experience/models.py
# [INPUT]: None (Domain models for Procedure-Shaped Experience Protocol & Dual-Node Retrieval)
# [OUTPUT]: RetrievalNodeKind, ProcedureMemoryEntry, DualNodeRetrievalQuery, DualNodeRetrievalResult

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class RetrievalNodeKind(StrEnum):
    """Lifecycle call sites for memory injection."""

    FIRST_USER = "first_user"
    PRE_WRITE = "pre_write"


@dataclass
class ProcedureMemoryEntry:
    """Core domain model implementing the 8-field procedure-shaped memory protocol."""

    entry_id: str
    name: str
    retrieval_anchor: str
    operation_intent: str
    preconditions: list[str] = field(default_factory=list)
    immutable_boundary: list[str] = field(default_factory=list)
    procedure_steps: list[str] = field(default_factory=list)
    write_field_provenance: dict[str, str] = field(default_factory=dict)
    anti_patterns: list[str] = field(default_factory=list)
    applicability: list[str] = field(default_factory=list)
    negative_applicability: list[str] = field(default_factory=list)
    confidence: float = 1.0
    source_session_id: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class DualNodeRetrievalQuery:
    """Query payload targeting either first-user intent or pre-write intercept nodes."""

    query_text: str
    node_kind: RetrievalNodeKind = RetrievalNodeKind.FIRST_USER
    top_n: int = 2
    scope_filter: str | None = None


@dataclass
class DualNodeRetrievalResult:
    """Fixed-count retrieval results projected for prompt injection at specified node."""

    node_kind: RetrievalNodeKind
    matched_entries: list[ProcedureMemoryEntry] = field(default_factory=list)
    total_matched: int = 0
