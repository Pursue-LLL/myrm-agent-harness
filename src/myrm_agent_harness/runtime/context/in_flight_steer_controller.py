"""In-flight steering controller for active session redirection.

Allows users to submit preemptive steering guidance during long-running agent
executions and injects high-priority interventions at the next step checkpoint.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence

from .session_fork_steer_types import InFlightSteerInstruction


class InFlightSteerController:
    """Controls in-flight human steering interventions intercepted at step checkpoints."""

    def __init__(self) -> None:
        self._pending_steers: dict[str, list[InFlightSteerInstruction]] = {}
        self._consumed_history: list[InFlightSteerInstruction] = []
        self._counter: int = 0

    def submit_steer(
        self,
        session_id: str,
        instruction: str,
        priority_weight: int = 10,
    ) -> InFlightSteerInstruction:
        """Submit a steering directive while the agent loop is executing."""
        if not instruction.strip():
            raise ValueError("Steering instruction cannot be empty.")

        self._counter += 1
        steer_id = f"steer_{self._counter}_{uuid.uuid4().hex[:6]}"
        steer = InFlightSteerInstruction(
            steer_id=steer_id,
            session_id=session_id,
            instruction=instruction.strip(),
            priority_weight=priority_weight,
            created_at_ms=int(time.time() * 1000),
            consumed_at_ms=None,
        )
        self._pending_steers.setdefault(session_id, []).append(steer)
        return steer

    def has_pending_steer(self, session_id: str) -> bool:
        """Check if pending steering directives exist for this session."""
        return len(self._pending_steers.get(session_id, [])) > 0

    def pending_count(self, session_id: str) -> int:
        """Return the count of pending steering directives for this session."""
        return len(self._pending_steers.get(session_id, []))

    def consume_pending_steers(
        self,
        session_id: str,
    ) -> tuple[InFlightSteerInstruction, ...]:
        """Intercept and consume all pending directives at the step checkpoint.

        Directives are sorted descending by priority_weight (higher number = higher priority).
        """
        steers = self._pending_steers.pop(session_id, [])
        if not steers:
            return ()

        # Stable sort: highest priority_weight first
        sorted_steers = sorted(steers, key=lambda s: s.priority_weight, reverse=True)
        now_ms = int(time.time() * 1000)

        consumed_list: list[InFlightSteerInstruction] = []
        for s in sorted_steers:
            consumed = InFlightSteerInstruction(
                steer_id=s.steer_id,
                session_id=s.session_id,
                instruction=s.instruction,
                priority_weight=s.priority_weight,
                created_at_ms=s.created_at_ms,
                consumed_at_ms=now_ms,
            )
            consumed_list.append(consumed)
            self._consumed_history.append(consumed)

        return tuple(consumed_list)

    @staticmethod
    def format_steer_prompt_block(
        steers: Sequence[InFlightSteerInstruction],
    ) -> str:
        """Format consumed steering instructions into a prompt intervention block."""
        if not steers:
            return ""

        lines = [
            "=== HUMAN STEERING INTERVENTION ===",
            "CRITICAL: The user has explicitly redirected your course of action.",
            "Adjust your current trajectory and prioritize the following directives:",
        ]
        for idx, s in enumerate(steers, start=1):
            lines.append(f"{idx}. [Priority: {s.priority_weight}] {s.instruction}")

        lines.append("=== END STEERING INTERVENTION ===")
        return "\n".join(lines)
