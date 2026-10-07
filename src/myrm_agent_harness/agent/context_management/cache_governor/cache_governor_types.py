# ============================================================================
# Dynamic Prompt Cache Breakeven Governor & Negative ROI Contracts (Item 166)
# Strong typing contracts for task reuse forecasting, breakeven ratio computation,
# pre-flight circuit breaking, and session net cache ROI observability.
# ============================================================================

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class TaskReuseKind(str, Enum):
    """Predicted interaction lifecycle kind for task reuse estimation."""

    SINGLE_TURN_QA = "single_turn_qa"
    ONE_OFF_COMMAND = "one_off_command"
    MULTI_TURN_ITERATION = "multi_turn_iteration"
    DEEP_WORKFLOW = "deep_workflow"


class CacheRoiStatus(str, Enum):
    """Categorization of expected cache economic ROI."""

    ROI_POSITIVE = "roi_positive"
    NEGATIVE_SUPPRESSED = "negative_suppressed"
    NEUTRAL_NO_PREMIUM = "neutral_no_premium"


@dataclass(frozen=True, slots=True)
class ModelPricingTier:
    """Pricing multipliers and baseline token cost for a model provider."""

    model_name: str
    input_cost_per_token: float
    cache_write_multiplier: float  # e.g. 1.25 for Anthropic
    cache_read_multiplier: float  # e.g. 0.1 for Anthropic


@dataclass(frozen=True, slots=True)
class BreakevenAnalysis:
    """Mathematical breakeven analysis based on Tokenomics Foundation rules."""

    breakeven_ratio: float  # (write_mult - 1.0) / (1.0 - read_mult)
    min_reuse_turns: int  # Minimum consecutive hits required to recoup write penalty
    expected_turns: int  # Forecasted turn count for the task
    predicted_net_roi_factor: float  # Estimated net ROI fraction


@dataclass(frozen=True, slots=True)
class CircuitBreakerDecision:
    """Pre-flight decision on whether to inject explicit cache breakpoints."""

    should_suppress_cache: bool
    roi_status: CacheRoiStatus
    reason: str
    analysis: BreakevenAnalysis
    evaluated_at_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(frozen=True, slots=True)
class SessionNetRoiLedgerEntry:
    """Accumulated financial and token audit entry for session net cache ROI."""

    session_id: str
    total_prompt_tokens: int
    cached_tokens: int
    cache_creation_tokens: int
    gross_savings_usd: float
    write_penalty_usd: float
    net_savings_usd: float
    suppressed_events_count: int
    last_updated_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
