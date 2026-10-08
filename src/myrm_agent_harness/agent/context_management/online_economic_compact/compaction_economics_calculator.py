# [INPUT]: CompactionDecisionResult, CompactionEconomicsConfig, PlanStep, PlanStepStatus
# [OUTPUT]: CompactionEconomicsCalculator
# [POS]: agent/context_management/online_economic_compact/compaction_economics_calculator.py

"""Mathematical economic breakeven calculator for online context compaction.

[INPUT]
- CompactionDecisionResult, CompactionEconomicsConfig, PlanStep, PlanStepStatus:
  Domain types from economic_compact_types.

[OUTPUT]
- CompactionEconomicsCalculator: Mathematical engine evaluating whether compacting context yields
  guaranteed net token savings over the expected task horizon or is required by hard window pressure.

[POS]
Mathematical core implementing NVIDIA SoL-Pi compaction economics (breakevenRequests vs effectiveHorizon).
"""

from __future__ import annotations

import math
from typing import Sequence

from .economic_compact_types import (
    CompactionDecisionResult,
    CompactionEconomicsConfig,
    PlanStep,
    PlanStepStatus,
)


class CompactionEconomicsCalculator:
    """Calculates mathematical breakeven horizons and evaluates compaction ROI."""

    def __init__(self, config: CompactionEconomicsConfig | None = None) -> None:
        self._config = config or CompactionEconomicsConfig()

    @property
    def config(self) -> CompactionEconomicsConfig:
        return self._config

    def calculate_breakeven(
        self,
        write_tokens: int,
        context_tokens: int,
        memo_tokens: int,
    ) -> int:
        """Calculate requests needed to recover compaction write cost."""
        delta = max(1, context_tokens - memo_tokens)
        return math.ceil(write_tokens / delta)

    def calculate_combined_breakeven(
        self,
        write_tokens: int,
        context_tokens: int,
        memo_tokens: int,
        carried_debt_tokens: int,
    ) -> int:
        """Calculate requests needed to recover both compaction cost and prior carried debt."""
        delta = max(1, context_tokens - memo_tokens)
        total_investment = write_tokens + max(0, carried_debt_tokens)
        return math.ceil(total_investment / delta)

    def estimate_remaining_horizon(
        self,
        plan_steps: Sequence[PlanStep],
        completed_step_requests: int = 0,
    ) -> int:
        """Estimate remaining requests based on completed steps velocity and remaining steps count."""
        remaining_steps = [
            s for s in plan_steps if s.status in (PlanStepStatus.PENDING, PlanStepStatus.IN_PROGRESS)
        ]
        if not remaining_steps:
            return 1

        completed_steps = [s for s in plan_steps if s.status == PlanStepStatus.COMPLETED]
        if completed_steps and completed_step_requests > 0:
            avg_per_step = max(1.0, completed_step_requests / len(completed_steps))
        else:
            avg_per_step = self._config.first_compaction_request_scale

        estimated = math.ceil(len(remaining_steps) * avg_per_step)
        return max(1, estimated)

    def evaluate_decision(
        self,
        current_tokens: int,
        plan_steps: Sequence[PlanStep],
        completed_step_requests: int = 0,
        carried_debt_tokens: int = 0,
        is_subtask_boundary: bool = False,
        estimated_write_tokens: int | None = None,
        estimated_memo_tokens: int | None = None,
    ) -> CompactionDecisionResult:
        """Evaluate compaction decision combining hard window pressure and mathematical economics."""
        write_tokens = estimated_write_tokens or self._config.default_estimated_write_tokens
        memo_tokens = estimated_memo_tokens or self._config.default_estimated_memo_tokens

        remaining_window = self._config.max_context_tokens - current_tokens

        # Check 1: Hard window overflow pressure override
        if remaining_window <= self._config.window_reserve_tokens:
            breakeven = self.calculate_breakeven(write_tokens, current_tokens, memo_tokens)
            combined = self.calculate_combined_breakeven(
                write_tokens, current_tokens, memo_tokens, carried_debt_tokens
            )
            horizon = self.estimate_remaining_horizon(plan_steps, completed_step_requests)
            return CompactionDecisionResult(
                should_compact=True,
                reason_code="HARD_WINDOW_PRESSURE",
                breakeven_requests=breakeven,
                combined_breakeven_requests=combined,
                effective_horizon_requests=horizon,
                carried_debt_tokens=carried_debt_tokens,
                net_estimated_savings=max(0, (horizon * (current_tokens - memo_tokens)) - write_tokens),
                explanation=(
                    f"Remaining context capacity ({remaining_window} tokens) fell below "
                    f"hard safety reserve ({self._config.window_reserve_tokens} tokens). "
                    "Compaction mandated to prevent context overflow."
                ),
            )

        # Check 2: Only trigger proactive compaction at subtask boundaries
        if not is_subtask_boundary:
            return CompactionDecisionResult(
                should_compact=False,
                reason_code="NO_COMPACTION_NEEDED",
                breakeven_requests=0,
                combined_breakeven_requests=0,
                effective_horizon_requests=self.estimate_remaining_horizon(plan_steps, completed_step_requests),
                carried_debt_tokens=carried_debt_tokens,
                net_estimated_savings=0,
                explanation="Not at a completed plan step / subtask boundary; deferring compaction.",
            )

        # Check 3: Mathematical delta viability
        delta = current_tokens - memo_tokens
        if delta <= 0:
            return CompactionDecisionResult(
                should_compact=False,
                reason_code="NO_COMPACTION_NEEDED",
                breakeven_requests=0,
                combined_breakeven_requests=0,
                effective_horizon_requests=self.estimate_remaining_horizon(plan_steps, completed_step_requests),
                carried_debt_tokens=carried_debt_tokens,
                net_estimated_savings=0,
                explanation=f"Context tokens ({current_tokens}) does not meaningfully exceed memo target ({memo_tokens}).",
            )

        breakeven = self.calculate_breakeven(write_tokens, current_tokens, memo_tokens)
        combined_breakeven = self.calculate_combined_breakeven(
            write_tokens, current_tokens, memo_tokens, carried_debt_tokens
        )
        horizon = self.estimate_remaining_horizon(plan_steps, completed_step_requests)

        required_horizon = math.ceil(combined_breakeven * self._config.subsequent_compaction_margin)

        # Check 4: Carried debt throttling
        if carried_debt_tokens > 0 and horizon < combined_breakeven:
            return CompactionDecisionResult(
                should_compact=False,
                reason_code="DEBT_UNRECOVERED_REJECTED",
                breakeven_requests=breakeven,
                combined_breakeven_requests=combined_breakeven,
                effective_horizon_requests=horizon,
                carried_debt_tokens=carried_debt_tokens,
                net_estimated_savings=0,
                explanation=(
                    f"Prior carried debt ({carried_debt_tokens} tokens) requires combined {combined_breakeven} "
                    f"requests to break even, but remaining horizon is only {horizon} requests."
                ),
            )

        # Check 5: Effective horizon vs economic margin
        if horizon < required_horizon:
            return CompactionDecisionResult(
                should_compact=False,
                reason_code="INSUFFICIENT_HORIZON_REJECTED",
                breakeven_requests=breakeven,
                combined_breakeven_requests=combined_breakeven,
                effective_horizon_requests=horizon,
                carried_debt_tokens=carried_debt_tokens,
                net_estimated_savings=0,
                explanation=(
                    f"Remaining horizon ({horizon} requests) is insufficient to achieve margin "
                    f"over combined breakeven ({combined_breakeven} reqs * {self._config.subsequent_compaction_margin} margin = {required_horizon} reqs). "
                    "Compaction rejected to avoid net economic token loss."
                ),
            )

        # Check 6: Approved with net positive economic ROI
        net_savings = (horizon * delta) - (write_tokens + carried_debt_tokens)
        return CompactionDecisionResult(
            should_compact=True,
            reason_code="ECONOMIC_BREAKEVEN_APPROVED",
            breakeven_requests=breakeven,
            combined_breakeven_requests=combined_breakeven,
            effective_horizon_requests=horizon,
            carried_debt_tokens=carried_debt_tokens,
            net_estimated_savings=max(0, net_savings),
            explanation=(
                f"Subtask boundary reached and economic breakeven verified: "
                f"horizon ({horizon} requests) >= required ({required_horizon} reqs). "
                f"Estimated net savings: ~{net_savings} tokens."
            ),
        )
