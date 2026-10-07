"""Core engine for Mid-Run Barge-In Steering and Safe Execution Gap Interventions.

Provides non-destructive mid-flight intervention queues, safe steering gate inspections
between tool call boundaries, and dynamic intent redirection without forcing hard task restarts.
"""

from __future__ import annotations

import time
import uuid
from myrm_agent_harness.agent.context_management.barge_in_steering.barge_in_steering_types import (
    BargeInMessage,
    BargeInSteeringConfig,
    InterventionMode,
    SteeringPointGateResult,
)


class MidRunBargeInSteeringEngine:
    """Engine managing asynchronous mid-run steering queues and safe gate interventions."""

    def __init__(self, config: BargeInSteeringConfig | None = None) -> None:
        self.config: BargeInSteeringConfig = config or BargeInSteeringConfig()
        self._queues: dict[str, list[BargeInMessage]] = {}
        self._history: dict[str, list[BargeInMessage]] = {}

    def post_intervention(
        self,
        session_id: str,
        content: str,
        mode: InterventionMode | None = None,
        metadata: dict[str, str] | None = None,
    ) -> BargeInMessage:
        """Enqueue an in-flight intervention directive while the agent run is executing."""
        resolved_mode = mode or self.config.default_mode
        intervention_id = f"barge_{uuid.uuid4().hex[:10]}"

        message = BargeInMessage(
            intervention_id=intervention_id,
            session_id=session_id,
            content=content.strip(),
            mode=resolved_mode,
            metadata=metadata or {},
            created_at=time.time(),
        )

        queue = self._queues.setdefault(session_id, [])
        if len(queue) >= self.config.max_pending_queue_size:
            # Drop the oldest pending message if queue exceeds bound
            queue.pop(0)
        queue.append(message)
        return message

    def inspect_gate_and_inject(
        self,
        session_id: str,
        current_step_index: int,
        plan_summary: str | None = None,
    ) -> SteeringPointGateResult:
        """Inspect safe execution gate (between tool steps) and inject high-priority steering directives."""
        queue = self._queues.get(session_id, [])
        if not queue:
            return SteeringPointGateResult(
                has_intervention=False,
                should_suspend=False,
                is_hard_abort=False,
                injected_message=None,
                applied_intervention_id=None,
                remaining_pending_count=0,
            )

        # Dequeue the oldest pending intervention
        intervention = queue.pop(0)
        self._history.setdefault(session_id, []).append(intervention)

        # 1. Hard Abort disposition: immediately halt execution
        if intervention.mode == InterventionMode.HARD_ABORT:
            if self.config.drain_on_abort:
                self._queues[session_id] = []
            return SteeringPointGateResult(
                has_intervention=True,
                should_suspend=True,
                is_hard_abort=True,
                injected_message=None,
                applied_intervention_id=intervention.intervention_id,
                remaining_pending_count=len(self._queues.get(session_id, [])),
            )

        # 2. Barge-in Steering disposition: construct non-destructive system redirect message
        plan_context = f" Current active plan: '{plan_summary}'." if plan_summary else ""
        injected_content = (
            f"{self.config.steering_instruction_prefix}{intervention.content}\n"
            f"[Execution Directive: The user submitted an in-flight steering directive at step #{current_step_index}.{plan_context} "
            "DO NOT abort or wipe earlier completed progress. Preserve all valid files and state generated so far, "
            "and dynamically adapt your subsequent steps to align with the user's updated directive.]"
        )

        injected_message = {
            "role": "system",
            "content": injected_content,
            "name": "system_steering",
        }

        return SteeringPointGateResult(
            has_intervention=True,
            should_suspend=False,
            is_hard_abort=False,
            injected_message=injected_message,
            applied_intervention_id=intervention.intervention_id,
            remaining_pending_count=len(queue),
        )

    def discard_pending(self, session_id: str) -> int:
        """Purge all pending interventions for a session."""
        queue = self._queues.pop(session_id, [])
        return len(queue)

    def get_pending_interventions(self, session_id: str) -> list[BargeInMessage]:
        """List currently pending unconsumed interventions."""
        return list(self._queues.get(session_id, []))

    def get_history(self, session_id: str) -> list[BargeInMessage]:
        """List consumed intervention history for auditing."""
        return list(self._history.get(session_id, []))

    def merge_incremental_intent(
        self,
        original_prompt: str,
        intervention: BargeInMessage,
    ) -> str:
        """Synthesize original prompt with in-flight barge-in intervention non-destructively."""
        return (
            f"Original Intent: {original_prompt}\n"
            f"Mid-Run User Correction ({intervention.mode.value}): {intervention.content}"
        )
