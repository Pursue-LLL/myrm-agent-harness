"""[POS]: src/myrm_agent_harness/toolkits/memory/decisions/models.py
[INPUT]: Core domain primitives and status enumerations for engineering decisions.
[OUTPUT]: Strongly typed DecisionRecord, PendingDecisionCandidate, and DecisionRecallHit contracts.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class DecisionStatus(StrEnum):
    """Lifecycle status of an architecture engineering decision."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DISCARDED = "discarded"


class CandidateStatus(StrEnum):
    """Lifecycle status of a pending decision candidate awaiting confirmation."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class DecisionRecord(BaseModel):
    """First-class structural architecture decision entity with lineage tracking."""

    id: str = Field(description="Unique deterministic or generated decision identifier")
    title: str = Field(description="Succinct technical topic or decision headline")
    text: str = Field(description="Concrete decision statement and chosen specification")
    rationale: str = Field(default="", description="Underlying architectural rationale, tradeoffs and constraints")
    status: DecisionStatus = Field(default=DecisionStatus.ACTIVE, description="Current lifecycle state")
    supersedes_id: str | None = Field(default=None, description="Identifier of the previous decision superseded by this one")
    superseded_by: str | None = Field(default=None, description="Identifier of the newer decision that superseded this one")
    scope: str = Field(default="project", description="Decision scope, e.g. project or global")
    project_key: str = Field(default="default", description="Namespace or project binding key")
    source_event: str | None = Field(default=None, description="Event trace anchor, e.g. #e104")
    created_at: str = Field(description="ISO-8601 creation timestamp")
    updated_at: str = Field(description="ISO-8601 last updated timestamp")


class PendingDecisionCandidate(BaseModel):
    """Temporary decision candidate staged in pending buffer before human approval."""

    id: str = Field(description="Candidate identifier")
    session_id: str = Field(description="Originating session identifier")
    title: str = Field(description="Proposed decision headline")
    text: str = Field(description="Proposed decision specification text")
    rationale: str = Field(default="", description="Proposed tradeoff reason")
    supersedes_id: str | None = Field(default=None, description="Proposed parent decision ID to supersede")
    status: CandidateStatus = Field(default=CandidateStatus.PENDING, description="Staged state")
    project_key: str = Field(default="default", description="Namespace or project binding key")
    created_at: str = Field(description="ISO-8601 candidate creation timestamp")
    updated_at: str = Field(description="ISO-8601 candidate update timestamp")


class DecisionRecallHit(BaseModel):
    """Prioritized recall hit wrapping a decision record with structured prompt formatting."""

    decision_id: str = Field(description="Decision record ID")
    title: str = Field(description="Decision headline")
    text: str = Field(description="Decision statement")
    rationale: str = Field(default="", description="Decision reasoning")
    status: DecisionStatus = Field(description="Lifecycle status")
    supersedes_id: str | None = Field(default=None, description="Superseded parent ID")
    superseded_by: str | None = Field(default=None, description="Newer superseding ID")
    score: float = Field(description="Relevance or priority score")
    is_priority: bool = Field(default=True, description="Whether this hit is placed in priority top section")
    formatted_line: str = Field(default="", description="Ready-to-inject markdown line for prompt integration")
    source_event: str | None = Field(default=None, description="Event trace anchor")
    created_at: str = Field(description="Creation timestamp")
