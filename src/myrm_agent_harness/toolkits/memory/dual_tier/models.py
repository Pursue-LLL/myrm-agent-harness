"""Data contracts and schemas for the Hyper/Local dual-tier memory block engine.

Decouples long-term, cross-session mental models (Hyper Memory Blocks) from
short-term, session-bound transient entities (Local Memory Blocks), preventing
semantic aliasing and cross-contamination.

[INPUT]
- pydantic::BaseModel, Field (POS: validation and serialization layer)
- datetime, uuid (POS: standard library time and identity generation)
- myrm_agent_harness.toolkits.memory.types::EvaporationState (POS: lifecycle evaporation status)

[OUTPUT]
- HyperMemoryBlock: Long-term global mental model, stable preference, or macro rule.
- LocalMemoryBlock: Short-term session-bound transient working memory entry.
- AttentionFusionContext: Dynamic memory attention weights and assembled prompt context.
- DistillationCandidate: High-confidence local memory extracted for promotion to Hyper.
- DistillationResult: Result of consolidating a session's local blocks into hyper blocks.

[POS]
Dual-tier memory block architecture foundation schemas inspired by Metis (arXiv:2607.26760).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from myrm_agent_harness.toolkits.memory.types import EvaporationState


def _utc_now() -> datetime:
    return datetime.now(UTC)


class HyperMemoryBlock(BaseModel):
    """Long-term, cross-session mental model or macro rule.

    Evolves slowly with high confidence, shared globally across agents and sessions.
    Resistant to single-session noise or temporary experimental parameters.
    """

    block_id: str = Field(default_factory=lambda: f"hyper_{uuid4().hex[:12]}")
    scope_id: str = Field(..., description="User ID, workspace ID, or global scope identifier")
    category: str = Field(
        default="preference",
        description="Category: preference, mental_model, architectural_rule, tool_profile",
    )
    statement: str = Field(..., description="Synthesized rule or invariant mental model statement")
    confidence: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        description="Confidence score, hyper blocks typically maintain >= 0.8",
    )
    version: int = Field(default=1, ge=1, description="Evolution revision number")
    reinforcement_count: int = Field(default=1, ge=1, description="Times reinforced across sessions")
    source_sessions: list[str] = Field(
        default_factory=list,
        description="Session IDs that contributed to or reinforced this block",
    )
    status: Literal["active", "deprecated", "superseded"] = Field(
        default="active",
        description="Lifecycle status of this macro rule",
    )
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


class LocalMemoryBlock(BaseModel):
    """Short-term, session-bound transient working memory entry.

    Maintains temporary entities, intermediate hypothesis states, and tool overrides.
    Bound to a specific session lifecycle. Evaporates upon session termination
    unless distilled into a HyperMemoryBlock.
    """

    block_id: str = Field(default_factory=lambda: f"local_{uuid4().hex[:12]}")
    session_id: str = Field(..., description="Active session ID owning this local memory")
    task_id: str | None = Field(default=None, description="Optional granular task or subagent ID")
    content: str = Field(..., description="Transient working memory content or temporary override")
    transient_tag: str = Field(
        default="task_context",
        description="Tag: tool_override, temporary_workaround, scratch_hypothesis, task_context",
    )
    evaporation_state: EvaporationState = Field(
        default=EvaporationState.PENDING,
        description="Lifecycle evaporation state",
    )
    verified_useful: bool = Field(
        default=False,
        description="Whether this temporary rule was verified as effective in solving tasks",
    )
    created_at: datetime = Field(default_factory=_utc_now)
    expires_at: datetime | None = Field(default=None)
    evaporated_at: datetime | None = Field(default=None)

    @field_validator("created_at", "expires_at", "evaporated_at", mode="before")
    @classmethod
    def _ensure_utc(cls, v: datetime | str | None) -> datetime | None:
        if v is None:
            return None
        if isinstance(v, str):
            v = datetime.fromisoformat(v)
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v


class AttentionFusionContext(BaseModel):
    """Dynamic memory attention weights and assembled prompt context."""

    hyper_weights: dict[str, float] = Field(
        default_factory=dict,
        description="Attention score per HyperMemoryBlock ID [0.0, 1.0]",
    )
    local_weights: dict[str, float] = Field(
        default_factory=dict,
        description="Attention score per LocalMemoryBlock ID [0.0, 1.0]",
    )
    hyper_blocks: list[HyperMemoryBlock] = Field(default_factory=list)
    local_blocks: list[LocalMemoryBlock] = Field(default_factory=list)
    formatted_prompt: str = Field(
        default="",
        description="Safe assembled prompt text with strict local boundary tags",
    )


class DistillationCandidate(BaseModel):
    """Local memory entity nominated for distillation into global Hyper memory."""

    local_block_id: str
    suggested_statement: str
    category: str
    confidence: float = Field(default=0.85, ge=0.0, le=1.0)


class DistillationResult(BaseModel):
    """Result of consolidating a session's local memory blocks."""

    session_id: str
    distilled_hyper_blocks: list[HyperMemoryBlock] = Field(default_factory=list)
    evaporated_local_block_ids: list[str] = Field(default_factory=list)
    retained_active_count: int = 0
