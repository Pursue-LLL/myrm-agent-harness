"""Declarative Saga Execution Engine with Reverse LIFO Compensation.

Provides transaction-like rollback for multi-step Agent workflows when an error
or user abort occurs, executing registered compensating hooks in reverse order.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from myrm_agent_harness.core.security.saga_dual_engine.types import (
    JsonScalar,
    SagaRollbackError,
    SagaStep,
    ToolIntent,
)

logger = logging.getLogger(__name__)

CompensatorCallable = Callable[[Mapping[str, JsonScalar]], bool]


class SagaExecutionEngine:
    """Engine managing executed operation steps and triggering reverse LIFO compensation."""

    def __init__(self) -> None:
        self._steps: list[SagaStep] = []
        self._compensators: dict[str, CompensatorCallable] = {}

    def register_compensator(self, name: str, handler: CompensatorCallable) -> None:
        """Register a named reverse compensating action handler."""
        self._compensators[name] = handler

    def record_step(
        self,
        tool_name: str,
        intent: ToolIntent,
        params: Mapping[str, JsonScalar],
        compensator_name: str | None = None,
        compensation_params: Mapping[str, JsonScalar] | None = None,
    ) -> SagaStep:
        """Record an executed operational step in the Saga transaction log."""
        step = SagaStep(
            step_id=f"step-{uuid.uuid4().hex[:10]}",
            tool_name=tool_name,
            intent=intent,
            params=dict(params),
            compensator_name=compensator_name,
            compensation_params=dict(compensation_params) if compensation_params is not None else {},
            status="EXECUTED",
            executed_at=datetime.now(UTC).isoformat(),
        )
        self._steps.append(step)
        return step

    @property
    def step_count(self) -> int:
        """Total steps currently recorded."""
        return len(self._steps)

    def rollback(self) -> list[tuple[str, bool]]:
        """Rollback executed steps by invoking registered compensators in reverse LIFO order."""
        results: list[tuple[str, bool]] = []
        failures: list[str] = []

        # Execute in reverse LIFO order
        for step in reversed(self._steps):
            if step.intent == ToolIntent.ACQUISITION:
                # Acquisition steps are read-only and reversible without compensation
                results.append((f"{step.step_id}::{step.tool_name}", True))
                continue

            if not step.compensator_name:
                logger.warning("Step %s has no registered compensator; skipped", step.step_id)
                results.append((f"{step.step_id}::{step.tool_name}", True))
                continue

            handler = self._compensators.get(step.compensator_name)
            if handler is None:
                err_msg = f"Compensator '{step.compensator_name}' not found for step {step.step_id}"
                logger.error(err_msg)
                failures.append(err_msg)
                results.append((f"{step.step_id}::{step.tool_name}", False))
                continue

            try:
                success = handler(step.compensation_params)
                if not success:
                    failures.append(f"Compensator '{step.compensator_name}' returned False for step {step.step_id}")
                results.append((f"{step.step_id}::{step.tool_name}", success))
            except Exception as exc:
                err_msg = f"Compensator '{step.compensator_name}' failed with error: {exc}"
                logger.error(err_msg)
                failures.append(err_msg)
                results.append((f"{step.step_id}::{step.tool_name}", False))

        self._steps.clear()
        if failures:
            raise SagaRollbackError(f"Saga rollback encountered {len(failures)} failure(s): {failures}")

        return results

    def clear(self) -> None:
        """Clear recorded steps after successful workflow completion."""
        self._steps.clear()
