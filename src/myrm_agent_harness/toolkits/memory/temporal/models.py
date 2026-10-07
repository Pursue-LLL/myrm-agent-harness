"""Data models for Temporal Validity and Fact Expiration Governance Engine.

[INPUT]
- External: pydantic

[OUTPUT]
- FactTemporalState: Lifecycle state of a temporal fact assertion.
- TemporalFactRecord: Structured semantic fact with explicit validity interval and evolution state.
- ConflictSuppressionReport: Detailed report generated when an evolved fact suppresses obsolete competitors.
- ExpirationScanResult: Summary of periodic fact expiration audit and archiving.

[POS]
Data models for Temporal Validity and Fact Expiration Governance Engine.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class FactTemporalState(StrEnum):
    """Lifecycle state of a temporal fact assertion."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    ARCHIVED = "archived"


class TemporalFactRecord(BaseModel):
    """Structured semantic fact with explicit validity interval and evolution state."""

    fact_id: str = Field(description="Unique fact identifier")
    subject: str = Field(description="Target entity or concept subject (e.g. 'frontend_framework')")
    predicate: str = Field(description="Property or relationship predicate (e.g. 'uses_version')")
    value: str = Field(description="Factual value proposition (e.g. 'React 18' or 'Vue 3')")
    valid_from: datetime = Field(description="Effective starting timestamp of the fact")
    valid_to: datetime | None = Field(
        default=None,
        description="Expiration timestamp when the fact becomes obsolete, if known",
    )
    confidence: float = Field(default=0.9, ge=0.0, le=1.0, description="Base confidence weight")
    status: FactTemporalState = Field(
        default=FactTemporalState.ACTIVE,
        description="Current validity lifecycle state",
    )
    superseded_by_id: str | None = Field(
        default=None,
        description="Identifier of newer fact that superseded this record",
    )
    last_accessed_at: datetime | None = Field(
        default=None,
        description="Timestamp of most recent retrieval or usage",
    )
    metadata: dict[str, str] = Field(
        default_factory=dict,
        description="Auxiliary provenance or lineage metadata",
    )


class ConflictSuppressionReport(BaseModel):
    """Detailed report generated when an evolved fact suppresses obsolete competitors."""

    conflict_detected: bool = Field(description="True if competing assertions were found for the same predicate")
    subject: str = Field(description="Target entity subject")
    predicate: str = Field(description="Target property predicate")
    prevailing_fact_id: str | None = Field(
        default=None,
        description="Identifier of the prevailing newer fact",
    )
    suppressed_fact_ids: list[str] = Field(
        default_factory=list,
        description="Identifiers of obsolete historical facts that were suppressed",
    )
    suppression_penalty: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence reduction factor applied to obsolete facts",
    )
    rationale: str = Field(description="Arbitration explanation for why the prevailing fact won")


class ExpirationScanResult(BaseModel):
    """Summary of periodic fact expiration audit and archiving."""

    scanned_count: int = Field(ge=0, description="Total facts evaluated for expiration")
    expired_count: int = Field(ge=0, description="Facts that reached their valid_to expiration bound")
    archived_count: int = Field(ge=0, description="Facts successfully quarantined into archive storage")
    archived_fact_ids: list[str] = Field(
        default_factory=list,
        description="List of fact identifiers transferred to archive",
    )
