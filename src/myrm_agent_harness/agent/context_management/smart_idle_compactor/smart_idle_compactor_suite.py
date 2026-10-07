"""Smart Idle Cache-Preserving Auto-Compactor Suite.

Coordinates OS/Web idle detection, upstream KV prompt cache TTL monitoring,
and opportunistic background pre-compaction to slash prefill latencies and costs.
"""

from __future__ import annotations

from typing import Sequence

from .idle_compactor_types import (
    CompactedCheckpointArchive,
    IdleCompactionEvaluation,
    IdleCompactorConfig,
    OpportunisticCompactionResult,
    ZeroWaitWakeupEvent,
)
from .idle_eligibility_evaluator import IdleEligibilityEvaluator
from .opportunistic_compactor_engine import OpportunisticCompactorEngine


class SmartIdleCachePreservingAutoCompactorSuite:
    """Master suite governing OS-level idle awareness and opportunistic background pre-compaction."""

    def __init__(self, config: IdleCompactorConfig | None = None) -> None:
        self.config = config or IdleCompactorConfig()
        self._evaluator = IdleEligibilityEvaluator(self.config)
        self._engine = OpportunisticCompactorEngine(self.config)
        self._results: list[OpportunisticCompactionResult] = []

    @property
    def evaluator(self) -> IdleEligibilityEvaluator:
        """Access the underlying idle eligibility evaluator."""
        return self._evaluator

    @property
    def engine(self) -> OpportunisticCompactorEngine:
        """Access the underlying opportunistic compactor engine."""
        return self._engine

    def evaluate_session(
        self,
        session_id: str,
        current_tokens: int,
        last_turn_timestamp_epoch: float,
        current_timestamp_epoch: float | None = None,
    ) -> IdleCompactionEvaluation:
        """Check whether an idle session qualifies for opportunistic background pre-compaction."""
        return self._evaluator.evaluate(
            session_id=session_id,
            current_tokens=current_tokens,
            last_turn_timestamp_epoch=last_turn_timestamp_epoch,
            current_timestamp_epoch=current_timestamp_epoch,
        )

    def compact_if_eligible(
        self,
        session_id: str,
        current_tokens: int,
        last_turn_timestamp_epoch: float,
        current_timestamp_epoch: float | None = None,
        messages_repr: Sequence[dict[str, str]] | None = None,
        summary_override: str | None = None,
    ) -> OpportunisticCompactionResult:
        """Evaluate and automatically execute background compaction if the opportunistic window is open."""
        eval_res = self.evaluate_session(
            session_id=session_id,
            current_tokens=current_tokens,
            last_turn_timestamp_epoch=last_turn_timestamp_epoch,
            current_timestamp_epoch=current_timestamp_epoch,
        )
        result = self._engine.execute_opportunistic_compaction(
            evaluation=eval_res,
            messages_repr=messages_repr,
            estimated_pre_tokens=current_tokens,
            summary_override=summary_override,
        )
        if result.success:
            self._results.append(result)
        return result

    def notify_user_wakeup(
        self,
        session_id: str,
        idle_total_seconds: float,
    ) -> ZeroWaitWakeupEvent:
        """Handle user resumption after prolonged absence and track latency avoidance."""
        return self._engine.record_wakeup(session_id, idle_total_seconds)

    def get_archived_checkpoint(self, session_id: str) -> CompactedCheckpointArchive | None:
        """Retrieve preserved cold-storage checkpoint archive for a given session."""
        return self._engine.get_archive(session_id)

    def get_aggregate_metrics(self) -> dict[str, object]:
        """Produce cumulative metrics on avoided costs and prompt cache efficiency."""
        total_tokens_compressed = sum(r.saved_tokens for r in self._results)
        total_cost_avoided = sum(r.cost_units_avoided for r in self._results)
        total_cost_incurred = sum(r.cost_units_incurred for r in self._results)

        net_savings_ratio = 0.0
        if (total_cost_avoided + total_cost_incurred) > 0:
            net_savings_ratio = total_cost_avoided / (total_cost_avoided + total_cost_incurred)

        return {
            "opportunistic_compactions_executed": len(self._results),
            "total_tokens_compressed": total_tokens_compressed,
            "total_cost_units_incurred_at_discount": round(total_cost_incurred, 2),
            "total_cold_cost_units_avoided": round(total_cost_avoided, 2),
            "net_financial_savings_ratio": round(net_savings_ratio, 4),
        }
