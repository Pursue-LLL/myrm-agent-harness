"""Multi-dimensional session and task token ledger for cumulative accounting and savings auditing.

[INPUT]
- PrefixCachingLayoutConfig: Pricing and discount configuration.
- TokenUsageBreakdown: Individual turn token breakdown.
- TurnLedgerRecord: Audited record per turn.

[OUTPUT]
- MultiDimensionalSessionTokenLedger: Stateful ledger accumulating multi-turn telemetry and diagnosing usage health.

[POS]
Authoritative state ledger layer preventing unmetered burn and transparently exposing KV cache savings.
"""

from __future__ import annotations

import time
from typing import Mapping, Sequence

from .prefix_caching_types import (
    PrefixCachingLayoutConfig,
    TokenUsageBreakdown,
    TurnLedgerRecord,
)


class MultiDimensionalSessionTokenLedger:
    """Session-scoped immutable audit ledger tracking all token dimensions across conversation turns."""

    def __init__(
        self,
        session_id: str,
        config: PrefixCachingLayoutConfig | None = None,
    ) -> None:
        self._session_id = session_id
        self._config = config or PrefixCachingLayoutConfig()
        self._records: list[TurnLedgerRecord] = []

    @property
    def session_id(self) -> str:
        """The identifier of the conversation session."""
        return self._session_id

    @property
    def turn_count(self) -> int:
        """Total number of recorded interaction turns."""
        return len(self._records)

    def record_turn(
        self,
        turn_id: str,
        model_name: str,
        usage: TokenUsageBreakdown,
        timestamp: float | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> TurnLedgerRecord:
        """Append an audited usage snapshot for a specific conversation turn."""
        t_now = timestamp if timestamp is not None else time.time()
        is_hit = usage.cache_read_tokens > 0

        record = TurnLedgerRecord(
            turn_id=turn_id,
            model_name=model_name,
            timestamp=t_now,
            usage=usage,
            prefix_cache_hit=is_hit,
            metadata=dict(metadata or {}),
        )
        self._records.append(record)
        return record

    def get_records(self) -> Sequence[TurnLedgerRecord]:
        """Retrieve an immutable view of all turn records."""
        return tuple(self._records)

    def get_session_aggregate(self) -> TokenUsageBreakdown:
        """Aggregate cumulative token figures across all session turns."""
        if not self._records:
            return TokenUsageBreakdown()

        tot_input = sum(r.usage.input_tokens for r in self._records)
        tot_output = sum(r.usage.output_tokens for r in self._records)
        tot_reasoning = sum(r.usage.reasoning_tokens for r in self._records)
        tot_cache_read = sum(r.usage.cache_read_tokens for r in self._records)
        tot_cache_write = sum(r.usage.cache_write_tokens for r in self._records)

        return TokenUsageBreakdown(
            input_tokens=tot_input,
            output_tokens=tot_output,
            reasoning_tokens=tot_reasoning,
            cache_read_tokens=tot_cache_read,
            cache_write_tokens=tot_cache_write,
        )

    def estimate_effective_token_savings(
        self,
        discount_rate: float | None = None,
    ) -> int:
        """Estimate the equivalent input tokens saved via KV-caching discounts."""
        rate = discount_rate if discount_rate is not None else self._config.default_cache_discount_rate
        aggregate = self.get_session_aggregate()
        return int(aggregate.cache_read_tokens * rate)

    def estimate_cost_savings_percentage(
        self,
        discount_rate: float | None = None,
    ) -> float:
        """Estimate the overall percentage cost reduction achieved across all input tokens."""
        aggregate = self.get_session_aggregate()
        if aggregate.input_tokens <= 0:
            return 0.0

        rate = discount_rate if discount_rate is not None else self._config.default_cache_discount_rate
        # Savings fraction = (cache_read_tokens * discount_rate) / total_input_tokens
        saved_fraction = (aggregate.cache_read_tokens * rate) / aggregate.input_tokens
        return min(1.0, max(0.0, saved_fraction))

    def diagnose_ledger_health(self) -> Mapping[str, object]:
        """Diagnose usage health, detecting hidden burn or prompt cache anomalies."""
        aggregate = self.get_session_aggregate()
        has_high_reasoning_burn = aggregate.reasoning_ratio > 0.5
        has_suboptimal_cache_rate = self.turn_count >= 2 and aggregate.cache_hit_rate < 0.4

        return {
            "session_id": self._session_id,
            "turn_count": self.turn_count,
            "total_tokens": aggregate.total_tokens,
            "reasoning_tokens": aggregate.reasoning_tokens,
            "reasoning_ratio": round(aggregate.reasoning_ratio, 4),
            "cache_hit_rate": round(aggregate.cache_hit_rate, 4),
            "estimated_savings_pct": round(self.estimate_cost_savings_percentage() * 100.0, 2),
            "alert_high_reasoning_burn": has_high_reasoning_burn,
            "alert_cache_hit_drop": has_suboptimal_cache_rate,
        }
