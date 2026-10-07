"""Types and models for Session Handoff and Clean Window Continuation.

Part of Item 126: SessionHandoffCleanWindowContinuationEngine.
Provides models for 8-part structured handoff memos, phase states, and clean-window continuation bundles.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class HandoffPhaseKind(StrEnum):
    """Lifecycle phase of a session handoff process."""

    ACTIVE = "active"
    PREPARING = "preparing"
    READY_FOR_SHIFT = "ready_for_shift"
    TRANSFERRED = "transferred"
    ABORTED = "aborted"


class HandoffTriggerReason(StrEnum):
    """Reason triggering the clean-window continuation handoff."""

    CAPACITY_SATURATION = "capacity_saturation"
    MILESTONE_REACHED = "milestone_reached"
    MODEL_SWITCH = "model_switch"
    USER_INITIATED = "user_initiated"
    ERROR_RECOVERY = "error_recovery"


class RejectedAlternativeRecord(BaseModel):
    """Record of an approach that failed or was disqualified, preventing re-attempts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    proposed_approach: str = Field(description="Summary of the failed or rejected approach")
    failure_reason: str = Field(description="Concrete reason why it failed or was discarded")
    prevent_retry: bool = Field(default=True, description="Enforce hard guard against retrying this approach")


class StructuredHandoffMemo(BaseModel):
    """Eight-part structured handoff memorandum passed to a fresh context window."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    memo_id: str = Field(description="Unique identifier for the handoff memorandum")
    source_session_id: str = Field(description="ID of the retiring source session")
    created_at: str = Field(description="ISO-8601 creation timestamp")
    trigger_reason: HandoffTriggerReason = Field(description="Why this handoff was initiated")
    current_objective: str = Field(description="Primary task objective remaining to be completed")
    completed_milestones: list[str] = Field(default_factory=list, description="Milestones successfully concluded")
    active_hypotheses: list[str] = Field(default_factory=list, description="Currently active assumptions and hypotheses")
    rejected_alternatives: list[RejectedAlternativeRecord] = Field(
        default_factory=list,
        description="Approaches attempted that failed or were rejected; must NOT be re-attempted",
    )
    critical_constraints: list[str] = Field(
        default_factory=list,
        description="Inviolable requirements, security gates, or resource limitations",
    )
    next_action_plan: list[str] = Field(
        default_factory=list,
        description="Sequential list of actionable next steps for the successor agent",
    )
    modified_files_and_artifacts: list[str] = Field(
        default_factory=list,
        description="Paths of files modified or artifacts generated during the session",
    )
    external_state_anchors: dict[str, str] = Field(
        default_factory=dict,
        description="External anchors such as commit hashes, branch names, or deployment URLs",
    )


class CleanWindowContinuationBundle(BaseModel):
    """Immutable bundle ready to prime a clean successor context window."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_session_id: str = Field(description="Originating session ID")
    new_session_id: str = Field(description="Fresh recipient session ID")
    handoff_memo: StructuredHandoffMemo = Field(description="Complete structured handoff memorandum")
    bootstrap_prompt: str = Field(description="Ready-to-inject Markdown/XML prompt for Turn 1")
    source_context_tokens: int = Field(ge=0, description="Estimated tokens consumed by source session")
    handoff_memo_tokens: int = Field(ge=0, description="Tokens consumed by the compiled handoff memorandum")
    estimated_token_savings_pct: float = Field(
        ge=0.0,
        le=100.0,
        description="Percentage of context window capacity reclaimed",
    )
    timestamp_iso: str = Field(description="ISO-8601 generation timestamp")
