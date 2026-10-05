"""Data models for Future Action Impact Filtering Gate."""

from enum import StrEnum

from pydantic import BaseModel, Field


class ActionImpactCategory(StrEnum):
    """Categorical classification of candidate memory information value."""

    CORE_PREFERENCE_OR_POLICY = "core_preference_or_policy"
    ENGINEERING_FACT_OR_DECISION = "engineering_fact_or_decision"
    EPHEMERAL_TASK_STATE = "ephemeral_task_state"
    CHITCHAT_OR_SPECULATION = "chitchat_or_speculation"


class ActionImpactTier(StrEnum):
    """Storage routing tier derived from quantitative action impact score."""

    TIER_LONG_TERM_PERSIST = "tier_long_term_persist"
    TIER_SESSION_BUFFER = "tier_session_buffer"
    TIER_IMMEDIATE_DISCARD = "tier_immediate_discard"


class ActionImpactAssessment(BaseModel):
    """Evaluation assessment detailing whether a fact will alter future agent actions."""

    fact_text: str = Field(description="Raw candidate fact text inspected")
    category: ActionImpactCategory = Field(description="Semantic value category")
    impact_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Quantified likelihood of modifying future agent decisions",
    )
    assigned_tier: ActionImpactTier = Field(description="Enforced persistence tier")
    rationale: str = Field(description="Heuristic reasoning explaining score assignment")
    will_alter_future_actions: bool = Field(
        description="True if impact score meets long-term persistence threshold (>= 0.80)",
    )


class BatchFilteringSummary(BaseModel):
    """Aggregated outcome of batch extraction admission filtering."""

    total_candidates: int = Field(ge=0, description="Total facts evaluated")
    persisted_count: int = Field(ge=0, description="Facts routed to long-term storage")
    session_buffered_count: int = Field(ge=0, description="Facts routed to ephemeral L2 session buffer")
    discarded_count: int = Field(ge=0, description="Facts immediately dropped as chitchat/noise")
    noise_reduction_ratio: float = Field(
        ge=0.0,
        le=1.0,
        description="Proportion of total facts prevented from polluting long-term memory",
    )
