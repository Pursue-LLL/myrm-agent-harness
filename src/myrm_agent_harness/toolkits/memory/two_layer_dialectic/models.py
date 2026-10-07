# [POS]: myrm_agent_harness.toolkits.memory.two_layer_dialectic.models
# [INPUT]: None (Standard library & Pydantic)
# [OUTPUT]: DialecticPassKind, DialecticReconciliationConfig, BaseContextPayload, DialecticConflictCandidate, DialecticReconciliationResult, TwoLayerContextInjectionResult

"""Domain models for Two-Layer Context Injection and Multi-Pass Dialectic Reconciliation Suite.

P0/P1 delivery for Item 112 in topic_01 memory roadmap.
Decouples base context from dynamic reconciliation:
- Layer 1 (Base Context): Low-frequency cadence to preserve System Prompt KV Cache.
- Layer 2 (Dialectic Reconciliation): Multi-pass on-demand cognitive conflict resolution
  injected at user message tail to prevent cache busting while resolving contradictions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class DialecticPassKind(StrEnum):
    """Categorical stage in multi-pass dialectic reasoning loop."""

    INSPECTION = "inspection"          # Pass 0: Detect mutually exclusive subject-predicate pairs
    SYNTHESIS = "synthesis"            # Pass 1: Evaluate causality, timestamps, and confidence trade-offs
    RECONCILIATION = "reconciliation"  # Pass 2: Produce unified authoritative resolution and mark supersessions


class DialecticReconciliationConfig(BaseModel):
    """Orthogonal knobs governing cadence, depth, and similarity cutoffs."""

    context_cadence: int = Field(
        default=5, ge=1, description="Turns between Layer 1 Base Context refreshes (preserves KV cache)"
    )
    dialectic_cadence: int = Field(
        default=3, ge=1, description="Turns between proactive Layer 2 dialectic contradiction checks"
    )
    dialectic_depth: int = Field(
        default=3, ge=1, le=3, description="Dialectic reasoning pass depth: 1 (Inspection), 2 (+Synthesis), 3 (+Reconciliation)"
    )
    conflict_similarity_cutoff: float = Field(
        default=0.65, ge=0.0, le=1.0, description="Minimum keyword/semantic overlap triggering contradiction detection"
    )


class BaseContextPayload(BaseModel):
    """Layer 1 static context payload structured to preserve Prompt KV Cache."""

    session_summary: str = Field(description="Compact trajectory synopsis of current session")
    standing_peer_cards: list[str] = Field(
        default_factory=list, description="Curated standing persona summaries for active peers"
    )
    cache_control_hash: str = Field(description="Deterministic SHA-256 fingerprint for KV Cache verification")
    refreshed_at_turn: int = Field(default=0, description="Turn index when this base context was last compiled")
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class DialecticConflictCandidate(BaseModel):
    """Pair of conflicting memory statements identified during inspection."""

    statement_a: str = Field(description="Prior or established historical memory statement")
    statement_b: str = Field(description="Recent or competing memory statement")
    subject_domain: str = Field(description="Categorical subject area (e.g. database, framework, infra)")
    conflict_score: float = Field(default=1.0, ge=0.0, le=1.0, description="Degree of logical mutual exclusivity")


class DialecticReconciliationResult(BaseModel):
    """Result of multi-pass dialectic resolution over conflicting memory statements."""

    passes_executed: list[DialecticPassKind] = Field(
        default_factory=list, description="Reasoning passes completed during reconciliation"
    )
    resolved_statement: str = Field(description="Harmonized authoritative decision statement")
    superseded_statements: list[str] = Field(
        default_factory=list, description="Outdated or overridden statements retired during resolution"
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Resolution confidence score")
    rationale: str = Field(default="", description="Dialectic synthesis reasoning trace")


class TwoLayerContextInjectionResult(BaseModel):
    """Dual-layer injection payload safely decoupled for optimal caching and conflict freedom."""

    layer1_base_context: str = Field(
        description="Static base context block suitable for prefix injection or low-frequency refresh"
    )
    layer2_dialectic_block: str = Field(
        default="", description="Dynamic dialectic reconciliation block injected at user message tail"
    )
    injected_position: str = Field(
        default="user_message_tail", description="Target placement ensuring System Prompt cache safety"
    )
    is_cache_safe: bool = Field(
        default=True, description="True if System Prompt prefix was left strictly untouched"
    )
    token_overhead: int = Field(default=0, description="Estimated total token overhead of injected payload")
