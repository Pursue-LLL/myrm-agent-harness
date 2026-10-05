"""Data contracts and schemas for the MemOps 4-tuple standard semantic engine.

Defines the formal semantics for Remember, Forget, Update, and Reflect operations
and zero-context evaluation benchmarks (inspired by Metis / arXiv:2607.26760).

[INPUT]
- pydantic::BaseModel, Field, field_validator (POS: schema definition and validation)
- enum::StrEnum (POS: string-backed operation and status enums)
- datetime, uuid (POS: timestamping and identity generation)

[OUTPUT]
- MemOpType: REMEMBER, FORGET, UPDATE, REFLECT operation enumeration.
- MemOpStatus: SUCCESS, REJECTED, NOT_FOUND, CONFLICT execution status.
- MemOpFact: Canonical structured atomic fact schema.
- MemOpRequest: Unified invocation request DTO for MemOps operations.
- MemOpResult: Standardized execution result with state mutation tracking.
- MemOpsBenchmarkMetrics: Metric report for zero-context replay evaluations.

[POS]
Foundational data contracts for native Agent memory operations and evaluation harness.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


def _utc_now() -> datetime:
    return datetime.now(UTC)


class MemOpType(StrEnum):
    """The canonical MemOps 4-tuple memory operations."""

    REMEMBER = "remember"
    FORGET = "forget"
    UPDATE = "update"
    REFLECT = "reflect"


class MemOpStatus(StrEnum):
    """Execution status for a MemOp invocation."""

    SUCCESS = "success"
    REJECTED = "rejected"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"


class MemOpFact(BaseModel):
    """Canonical structured atomic fact schema supporting strict provenance and versioning."""

    fact_id: str = Field(default_factory=lambda: f"fact_{uuid4().hex[:12]}")
    entity: str = Field(..., description="Subject entity identifier (e.g., 'package_manager', 'db')")
    attribute: str = Field(..., description="Property or attribute name (e.g., 'preferred_tool', 'port')")
    value: str = Field(..., description="Exact factual value (e.g., 'uv', '5432')")
    statement: str = Field(..., description="Natural language declarative representation")
    confidence: float = Field(default=0.9, ge=0.0, le=1.0, description="Epistemic confidence [0.0, 1.0]")
    evidence: str = Field(default="", description="Source dialogue turn or observation evidence snippet")
    scope_id: str = Field(default="default", description="Namespace, user ID, or project scope")
    version: int = Field(default=1, ge=1, description="Sequential mutation revision counter")
    is_active: bool = Field(default=True, description="Active status; set to False upon deletion/forgetting")
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _ensure_utc(cls, v: datetime | str | None) -> datetime:
        if v is None:
            return _utc_now()
        if isinstance(v, str):
            v = datetime.fromisoformat(v)
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v


class MemOpRequest(BaseModel):
    """Unified invocation request DTO for MemOps operations."""

    op_type: MemOpType
    scope_id: str = Field(default="default")
    fact: MemOpFact | None = Field(default=None, description="Payload for REMEMBER or initial fact")
    target_id: str | None = Field(default=None, description="Explicit fact_id for FORGET or UPDATE")
    target_entity: str | None = Field(default=None, description="Entity match for entity-scoped FORGET")
    target_attribute: str | None = Field(default=None, description="Attribute match for targeted UPDATE")
    new_value: str | None = Field(default=None, description="New value payload for UPDATE")
    new_statement: str | None = Field(default=None, description="Optional updated natural language statement")
    new_evidence: str = Field(default="", description="Evidentiary justification for UPDATE")
    reason: str = Field(default="", description="Audit reason for FORGET or mutation")
    reflection_goal: str | None = Field(default=None, description="Target query or analytical goal for REFLECT")
    hard_delete: bool = Field(default=False, description="Physical removal vs. tombstone deactivation on FORGET")


class MemOpResult(BaseModel):
    """Standardized execution outcome DTO with mutation tracking."""

    op_type: MemOpType
    status: MemOpStatus
    affected_fact_ids: list[str] = Field(default_factory=list)
    message: str = Field(default="")
    fact: MemOpFact | None = Field(default=None, description="Resulting or mutated fact if applicable")
    reflection_synthesis: list[str] = Field(
        default_factory=list,
        description="Synthesized high-order insights produced by REFLECT",
    )


class MemOpsBenchmarkMetrics(BaseModel):
    """Quantitative performance score under Zero-Context Replay evaluation protocol."""

    total_episodes: int
    remember_recall: float = Field(ge=0.0, le=1.0, description="Recall rate under zero conversational context")
    forget_leakage_rate: float = Field(
        ge=0.0,
        le=1.0,
        description="Leakage rate (should be 0.0: forgotten facts must never be recalled)",
    )
    update_consistency_rate: float = Field(
        ge=0.0,
        le=1.0,
        description="Consistency rate (updated facts must override old values without conflict)",
    )
    reflect_synthesis_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Accuracy of multi-fact inductive synthesis",
    )
    passed: bool = Field(description="Whether all zero-context test thresholds were met")
