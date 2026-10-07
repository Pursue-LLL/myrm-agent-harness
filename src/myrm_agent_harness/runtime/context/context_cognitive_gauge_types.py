"""Types and models for Context Cognitive Gauge and Agent Context Self-Awareness.

Part of Item 125: InspectContextCognitiveGaugeMetaTool.
Provides strong typed cognitive budget snapshots, urgency tiers, and action guidance.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ContextUrgencyLevel(StrEnum):
    """Urgency tier reflecting remaining context capacity."""

    NOMINAL = "nominal"  # < 60.0%: Abundant capacity for diverging and exploring
    CONVERGING = "converging"  # 60.0% ~ 84.9%: Moderate capacity, prepare to converge
    CRITICAL = "critical"  # 85.0% ~ 94.9%: High urgency, brake and summarize findings
    EXHAUSTED = "exhausted"  # >= 95.0%: Extreme urgency, emergency handoff/final answer


class CognitiveActionGuidance(StrEnum):
    """Recommended behavioral guidance based on cognitive headroom."""

    EXPLORE_FREELY = "EXPLORE_FREELY"
    CONVERGE_AND_VERIFY = "CONVERGE_AND_VERIFY"
    BRAKE_AND_SUMMARIZE = "BRAKE_AND_SUMMARIZE"
    EMERGENCY_HANDOFF = "EMERGENCY_HANDOFF"


class CognitiveGaugeConfig(BaseModel):
    """Configuration thresholds for context cognitive gauge evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_context_tokens: int = Field(default=128_000, gt=0)
    converging_threshold_pct: float = Field(default=60.0, ge=0.0, lt=100.0)
    critical_threshold_pct: float = Field(default=85.0, ge=0.0, lt=100.0)
    exhausted_threshold_pct: float = Field(default=95.0, ge=0.0, le=100.0)
    default_turn_token_burn: int = Field(default=1_500, gt=0)
    max_history_turns_tracked: int = Field(default=10, gt=0)


class ContextCognitiveSnapshot(BaseModel):
    """Immutable real-time cognitive capacity snapshot of the agent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total_limit_tokens: int = Field(gt=0, description="Configured context window size limit")
    used_tokens: int = Field(ge=0, description="Tokens currently consumed")
    remaining_tokens: int = Field(ge=0, description="Available token headroom remaining")
    capacity_pct: float = Field(ge=0.0, le=100.0, description="Capacity utilization percentage")
    urgency_level: ContextUrgencyLevel = Field(description="Cognitive urgency tier")
    suggested_action: CognitiveActionGuidance = Field(description="Recommended behavioral action")
    estimated_remaining_turns: int = Field(ge=0, description="Estimated turns remaining before exhaustion")
    is_compaction_imminent: bool = Field(description="True if context compression/summarization will trigger soon")
    gauge_rendered_bar: str = Field(description="Visual HUD bar representation (e.g. [████░░░░] 50.0%)")
    guidance_message: str = Field(description="Human and agent actionable guidance explanation")
