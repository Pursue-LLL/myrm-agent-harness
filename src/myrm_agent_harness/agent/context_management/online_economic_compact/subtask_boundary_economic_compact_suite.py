# [INPUT]: CompactionDecisionResult, CompactionEconomicsCalculator, CompactionEconomicsConfig, ContinuationTurnPayload, EconomicCompactionLedger, OnlineCompactContinuationEngine, PlanStep, SubtaskBoundaryHook
# [OUTPUT]: SubtaskBoundaryOnlineContextCompactAndEconomicBreakevenSuite
# [POS]: agent/context_management/online_economic_compact/subtask_boundary_economic_compact_suite.py

"""Comprehensive facade suite for subtask-boundary online context compaction and economics.

[INPUT]
- CompactionDecisionResult, CompactionEconomicsCalculator, CompactionEconomicsConfig, ContinuationTurnPayload,
  EconomicCompactionLedger, OnlineCompactContinuationEngine, PlanStep, SubtaskBoundaryHook:
  Domain types, calculators, event hooks, and transition engines from online_economic_compact.

[OUTPUT]
- SubtaskBoundaryOnlineContextCompactAndEconomicBreakevenSuite: Unified facade managing subtask boundaries,
  mathematical economic breakeven evaluations, carried debt throttling, and new-turn continuity.

[POS]
Top-level entrypoint for NVIDIA SoL-Pi inspired online context compaction and economics.
"""

from __future__ import annotations

from typing import Mapping, Optional, Sequence, Tuple

from .compaction_economics_calculator import CompactionEconomicsCalculator
from .economic_compact_types import (
    CompactionDecisionResult,
    CompactionEconomicsConfig,
    ContinuationTurnPayload,
    EconomicCompactionLedger,
    PlanStep,
)
from .online_compact_continuation_engine import OnlineCompactContinuationEngine
from .subtask_boundary_hook import SubtaskBoundaryHook


class SubtaskBoundaryOnlineContextCompactAndEconomicBreakevenSuite:
    """Orchestrates plan step boundaries, economic breakeven decisions, and seamless new-turn continuation."""

    def __init__(
        self,
        config: CompactionEconomicsConfig | None = None,
        initial_steps: Sequence[PlanStep] = (),
    ) -> None:
        self._config = config or CompactionEconomicsConfig()
        self._calculator = CompactionEconomicsCalculator(config=self._config)
        self._hook = SubtaskBoundaryHook(calculator=self._calculator, initial_steps=initial_steps)
        self._ledger = EconomicCompactionLedger()
        self._continuation_engine = OnlineCompactContinuationEngine(ledger=self._ledger)

    @property
    def config(self) -> CompactionEconomicsConfig:
        return self._config

    @property
    def calculator(self) -> CompactionEconomicsCalculator:
        return self._calculator

    @property
    def hook(self) -> SubtaskBoundaryHook:
        return self._hook

    @property
    def ledger(self) -> EconomicCompactionLedger:
        return self._ledger

    def set_plan(self, steps: Sequence[PlanStep]) -> None:
        """Register the entire task plan."""
        self._hook.set_plan(steps)

    def add_plan_step(self, step: PlanStep) -> None:
        """Add an individual step to the task plan."""
        self._hook.add_step(step)

    def get_remaining_steps(self) -> Sequence[PlanStep]:
        """Return steps awaiting execution."""
        return self._hook.get_remaining_steps()

    def get_completed_steps(self) -> Sequence[PlanStep]:
        """Return steps that have completed."""
        return self._hook.get_completed_steps()

    def on_subtask_completed(
        self,
        step_id: str,
        requests_spent: int = 1,
        current_tokens: int = 0,
        messages: Sequence[Mapping[str, str]] = (),
        session_turn: int = 1,
    ) -> Tuple[CompactionDecisionResult, Optional[ContinuationTurnPayload]]:
        """Triggered upon subtask completion; evaluates economics and performs continuation if approved."""
        decision = self._hook.mark_step_completed(
            step_id=step_id,
            requests_spent=requests_spent,
            current_tokens=current_tokens,
            carried_debt_tokens=self._ledger.carried_debt_tokens,
        )

        payload: Optional[ContinuationTurnPayload] = None
        if decision.should_compact:
            payload = self._continuation_engine.execute_continuation(
                messages=messages,
                decision=decision,
                completed_steps=self.get_completed_steps(),
                remaining_steps=self.get_remaining_steps(),
                current_tokens=current_tokens,
                session_turn=session_turn,
            )

        return decision, payload

    def check_hard_window_pressure(
        self,
        current_tokens: int,
        messages: Sequence[Mapping[str, str]] = (),
        session_turn: int = 1,
    ) -> Tuple[CompactionDecisionResult, Optional[ContinuationTurnPayload]]:
        """Proactively monitor context window against the hard reserve threshold."""
        decision = self._calculator.evaluate_decision(
            current_tokens=current_tokens,
            plan_steps=list(self.get_completed_steps()) + list(self.get_remaining_steps()),
            completed_step_requests=self._hook.total_completed_requests(),
            carried_debt_tokens=self._ledger.carried_debt_tokens,
            is_subtask_boundary=False,
        )

        payload: Optional[ContinuationTurnPayload] = None
        if decision.should_compact:
            payload = self._continuation_engine.execute_continuation(
                messages=messages,
                decision=decision,
                completed_steps=self.get_completed_steps(),
                remaining_steps=self.get_remaining_steps(),
                current_tokens=current_tokens,
                session_turn=session_turn,
            )

        return decision, payload

    def reset_ledger(self) -> None:
        """Reset economic tracking ledger."""
        self._ledger = EconomicCompactionLedger()
        self._continuation_engine = OnlineCompactContinuationEngine(ledger=self._ledger)

    @classmethod
    def create(
        cls,
        window_reserve_tokens: int = 16_384,
        max_context_tokens: int = 128_000,
        subsequent_compaction_margin: float = 1.5,
    ) -> SubtaskBoundaryOnlineContextCompactAndEconomicBreakevenSuite:
        """Factory constructor for standard configurations."""
        config = CompactionEconomicsConfig(
            window_reserve_tokens=window_reserve_tokens,
            max_context_tokens=max_context_tokens,
            subsequent_compaction_margin=subsequent_compaction_margin,
        )
        return cls(config=config)
