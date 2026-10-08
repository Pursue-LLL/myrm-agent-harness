"""Domain models for Explicit Authoritative Conclusions and Audit Tooling Suite.

P0 delivery for Item 111 in topic_01 memory roadmap.
Transforms implicit, passive summarization into explicit, first-class authoritative
decisions that can be declared, listed, audited, and revoked with full accountability.

[INPUT]
- Third-party: pydantic

[OUTPUT]
- ConclusionStatus: Lifecycle status of an authoritative decision or conclusion.
- ConclusionToolAction: Operation action invoked via memory_conclude_tool.
- AuthoritativeConclusion: First-class durable conclusion object with explicit peer attribution.
- ConclusionAuditRecord: Audit ledger record capturing mutation history of an authoritative conclusion.
- ConclusionAnchorProjection: Anti-dilution decision prompt block rendered for system prefix context.

[POS]
Domain models for Explicit Authoritative Conclusions and Audit Tooling Suite.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ConclusionStatus(StrEnum):
    """Lifecycle status of an authoritative decision or conclusion."""

    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    DEPRECATED = "deprecated"


class ConclusionToolAction(StrEnum):
    """Operation action invoked via memory_conclude_tool."""

    WRITE = "write"
    LIST = "list"
    DEPRECATE = "deprecate"
    DELETE = "delete"


class AuthoritativeConclusion(BaseModel):
    """First-class durable conclusion object with explicit peer attribution."""

    conclusion_id: str = Field(description="Unique system identifier for the conclusion")
    peer_id: str = Field(description="Originating participant peer ID (user or agent)")
    content: str = Field(description="Explicit, authoritative normative decision statement")
    status: ConclusionStatus = Field(
        default=ConclusionStatus.CONFIRMED, description="Current lifecycle state"
    )
    scope_tag: str = Field(
        default="general",
        description="Domain category (e.g. architecture, security, code_style, business_rule)",
    )
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    confirmed_at: str | None = Field(default=None, description="Timestamp when confirmed")
    deprecated_at: str | None = Field(default=None, description="Timestamp when marked deprecated")


class ConclusionAuditRecord(BaseModel):
    """Audit ledger record capturing mutation history of an authoritative conclusion."""

    audit_id: str = Field(description="Unique audit event identifier")
    conclusion_id: str = Field(description="Target conclusion identifier")
    action: ConclusionToolAction = Field(description="Operation performed")
    operator_peer_id: str = Field(description="Actor peer who performed this change")
    previous_status: ConclusionStatus | None = Field(
        default=None, description="Status prior to mutation"
    )
    new_status: ConclusionStatus | None = Field(
        default=None, description="Status after mutation"
    )
    rationale: str = Field(default="", description="Reason or justification for this action")
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ConclusionAnchorProjection(BaseModel):
    """Anti-dilution decision prompt block rendered for system prefix context."""

    formatted_prompt_block: str = Field(
        description="Rendered markdown block anchoring active authoritative conclusions"
    )
    total_active_conclusions: int = Field(default=0, description="Count of confirmed conclusions")
    token_estimate: int = Field(default=0, description="Estimated token overhead of anchor block")
