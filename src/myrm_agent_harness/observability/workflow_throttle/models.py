"""
[INPUT]: Workflow token metrics, active agent concurrency, and budget configurations.
[OUTPUT]: Strongly-typed telemetry models for massive workflow token burn rates and tiered budget ladder verdicts.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/workflow_throttle/models.py
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class BudgetLadderTier(str, Enum):
    """Tiered budget status levels based on workflow consumption percentage."""

    NORMAL = "NORMAL"  # < 50%
    TIER1_NOTICE = "TIER1_NOTICE"  # 50% - 80% Soft notice
    TIER2_DEGRADED = "TIER2_DEGRADED"  # 80% - 100% Adaptive model degradation / throttle
    TIER3_SUSPENDED = "TIER3_SUSPENDED"  # >= 100% Safety halt / paused


@dataclass(frozen=True)
class WorkflowTokenBurnSample:
    """Instantaneous snapshot of token burn metrics for a workflow execution."""

    timestamp: float
    tokens_per_sec: float
    cost_per_hour_usd: float
    cumulative_prompt_tokens: int
    cumulative_completion_tokens: int
    cumulative_cost_usd: float
    active_agent_count: int
    agent_burn_distribution: Dict[str, int] = field(default_factory=dict)

    def total_cumulative_tokens(self) -> int:
        return self.cumulative_prompt_tokens + self.cumulative_completion_tokens

    def to_dict(self) -> Dict[str, object]:
        return {
            "timestamp": round(self.timestamp, 3),
            "tokens_per_sec": round(self.tokens_per_sec, 2),
            "cost_per_hour_usd": round(self.cost_per_hour_usd, 4),
            "cumulative_prompt_tokens": self.cumulative_prompt_tokens,
            "cumulative_completion_tokens": self.cumulative_completion_tokens,
            "total_cumulative_tokens": self.total_cumulative_tokens(),
            "cumulative_cost_usd": round(self.cumulative_cost_usd, 4),
            "active_agent_count": self.active_agent_count,
            "agent_burn_distribution": dict(self.agent_burn_distribution),
        }


@dataclass(frozen=True)
class BudgetLadderVerdict:
    """Decision verdict emitted by the tiered budget safety governor."""

    workflow_id: str
    tier: BudgetLadderTier
    used_pct: float
    is_throttled: bool
    is_suspended: bool
    throttle_factor: float  # 1.0 = full speed, 0.5 = halved concurrency, 0.0 = halted
    action_message: str
    recommended_model_tier: str  # e.g., "primary", "economy", "halted"

    def to_dict(self) -> Dict[str, object]:
        return {
            "workflow_id": self.workflow_id,
            "tier": self.tier.value,
            "used_pct": round(self.used_pct, 2),
            "is_throttled": self.is_throttled,
            "is_suspended": self.is_suspended,
            "throttle_factor": round(self.throttle_factor, 2),
            "action_message": self.action_message,
            "recommended_model_tier": self.recommended_model_tier,
        }
