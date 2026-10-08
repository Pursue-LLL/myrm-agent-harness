"""Type definitions for cross-agent composable context and memory conflict arbitration.

[INPUT]
- External: pydantic, enum, time

[OUTPUT]
- ContextLayerKind: 4-layer taxonomy (Private, Profile, Global, Handoff)
- ContextProjectionLayer: Individual layer content and cache fingerprint
- ComposableContextProjection: Composed 4-layer context view for an agent
- ConflictResolutionPolicy: Arbitration policy order
- MemoryAssertion: Atomic memory claim by an agent
- AgentMemoryDivergence: Discrepancy between two agents
- ArbitrationOutcome: Settled truth after arbitration
- HandoffPacket: Signed task handoff packet with integrity hash
- HandoffVerificationResult: Verification report for incoming handoff

[POS]
Core contracts for multi-agent shared memory, context composition, and divergence settlement.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import time
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ContextLayerKind(StrEnum):
    """Four-layer hierarchy for composable multi-agent context projection."""

    LAYER_1_PRIVATE = "private_scratchpad"
    LAYER_2_PROFILE = "profile_tools"
    LAYER_3_GLOBAL = "global_ground_truth"
    LAYER_4_HANDOFF = "ephemeral_handoff"


class ContextProjectionLayer(BaseModel):
    """Metadata and serialized body of an individual context layer."""

    model_config = ConfigDict(extra="forbid")

    layer_kind: ContextLayerKind = Field(..., description="Classification tier of this layer")
    title: str = Field(..., description="Human-readable section title")
    content: str = Field(..., description="Textual body content projected for the agent")
    token_count: int = Field(ge=0, description="Estimated token consumption of this layer")
    content_hash: str = Field(..., description="SHA-256 fingerprint of the content for KV cache reuse")
    is_shared: bool = Field(default=False, description="Whether this layer is accessible to peer agents")


class ComposableContextProjection(BaseModel):
    """Fully composed 4-layer context projected for a specific agent execution turn."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(..., description="Target agent receiving this projection")
    session_id: str = Field(..., description="Active session or coordination id")
    total_tokens: int = Field(ge=0, description="Total aggregated token count across all layers")
    layers: list[ContextProjectionLayer] = Field(default_factory=list, description="Ordered layer stack")
    assembled_prompt_text: str = Field(..., description="Unified system/context prompt with prefix preservation")
    cache_prefix_hash: str = Field(..., description="Combined fingerprint of Layer 2 & 3 for 80%+ KV cache reuse")


class ConflictResolutionPolicy(StrEnum):
    """Resolution strategy priority for multi-agent memory arbitration."""

    GROUND_TRUTH_FIRST = "ground_truth_first"
    COORDINATOR_AUTHORITY = "coordinator_authority"
    CONFIDENCE_WEIGHTED = "confidence_weighted"
    HUMAN_IN_THE_LOOP = "human_in_the_loop"


class MemoryAssertion(BaseModel):
    """Atomic memory claim or fact asserted by an agent."""

    model_config = ConfigDict(extra="forbid")

    assertion_id: str = Field(..., description="Unique claim identifier")
    subject: str = Field(..., description="Subject or entity name, e.g. 'database_engine'")
    predicate: str = Field(..., description="Relationship or property, e.g. 'uses'")
    object_value: str = Field(..., description="Target value, e.g. 'SQLite' or 'PostgreSQL'")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence asserted by author")
    source_agent_id: str = Field(..., description="Author agent claiming this fact")
    source_reference: str | None = Field(default=None, description="Optional code path, config key, or tool source")
    timestamp: float = Field(default_factory=time.time, description="Unix timestamp of assertion generation")


class AgentMemoryDivergence(BaseModel):
    """Detected memory discrepancy between two collaborating agents."""

    model_config = ConfigDict(extra="forbid")

    divergence_id: str = Field(..., description="Unique divergence incident id")
    subject: str = Field(..., description="Contested subject or topic")
    predicate: str = Field(..., description="Contested predicate or relation")
    agent_a_id: str = Field(..., description="First agent identifier")
    assertion_a: MemoryAssertion = Field(..., description="Claim held by agent A")
    agent_b_id: str = Field(..., description="Second agent identifier")
    assertion_b: MemoryAssertion = Field(..., description="Conflicting claim held by agent B")


class ArbitrationOutcome(BaseModel):
    """Settled truth result produced by the arbitration probe."""

    model_config = ConfigDict(extra="forbid")

    divergence_id: str = Field(..., description="Evaluated divergence identifier")
    resolved: bool = Field(..., description="Whether conflict was definitively settled")
    policy_applied: ConflictResolutionPolicy = Field(..., description="Strategy that achieved settlement")
    winning_assertion: MemoryAssertion = Field(..., description="Canonical assertion adopted for both agents")
    audit_rationale: str = Field(..., description="Detailed explanation of the resolution evidence")
    requires_human_confirmation: bool = Field(
        default=False,
        description="True if confidence is ambiguous and needs 1-click human confirmation in UI",
    )


class HandoffPacket(BaseModel):
    """Cryptographically sealed task handoff packet transferred between agents."""

    model_config = ConfigDict(extra="forbid")

    packet_id: str = Field(..., description="Unique handoff transfer packet id")
    source_agent_id: str = Field(..., description="Author/sender agent identifier")
    target_agent_id: str = Field(..., description="Receiving agent identifier")
    task_id: str = Field(..., description="Underlying coordination task id")
    context_snapshot: str = Field(..., description="Key task findings, vetoed routes, and remaining actions")
    critical_assertions: list[MemoryAssertion] = Field(
        default_factory=list, description="Verified ground truth assertions passed to successor"
    )
    timestamp: float = Field(default_factory=time.time, description="Creation timestamp")
    signature_sha256: str = Field(..., description="SHA-256 seal across sender, target, task, and assertions")


class HandoffVerificationResult(BaseModel):
    """Verification outcome of an incoming handoff packet."""

    model_config = ConfigDict(extra="forbid")

    packet_id: str = Field(..., description="Evaluated packet identifier")
    is_valid: bool = Field(..., description="True if payload SHA-256 matches seal exactly")
    verified_assertions_count: int = Field(ge=0, description="Count of assertions confirmed pristine")
    rejection_reason: str | None = Field(default=None, description="Discrepancy reason if tampered or corrupt")
