# [POS]: src/myrm_agent_harness/toolkits/memory/auto_memory/models.py
# [INPUT]: Telemetry metrics, turn counts, token budgets, and structured memory facets
# [OUTPUT]: Strongly-typed Pydantic domain models for idle and budget-gated auto memory

"""Domain models for Idle and Budget Gated Auto-Memory Engine Suite (Item 123 P1).

Defines gating decisions, session activity snapshots, budget protection policies,
and the six-dimensional structured memory artifact model.
"""

from __future__ import annotations

import time
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class AutoMemoryGatingDecision(StrEnum):
    """Gating decision outcomes for automated session memory consolidation."""

    ACCEPTED = "accepted"
    SKIPPED_SHORT_CONVERSATION = "skipped_short_conversation"
    SKIPPED_LOW_INFORMATION = "skipped_low_information"
    SKIPPED_BUDGET_EXHAUSTED = "skipped_budget_exhausted"
    SKIPPED_NOT_IDLE = "skipped_not_idle"
    ALREADY_CONSOLIDATED = "already_consolidated"


class SessionActivitySnapshot(BaseModel):
    """Point-in-time activity and workload snapshot of an interactive session."""

    model_config = ConfigDict(frozen=True)

    session_id: str = Field(..., description="Unique session identifier")
    last_active_at_timestamp: float = Field(..., ge=0.0, description="Unix timestamp of last user or agent activity")
    turn_count: int = Field(default=0, ge=0, description="Total completed user-assistant conversation turns")
    total_messages_count: int = Field(default=0, ge=0, description="Total raw message count in session")
    total_tokens_consumed: int = Field(default=0, ge=0, description="Cumulative LLM tokens consumed in this session")
    has_unconsolidated_turns: bool = Field(default=True, description="Whether session has new turns since last memory save")
    workspace_path: str = Field(default="", description="Target working directory or repository root")


class AutoMemoryBudgetPolicy(BaseModel):
    """Dual-gate threshold constraints and token safety limits."""

    model_config = ConfigDict(frozen=True)

    min_turns_threshold: int = Field(default=3, ge=1, description="Minimum turns required to trigger memory save")
    idle_timeout_seconds: float = Field(default=900.0, ge=1.0, description="Seconds of inactivity before auto-trigger (default 15m)")
    max_token_budget_ceiling: int = Field(default=50000, ge=100, description="Max session token usage before suspending background summarization")
    current_consumed_tokens: int = Field(default=0, ge=0, description="Current total tokens consumed across session/account")
    min_unconsolidated_char_count: int = Field(default=120, ge=10, description="Minimum total message characters to avoid trivial summaries")
    allow_rule_heuristic_fallback: bool = Field(default=True, description="Whether to extract zero-token rule summaries when LLM budget is constrained")


class SixDimensionalMemorySlice(BaseModel):
    """Six-dimensional structured artifact organizing durable session insights."""

    model_config = ConfigDict(frozen=True)

    session_id: str = Field(..., description="Source session ID")
    workspace_env: str = Field(default="", description="Workspace root, environment details, runtime toolchain")
    key_topics: tuple[str, ...] = Field(default_factory=tuple, description="Key domain terms, keywords, and topics")
    user_preferences: tuple[str, ...] = Field(default_factory=tuple, description="User habits, stylistic constraints, guidelines")
    reusable_knowledge: tuple[str, ...] = Field(default_factory=tuple, description="Reusable procedures, domain patterns, architectural facts")
    failure_lessons: tuple[str, ...] = Field(default_factory=tuple, description="Resolved pitfalls, bug causes, failure reflections")
    tool_habits: tuple[str, ...] = Field(default_factory=tuple, description="Frequent tool commands, parameter quirks, execution habits")
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0, description="Extraction confidence score")
    created_at_timestamp: float = Field(default_factory=time.time, ge=0.0, description="Unix timestamp when slice was materialized")


class AutoMemoryExtractionResult(BaseModel):
    """Aggregated outcome of auto-memory gating evaluation and extraction."""

    model_config = ConfigDict(frozen=True)

    decision: AutoMemoryGatingDecision = Field(..., description="Gating verdict")
    is_eligible: bool = Field(..., description="Whether memory extraction was executed")
    reason: str = Field(..., description="Human and machine-readable explanation of decision")
    memory_slice: SixDimensionalMemorySlice | None = Field(default=None, description="Extracted 6D memory slice if accepted")
    tokens_billed_for_extraction: int = Field(default=0, ge=0, description="Tokens consumed during extraction (0 if rule-based)")
