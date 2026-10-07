"""Core engine for Mid-Flight Steering and Interactive Execution Intervention.

[INPUT]
- midflight_steering_types: Domain models for directives, injection envelopes, and telemetry.

[OUTPUT]
- MidFlightSteeringCoordinator: Non-blocking directive queue and checkpoint injection manager.

[POS]
Coordinates in-flight user steering during long-running tasks, enabling live requirements
appending and dynamic direction tuning without killing active execution.
"""

from __future__ import annotations

import time
import uuid

from myrm_agent_harness.agent.context_management.midflight_steering.midflight_steering_types import (
    MidFlightDirective,
    SteeringDirectiveStatus,
    SteeringExecutionTelemetry,
    SteeringInjectionEnvelope,
    SteeringIntentKind,
)


class MidFlightSteeringCoordinator:
    """Non-blocking directive queue and checkpoint injection coordinator for active sessions."""

    def __init__(self) -> None:
        # Maps session_id to list of queued directives
        self._pending_queues: dict[str, list[MidFlightDirective]] = {}
        # Maps session_id to list of all historical directives
        self._all_directives: dict[str, list[MidFlightDirective]] = {}

    def enqueue_directive(
        self,
        session_id: str,
        task_id: str,
        content: str,
        intent: SteeringIntentKind = SteeringIntentKind.APPEND_REQUIREMENT,
        priority: int = 10,
    ) -> MidFlightDirective:
        """Enqueues a user directive for non-blocking injection at the next execution checkpoint."""
        directive = MidFlightDirective(
            directive_id=f"dir_{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            task_id=task_id,
            content=content.strip(),
            intent=intent,
            priority=priority,
            status=SteeringDirectiveStatus.QUEUED,
            created_at=time.time(),
        )

        pending = self._pending_queues.setdefault(session_id, [])
        # Insert sorted by priority descending
        insert_idx = 0
        while insert_idx < len(pending) and pending[insert_idx].priority >= priority:
            insert_idx += 1
        pending.insert(insert_idx, directive)

        history = self._all_directives.setdefault(session_id, [])
        history.append(directive)

        return directive

    def poll_and_inject_at_checkpoint(
        self, session_id: str, checkpoint_step_index: int
    ) -> SteeringInjectionEnvelope | None:
        """Atomically drains pending directives and composes an injection envelope if present."""
        pending = self._pending_queues.get(session_id)
        if not pending:
            return None

        # Atomically pop all queued directives
        to_inject: list[MidFlightDirective] = list(pending)
        self._pending_queues[session_id] = []

        now = time.time()
        for d in to_inject:
            d.mark_injected()

        # Compose structured in-flight steering prompt
        lines: list[str] = [
            f'<in-flight-steering checkpoint_step="{checkpoint_step_index}">'
        ]
        for d in to_inject:
            lines.append(
                f"- [Direct User Guidance ({d.intent.value})]: {d.content}"
            )
        lines.append("</in-flight-steering>")
        composed_prompt = "\n".join(lines)

        return SteeringInjectionEnvelope(
            session_id=session_id,
            checkpoint_step_index=checkpoint_step_index,
            injected_directives=to_inject,
            composed_steering_prompt=composed_prompt,
            injected_timestamp=now,
        )

    def mark_acknowledged(self, session_id: str, directive_id: str) -> bool:
        """Marks an injected directive as acknowledged by the agent execution runtime."""
        history = self._all_directives.get(session_id, [])
        for d in history:
            if d.directive_id == directive_id:
                d.mark_acknowledged()
                return True
        return False

    def get_telemetry(self, session_id: str) -> SteeringExecutionTelemetry:
        """Calculates responsiveness metrics and queue state for observability dashboards."""
        history = self._all_directives.get(session_id, [])
        pending = self._pending_queues.get(session_id, [])

        total = len(history)
        injected_count = sum(1 for d in history if d.status in (
            SteeringDirectiveStatus.INJECTED, SteeringDirectiveStatus.ACKNOWLEDGED
        ))
        acknowledged_count = sum(1 for d in history if d.status == SteeringDirectiveStatus.ACKNOWLEDGED)

        # Compute average latency from creation to injection
        latencies_ms: list[float] = [
            (d.injected_at - d.created_at) * 1000.0
            for d in history
            if d.injected_at is not None
        ]
        avg_latency = (sum(latencies_ms) / len(latencies_ms)) if latencies_ms else 0.0

        return SteeringExecutionTelemetry(
            session_id=session_id,
            total_received=total,
            injected_count=injected_count,
            acknowledged_count=acknowledged_count,
            pending_queue_length=len(pending),
            avg_latency_to_injection_ms=round(avg_latency, 2),
            active_directives=list(history),
        )

    def clear_session(self, session_id: str) -> None:
        """Disposes steering queues and clears telemetry history for session."""
        self._pending_queues.pop(session_id, None)
        self._all_directives.pop(session_id, None)
