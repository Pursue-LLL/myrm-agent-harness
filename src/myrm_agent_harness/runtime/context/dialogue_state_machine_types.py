"""Types and models for Dialogue State Machine and Adaptive Context Optimization.

Part of Item 128: DialogueStateMachineAndPerStateAdaptiveContextOptimizationEngine.
Provides models for 6-state dialogue classification, topic drift detection,
two-stage token threshold tiers, and temporal relevance weighting.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class DialogueStateKind(StrEnum):
    """Six canonical dialogue interaction states."""

    INITIAL_INQUIRY = "initial_inquiry"  # New task or query onset
    REQUIREMENT_SUPPLEMENT = "requirement_supplement"  # Incremental detail or constraint added
    FOLLOW_UP_PROBE = "follow_up_probe"  # In-depth question or inquiry into current finding
    CLARIFICATION_DISAMBIGUATION = "clarification_disambiguation"  # Clarifying ambiguous inputs
    TOPIC_SWITCH = "topic_switch"  # Abrupt or deliberate shift to a different topic
    SESSION_TERMINAL = "session_terminal"  # Concluding or confirmation phase


class TokenGovernanceThresholdTier(StrEnum):
    """Two-stage token budget governance tiers."""

    SAFE_NORMAL = "safe_normal"  # Within safe limits; standard pass-through
    WARNING_PRUNE = "warning_prune"  # Warning threshold reached; triggers redundancy & chatter pruning
    LIMIT_COMPACT = "limit_compact"  # Hard limit threshold reached; triggers topic decay & compaction


class TopicDriftAssessment(BaseModel):
    """Evaluation of semantic continuity vs topic drifting."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    is_drift_detected: bool = Field(description="True if current turn drifts from previous topic")
    similarity_score: float = Field(ge=0.0, le=1.0, description="Topic keyword overlap / continuity score")
    previous_topic_keywords: list[str] = Field(default_factory=list, description="Extracted keywords of prior turn")
    current_topic_keywords: list[str] = Field(default_factory=list, description="Extracted keywords of current turn")
    recommended_action: str = Field(description="Recommended action: MAINTAIN_THREAD, SOFT_ISOLATE, or BRANCH_TOPIC")


class TurnStateAnnotation(BaseModel):
    """Annotated state metadata for a single dialogue turn."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    turn_index: int = Field(ge=0, description="Sequential turn index")
    state_kind: DialogueStateKind = Field(description="Classified dialogue state")
    confidence_score: float = Field(ge=0.0, le=1.0, description="Confidence score of classification")
    detected_intents: list[str] = Field(default_factory=list, description="Identified functional intents")
    topic_drift: TopicDriftAssessment = Field(description="Topic drift analysis against context")
    governance_tier: TokenGovernanceThresholdTier = Field(description="Active token governance tier")


class AdaptiveDialogueOptimizationConfig(BaseModel):
    """Configuration for state-aware adaptive dialogue context optimization."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    warning_token_threshold: int = Field(default=8_000, gt=0, description="Token threshold triggering light pruning")
    limit_token_threshold: int = Field(default=16_000, gt=0, description="Token threshold triggering heavy compaction")
    topic_drift_similarity_threshold: float = Field(default=0.25, ge=0.0, le=1.0)
    temporal_decay_factor: float = Field(default=0.85, ge=0.1, le=1.0)


class OptimizedDialogueContextResult(BaseModel):
    """Result payload containing state annotations and optimized context."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    current_annotation: TurnStateAnnotation = Field(description="Annotation for the latest user turn")
    governance_tier: TokenGovernanceThresholdTier = Field(description="Enforced governance tier")
    pruned_chatter_count: int = Field(default=0, ge=0, description="Count of pruned redundant turns")
    isolated_prior_topics_count: int = Field(default=0, ge=0, description="Count of soft-isolated drifted turns")
    estimated_tokens_before: int = Field(ge=0, description="Token estimation prior to optimization")
    estimated_tokens_after: int = Field(ge=0, description="Token estimation following optimization")
    effective_messages_count: int = Field(ge=0, description="Count of messages retained in context")
