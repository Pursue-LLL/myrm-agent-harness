"""Data models for Idle & Budget Gated Auto-Memory Consolidation Suite.

[INPUT]
- pydantic (BaseModel, Field)
- time (POS: timestamp generation)

[OUTPUT]
- AutoMemoryGatingConfig: Threshold configurations for idle triggers and dual gates.
- TurnGatingDecision: Audit outcome for conversation turn count and info gain.
- BudgetGatingDecision: Audit outcome for token reserve & quota safety.
- IdleDetectionState: Evaluation for session idle window.
- OverallGatingReport: Consolidated decision bundle.
- SixDimensionalMemoryArtifact: Six-dimensional structured long-term memory asset.

[POS]
Domain value objects and reporting contracts for Item 123.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AutoMemoryGatingConfig(BaseModel):
    """Configuration regulating auto-consolidation triggers and admission gates."""

    enabled: bool = Field(
        default=True,
        description="Global kill-switch for automated background memory distillation.",
    )
    idle_timeout_seconds: float = Field(
        default=900.0,
        ge=10.0,
        description="Inactivity threshold (seconds) before triggering auto-consolidation (default 15m).",
    )
    min_turn_count: int = Field(
        default=3,
        ge=1,
        description="Minimum conversation turns required before admitting distillation (filters trivial queries).",
    )
    min_info_density: float = Field(
        default=0.35,
        ge=0.0,
        le=1.0,
        description="Minimum vocabulary/entropy density to reject trivial chit-chat (e.g. 'hi', 'ok').",
    )
    min_remaining_budget_tokens: int = Field(
        default=1000,
        ge=0,
        description="Absolute floor for remaining token balance before pausing background tasks.",
    )
    max_consolidation_cost_ratio: float = Field(
        default=0.25,
        gt=0.0,
        le=1.0,
        description="Upper bound for estimated distillation cost relative to remaining budget.",
    )


class TurnGatingDecision(BaseModel):
    """Evaluation result for dialogue turn count and information density gate."""

    passed: bool = Field(..., description="Whether turn & info gain criteria are satisfied.")
    turn_count: int = Field(..., ge=0, description="Total turns detected in the session.")
    info_density: float = Field(..., ge=0.0, le=1.0, description="Computed information density score.")
    reason: str = Field(..., description="Detailed diagnostic rationale.")


class BudgetGatingDecision(BaseModel):
    """Evaluation result for token reserve and quota preservation gate."""

    passed: bool = Field(..., description="Whether token budget is adequate for distillation.")
    remaining_tokens: int = Field(..., ge=0, description="Currently available token balance.")
    estimated_cost_tokens: int = Field(..., ge=0, description="Estimated token cost of distillation.")
    cost_ratio: float = Field(..., ge=0.0, description="Proportion of remaining budget consumed.")
    reason: str = Field(..., description="Detailed diagnostic rationale.")


class IdleDetectionState(BaseModel):
    """Inspection result for session inactivity duration."""

    session_id: str = Field(..., description="Unique conversation session identifier.")
    idle_seconds: float = Field(..., ge=0.0, description="Elapsed seconds since last conversation event.")
    idle_threshold_seconds: float = Field(..., ge=0.0, description="Configured timeout requirement.")
    is_idle_triggered: bool = Field(..., description="True if elapsed idle time meets or exceeds threshold.")
    reason: str = Field(..., description="Status summary.")


class OverallGatingReport(BaseModel):
    """Aggregated admission report deciding whether background distillation proceeds."""

    session_id: str = Field(..., description="Session identifier.")
    should_consolidate: bool = Field(..., description="Master verdict allowing distillation.")
    turn_decision: TurnGatingDecision = Field(..., description="Turn gate breakdown.")
    budget_decision: BudgetGatingDecision = Field(..., description="Budget gate breakdown.")
    idle_state: IdleDetectionState = Field(..., description="Idle trigger status.")
    final_rationale: str = Field(..., description="Human-readable decision explanation.")


class SixDimensionalMemoryArtifact(BaseModel):
    """Six-dimensional structured memory artifact distilled from session context.

    Addresses the CodeX benchmark:
    ① Working Directory Context
    ② Key Topics & Entities
    ③ User Preferences & Style
    ④ Reusable Domain Knowledge
    ⑤ Failure Lessons & Pitfalls
    ⑥ Tool Calling Patterns & Habits
    """

    artifact_id: str = Field(..., description="Unique deterministic artifact ID.")
    session_id: str = Field(..., description="Originating conversation session ID.")
    created_at_iso: str = Field(..., description="ISO 8601 creation timestamp.")
    working_directory: str = Field(..., description="Primary workspace/project directory path.")
    key_topics: list[str] = Field(default_factory=list, description="Core technical topics and concepts.")
    user_preferences: list[str] = Field(default_factory=list, description="User habits, preferences, and style.")
    reusable_domain_knowledge: list[str] = Field(
        default_factory=list,
        description="Reusable engineering practices, architecture patterns, and factual insights.",
    )
    failure_lessons: list[str] = Field(
        default_factory=list,
        description="Encountered traps, anti-patterns, and resolution postmortems.",
    )
    tool_calling_patterns: list[str] = Field(
        default_factory=list,
        description="Frequent tool interactions, sequence habits, and workflow behaviors.",
    )
    token_cost: int = Field(default=0, ge=0, description="Actual tokens expended producing this artifact.")
    summary_digest: str = Field(..., description="Concise synopsis synthesizing all six dimensions.")
