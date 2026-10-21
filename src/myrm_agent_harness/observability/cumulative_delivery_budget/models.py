"""
[INPUT]: Token and cost trial execution events from multi-agent orchestration workers.
[OUTPUT]: Immutable trial ledgers, cumulative delivery aggregates, and budget gate verdicts.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/cumulative_delivery_budget/models.py
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class UnknownUsageStatus(str, Enum):
    METERED = "METERED"
    UNMETERED_TIMEOUT = "UNMETERED_TIMEOUT"
    UNMETERED_PROVIDER_EMPTY = "UNMETERED_PROVIDER_EMPTY"
    UNMETERED_CONNECTION_RESET = "UNMETERED_CONNECTION_RESET"


class DeliveryBudgetGate(str, Enum):
    NORMAL = "NORMAL"
    WARNING_70 = "WARNING_70"
    EXCEEDED_PAUSED_100 = "EXCEEDED_PAUSED_100"


@dataclass(frozen=True)
class TrialRecord:
    trial_id: str
    agent_id: str
    agent_role: str
    attempt_index: int
    step_name: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    latency_ms: float
    is_unmetered: bool = False
    unmetered_status: UnknownUsageStatus = UnknownUsageStatus.METERED
    imputed_prompt_tokens: int = 0
    imputed_completion_tokens: int = 0
    imputed_cost_usd: float = 0.0
    status: str = "success"
    created_at: str = ""

    @property
    def effective_tokens(self) -> int:
        if self.is_unmetered:
            return self.imputed_prompt_tokens + self.imputed_completion_tokens
        return self.total_tokens

    @property
    def effective_cost_usd(self) -> float:
        if self.is_unmetered:
            return round(self.imputed_cost_usd, 4)
        return round(self.cost_usd, 4)


@dataclass
class CumulativeDeliveryLedger:
    delivery_id: str
    title: str
    budget_tokens_limit: Optional[int] = None
    budget_cost_limit_usd: Optional[float] = None
    total_metered_tokens: int = 0
    total_imputed_tokens: int = 0
    total_effective_tokens: int = 0
    total_metered_cost_usd: float = 0.0
    total_imputed_cost_usd: float = 0.0
    total_effective_cost_usd: float = 0.0
    unmetered_trials_count: int = 0
    total_trials_count: int = 0
    gate_verdict: DeliveryBudgetGate = DeliveryBudgetGate.NORMAL
    is_paused: bool = False
    pause_reason: Optional[str] = None
    trials: List[TrialRecord] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
