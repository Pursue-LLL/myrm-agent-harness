"""Types and data contracts for integration retained context purge and provenance revocation.

[INPUT]
- datetime::{UTC, datetime}
- enum::{Enum}
- uuid::{uuid4}
- pydantic::{BaseModel, Field}

[OUTPUT]
- PurgeExecutionMode: Enumeration of purge operation modes
- IntegrationRetainedContextSummary: High-fidelity retained context audit snapshot
- PurgeExecutionResult: Outcome report of an executed purge and revocation action
- ProvenanceRevocationRecord: Tamper-evident ledger record of revoked provenance origin

[POS]
Core contracts for connector-scoped context retention auditing, GDPR/Privacy-grade
selective purge, and cryptographic provenance invalidation (Topic 01 Item 179).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field


class PurgeExecutionMode(StrEnum):
    """Execution mode for connector disconnect and context retention."""

    RETAIN_CONTEXT = "retain_context"
    SELECTIVE_PURGE = "selective_purge"
    PURGE_AND_REVOKE = "purge_and_revoke"


class IntegrationRetainedContextSummary(BaseModel):
    """High-fidelity summary snapshot of context items retained from an integration."""

    integration_id: str = Field(description="Unique identifier of the connector or integration")
    provider_type: str = Field(
        default="external_integration",
        description="Provider category: oauth_provider, mcp_server, or external_integration",
    )
    retained_memory_count: int = Field(
        default=0, ge=0, description="Number of vector/semantic memories retaining this provenance"
    )
    retained_tree_count: int = Field(
        default=0, ge=0, description="Number of hierarchical integration trees/branches indexed"
    )
    retained_fact_count: int = Field(
        default=0, ge=0, description="Number of relational/procedural facts retaining this provenance"
    )
    total_retained_items: int = Field(
        default=0, ge=0, description="Aggregate count of all retained context items"
    )
    oldest_retained_at: datetime | None = Field(
        default=None, description="Timestamp of the earliest retained context item"
    )
    latest_retained_at: datetime | None = Field(
        default=None, description="Timestamp of the latest retained context item"
    )
    sample_snippets: list[str] = Field(
        default_factory=list, description="Sanitized snippets of retained memories for user verification"
    )
    is_provenance_revoked: bool = Field(
        default=False, description="Whether this integration provenance is currently marked as revoked"
    )


class PurgeExecutionResult(BaseModel):
    """Detailed execution result from a connector purge and provenance revocation operation."""

    integration_id: str = Field(description="Target connector or integration identifier")
    mode: PurgeExecutionMode = Field(description="Selected execution mode")
    deleted_memories_count: int = Field(
        default=0, ge=0, description="Total count of purged memory entries"
    )
    deleted_trees_count: int = Field(
        default=0, ge=0, description="Total count of purged integration trees"
    )
    revocation_id: str | None = Field(
        default=None, description="Identifier of the recorded provenance revocation entry"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp when the purge/disconnect operation completed",
    )
    success: bool = Field(default=True, description="Whether the operation succeeded cleanly")
    message: str = Field(default="", description="Human-readable result summary description")


class ProvenanceRevocationRecord(BaseModel):
    """Audit ledger record representing a revoked provenance source anchor."""

    revocation_id: str = Field(
        default_factory=lambda: f"rev_{uuid4().hex[:12]}",
        description="Globally unique identifier of this provenance revocation",
    )
    integration_id: str = Field(description="Connector or integration whose provenance was revoked")
    reason: str = Field(
        default="User requested integration disconnect with provenance revocation",
        description="Formal audit rationale for provenance revocation",
    )
    revoked_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Exact timestamp when provenance was invalidated",
    )
    purged_items_count: int = Field(
        default=0, ge=0, description="Number of context items purged as part of revocation"
    )
    actor: str = Field(default="user", description="Subject initiating the revocation")
