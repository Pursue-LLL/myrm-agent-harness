"""Subtask boundary lifecycle hook triggering economic context compaction evaluations.

[INPUT]
- CompactionDecisionResult, PlanStep, PlanStepStatus from economic_compact_types.
- CompactionEconomicsCalculator from compaction_economics_calculator.

[OUTPUT]
- SubtaskBoundaryHook: Lifecycle hook listening to plan step completion events and invoking
  economic breakeven evaluations.

[POS]
Event-driven hook integrating plan/subtask completions with active online compaction.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from .compaction_economics_calculator import CompactionEconomicsCalculator
from .economic_compact_types import (
    CompactionDecisionResult,
    PlanStep,
    PlanStepStatus,
)


class SubtaskBoundaryHook:
    """Manages plan step lifecycles and coordinates subtask boundary compaction triggers."""

    def __init__(
        self,
        calculator: CompactionEconomicsCalculator,
        initial_steps: Sequence[PlanStep] = (),
    ) -> None:
        self._calculator = calculator
        self._steps: List[PlanStep] = list(initial_steps)
        self._step_map: Dict[str, PlanStep] = {s.step_id: s for s in self._steps}
        self._completed_requests: int = sum(
            s.requests_spent for s in self._steps if s.status == PlanStepStatus.COMPLETED
        )

    @property
    def calculator(self) -> CompactionEconomicsCalculator:
        return self._calculator

    def set_plan(self, steps: Sequence[PlanStep]) -> None:
        """Replace the active plan step collection."""
        self._steps = list(steps)
        self._step_map = {s.step_id: s for s in self._steps}
        self._completed_requests = sum(
            s.requests_spent for s in self._steps if s.status == PlanStepStatus.COMPLETED
        )

    def add_step(self, step: PlanStep) -> None:
        """Append a new plan step to the active plan."""
        self._steps.append(step)
        self._step_map[step.step_id] = step

    def get_remaining_steps(self) -> Sequence[PlanStep]:
        """Return steps that are still pending or in progress."""
        return [
            s
            for s in self._steps
            if s.status in (PlanStepStatus.PENDING, PlanStepStatus.IN_PROGRESS)
        ]

    def get_completed_steps(self) -> Sequence[PlanStep]:
        """Return steps that have completed."""
        return [s for s in self._steps if s.status == PlanStepStatus.COMPLETED]

    def total_completed_requests(self) -> int:
        """Return total requests recorded across completed steps."""
        return self._completed_requests

    def mark_step_completed(
        self,
        step_id: str,
        requests_spent: int = 1,
        current_tokens: int = 0,
        carried_debt_tokens: int = 0,
        estimated_write_tokens: Optional[int] = None,
        estimated_memo_tokens: Optional[int] = None,
    ) -> CompactionDecisionResult:
        """Mark a plan step as completed and evaluate economic compaction at the subtask boundary."""
        if step_id in self._step_map:
            old_step = self._step_map[step_id]
            updated_step = PlanStep(
                step_id=old_step.step_id,
                title=old_step.title,
                status=PlanStepStatus.COMPLETED,
                requests_spent=max(1, requests_spent),
                metadata=old_step.metadata,
            )
            self._step_map[step_id] = updated_step
            # Replace in list maintaining order
            for idx, s in enumerate(self._steps):
                if s.step_id == step_id:
                    self._steps[idx] = updated_step
                    break
        else:
            new_step = PlanStep(
                step_id=step_id,
                title=f"Step {step_id}",
                status=PlanStepStatus.COMPLETED,
                requests_spent=max(1, requests_spent),
            )
            self._steps.append(new_step)
            self._step_map[step_id] = new_step

        self._completed_requests += max(1, requests_spent)

        return self._calculator.evaluate_decision(
            current_tokens=current_tokens,
            plan_steps=self._steps,
            completed_step_requests=self._completed_requests,
            carried_debt_tokens=carried_debt_tokens,
            is_subtask_boundary=True,
            estimated_write_tokens=estimated_write_tokens,
            estimated_memo_tokens=estimated_memo_tokens,
        )
