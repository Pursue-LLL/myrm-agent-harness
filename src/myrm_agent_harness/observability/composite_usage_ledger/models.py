"""[INPUT] Multi-turn agent usage telemetry with 6-dimensional composite keys.
[OUTPUT] Immutable data structures for composite session-model-task usage ledger and dual-track reconciliation.
[POS] myrm_agent_harness.observability.composite_usage_ledger.models

Defines the core data models for 6-dimensional persistent usage tracking:
1. CompositeUsageKey: (session_id, model, billing_provider, billing_base_url, billing_mode, task)
2. CostReconciliationStatus: ESTIMATED_ONLY, RECONCILED, DISCREPANCY_ALERT
3. CompositeUsageRecord: aggregated usage, token breakdown, estimated vs actual costs
"""

from dataclasses import dataclass, field
from enum import Enum
import time


class CostReconciliationStatus(str, Enum):
    """Reconciliation state between local estimated baseline and upstream billing invoice."""

    ESTIMATED_ONLY = "ESTIMATED_ONLY"            # Only local tier estimate available
    RECONCILED = "RECONCILED"                    # Upstream billed cost matches estimate within tolerance (<=15%)
    DISCREPANCY_ALERT = "DISCREPANCY_ALERT"      # Material discrepancy detected between estimate and billed invoice (>15%)


@dataclass(frozen=True)
class CompositeUsageKey:
    """Six-dimensional composite primary key uniquely scoping usage allocation."""

    session_id: str
    model: str
    billing_provider: str
    billing_base_url: str
    billing_mode: str
    task: str

    def to_key_string(self) -> str:
        return f"{self.session_id}::{self.model}::{self.billing_provider}::{self.billing_base_url}::{self.billing_mode}::{self.task}"


@dataclass
class CompositeUsageRecord:
    """Persistent ledger record tracking call count, token distribution, and dual-track cost."""

    key: CompositeUsageKey
    api_call_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    estimated_cost_usd: float = 0.0
    actual_cost_usd: float = 0.0
    cost_status: CostReconciliationStatus = CostReconciliationStatus.ESTIMATED_ONLY
    discrepancy_pct: float = 0.0
    first_seen_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    last_seen_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def accumulate(
        self,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        reasoning_tokens: int = 0,
        estimated_cost_usd: float = 0.0,
        actual_cost_usd: float = 0.0,
        timestamp_ms: int | None = None,
    ) -> None:
        """Accumulate new token consumptions and update dual-track reconciliation values."""
        now_ms = timestamp_ms or int(time.time() * 1000)
        self.api_call_count += 1
        self.input_tokens += max(0, input_tokens)
        self.output_tokens += max(0, output_tokens)
        self.cache_read_tokens += max(0, cache_read_tokens)
        self.cache_write_tokens += max(0, cache_write_tokens)
        self.reasoning_tokens += max(0, reasoning_tokens)
        self.estimated_cost_usd += max(0.0, estimated_cost_usd)
        self.last_seen_ms = now_ms

        if actual_cost_usd > 0.0:
            self.actual_cost_usd += actual_cost_usd
            self._recalculate_status()

    def reconcile_actual(self, actual_cost_usd: float, timestamp_ms: int | None = None) -> None:
        """Apply upstream returned invoice cost and compute reconciliation drift."""
        now_ms = timestamp_ms or int(time.time() * 1000)
        self.actual_cost_usd = max(0.0, actual_cost_usd)
        self.last_seen_ms = now_ms
        self._recalculate_status()

    def _recalculate_status(self) -> None:
        """Evaluate variance between estimated and actual cost."""
        if self.actual_cost_usd <= 0.0:
            self.cost_status = CostReconciliationStatus.ESTIMATED_ONLY
            self.discrepancy_pct = 0.0
            return

        if self.estimated_cost_usd <= 0.0:
            self.discrepancy_pct = 100.0
            self.cost_status = CostReconciliationStatus.DISCREPANCY_ALERT
            return

        diff = abs(self.actual_cost_usd - self.estimated_cost_usd)
        self.discrepancy_pct = round((diff / self.estimated_cost_usd) * 100.0, 2)

        if self.discrepancy_pct > 15.0:
            self.cost_status = CostReconciliationStatus.DISCREPANCY_ALERT
        else:
            self.cost_status = CostReconciliationStatus.RECONCILED

    def to_dict(self) -> dict[str, str | int | float]:
        return {
            "session_id": self.key.session_id,
            "model": self.key.model,
            "billing_provider": self.key.billing_provider,
            "billing_base_url": self.key.billing_base_url,
            "billing_mode": self.key.billing_mode,
            "task": self.key.task,
            "api_call_count": self.api_call_count,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "actual_cost_usd": round(self.actual_cost_usd, 6),
            "cost_status": self.cost_status.value,
            "discrepancy_pct": self.discrepancy_pct,
            "first_seen_ms": self.first_seen_ms,
            "last_seen_ms": self.last_seen_ms,
        }


@dataclass(frozen=True)
class LedgerSummary:
    """Aggregated portfolio summary across composite usage records."""

    total_records: int
    total_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_cache_tokens: int
    total_estimated_usd: float
    total_actual_usd: float
    reconciled_records_count: int
    discrepancy_records_count: int
    task_spend_distribution: dict[str, float]
    model_spend_distribution: dict[str, float]

    def to_dict(self) -> dict[str, int | float | dict[str, float]]:
        return {
            "total_records": self.total_records,
            "total_calls": self.total_calls,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cache_tokens": self.total_cache_tokens,
            "total_estimated_usd": round(self.total_estimated_usd, 6),
            "total_actual_usd": round(self.total_actual_usd, 6),
            "reconciled_records_count": self.reconciled_records_count,
            "discrepancy_records_count": self.discrepancy_records_count,
            "task_spend_distribution": self.task_spend_distribution,
            "model_spend_distribution": self.model_spend_distribution,
        }
