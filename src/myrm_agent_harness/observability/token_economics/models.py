"""
[INPUT]: Token usages, model names, execution durations, budget thresholds.
[OUTPUT]: Immutable dataclasses and schemas for Token economics, cache savings ROI, cost drift detection, and budget runaway guards.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/token_economics/models.py
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class DriftReasonType(str, Enum):
    NORMAL = "NORMAL"
    UPSTREAM_PRICE_INCREASE = "UPSTREAM_PRICE_INCREASE"
    SUBSIDY_REVOKED = "SUBSIDY_REVOKED"
    CACHE_HIT_DEGRADED = "CACHE_HIT_DEGRADED"
    ROUTING_FALLBACK = "ROUTING_FALLBACK"
    PROMPT_BLOAT = "PROMPT_BLOAT"


class GuardStatus(str, Enum):
    OK = "OK"
    SOFT_WARNING = "SOFT_WARNING"
    CIRCUIT_BREAKER_TRIPPED = "CIRCUIT_BREAKER_TRIPPED"


@dataclass(frozen=True)
class ModelPricingRate:
    model_name: str
    prompt_cpm: float  # Cost per million input tokens (RMB)
    completion_cpm: float  # Cost per million output tokens (RMB)
    cache_hit_cpm: float  # Cost per million cached input tokens (RMB, usually ~10% of prompt_cpm)
    cache_write_cpm: Optional[float] = None  # Cost for cache creation if any


@dataclass(frozen=True)
class TokenUsageSnapshot:
    task_id: str
    model_name: str
    task_category: str
    total_prompt_tokens: int
    cached_prompt_tokens: int
    completion_tokens: int
    execution_duration_seconds: float


@dataclass(frozen=True)
class CacheSavingsMetrics:
    task_id: str
    model_name: str
    cache_hit_rate_pct: float
    baseline_cost_rmb: float
    actual_cost_rmb: float
    saved_amount_rmb: float
    saved_percentage: float


@dataclass
class UnitCostBaseline:
    model_name: str
    task_category: str
    rolling_samples: List[float] = field(default_factory=list)
    average_unit_cost_per_k: float = 0.0
    sample_count: int = 0
    last_updated_at: str = ""


@dataclass(frozen=True)
class CostDriftAlert:
    task_category: str
    model_name: str
    current_unit_cost_per_k: float
    baseline_unit_cost_per_k: float
    drift_percentage: float
    is_significant_drift: bool
    reason: DriftReasonType
    explanation: str


@dataclass(frozen=True)
class BudgetGuardPolicy:
    max_allowed_cost_rmb: float = 10.0
    soft_warning_threshold_rmb: float = 7.0
    max_allowed_tokens: int = 200_000
    max_burn_rate_rmb_per_minute: float = 3.0


@dataclass(frozen=True)
class BudgetGuardEvaluation:
    status: GuardStatus
    current_cost_rmb: float
    current_burn_rate_rmb_min: float
    current_tokens: int
    is_paused: bool
    reason: str
    suggested_action: str
