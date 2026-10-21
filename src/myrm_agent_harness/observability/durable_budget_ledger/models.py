"""
[INPUT]: Spend amounts, categories, session/task IDs, branch flags, and timestamp metadata.
[OUTPUT]: Strongly typed domain models for durable spend ledger, budget recovery summaries, and session actual-billed statements.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/durable_budget_ledger/models.py
"""

from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class SpendCategory(str, Enum):
    """Classification of LLM invocation costs."""

    CHAT = "chat"
    AUXILIARY = "auxiliary"
    CACHE_WARM = "cache_warm"
    SUBAGENT = "subagent"
    SYSTEM = "system"


class DurableSpendLedgerRecord(BaseModel):
    """Immutable spend ledger row persisting even if messages, retries, or sessions are deleted."""

    record_id: str = Field(...)
    session_id: Optional[str] = Field(default=None)
    task_id: Optional[str] = Field(default=None)
    cost_usd: float = Field(..., ge=0.0)
    category: SpendCategory = Field(default=SpendCategory.CHAT)
    date_utc: str = Field(..., description="UTC day key: YYYY-MM-DD")
    message_id: Optional[str] = Field(default=None)
    is_active_branch: bool = Field(default=True, description="False if discarded, rewound, or retried")
    timestamp_ms: int = Field(...)


class DurableBudgetRecoverySummary(BaseModel):
    """Reconciliation summary recovering daily budget from durable ledger vs fragile surviving messages."""

    date_utc: str = Field(...)
    total_durable_cost_usd: float = Field(default=0.0, ge=0.0)
    total_surviving_message_cost_usd: float = Field(default=0.0, ge=0.0)
    discarded_branch_cost_usd: float = Field(
        default=0.0,
        ge=0.0,
        description="True spend on rewound/deleted turns that disappeared from surviving messages",
    )
    records_count: int = Field(default=0, ge=0)
    category_breakdown: Dict[str, float] = Field(default_factory=dict)
    budget_underestimation_gap_usd: float = Field(
        default=0.0,
        ge=0.0,
        description="Underestimation risk: total_durable_cost_usd minus surviving messages sum",
    )


class SessionActualBilledStatement(BaseModel):
    """Session-level statement reconciling currently visible branch cost against actual billed cost."""

    session_id: str = Field(...)
    visible_branch_cost_usd: float = Field(default=0.0, ge=0.0)
    actual_billed_cost_usd: float = Field(default=0.0, ge=0.0)
    discarded_diff_cost_usd: float = Field(default=0.0, ge=0.0)
    records: List[DurableSpendLedgerRecord] = Field(default_factory=list)
