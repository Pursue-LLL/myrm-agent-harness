"""Core coordinator for Long-Running Task Dual-Track Interjection and Preemption Queue Suite (Item 212).

[INPUT]
- dual_track_interjection_types: Enums, directives, snapshots, and configuration contracts.

[OUTPUT]
- DualTrackInterventionCoordinator: Thread-safe coordinator for mid-flight interjections and task preemption.

[POS]
- Safely captures real-time user steering during long tasks, routing immediate corrections into
- step-boundary prompt injections and queuing sequential tasks at the head of execution.
"""

from __future__ import annotations

import threading
import time
import uuid

from myrm_agent_harness.agent.context_management.dual_track_interjection.dual_track_interjection_types import (
    DualTrackInterventionConfig,
    InterventionStatus,
    InterventionTrack,
    PreemptionQueueSnapshot,
    StepBoundaryInjectionResult,
    UserInterventionDirective,
)


class DualTrackInterventionCoordinator:
    """Coordinates dual-track user steering: step-boundary interjections and task queue preemption."""

    def __init__(self, default_config: DualTrackInterventionConfig | None = None) -> None:
        self._default_config = default_config or DualTrackInterventionConfig()
        self._lock = threading.RLock()
        # session_id -> list of pending immediate interjections
        self._interject_buffers: dict[str, list[UserInterventionDirective]] = {}
        # session_id -> list of prioritized preemption queue directives
        self._preemption_queues: dict[str, list[UserInterventionDirective]] = {}
        # session_id -> dict of directive_id -> directive
        self._all_directives: dict[str, dict[str, UserInterventionDirective]] = {}

    def submit_intervention(
        self,
        session_id: str,
        track: InterventionTrack,
        prompt_text: str,
        priority: int = 100,
        config: DualTrackInterventionConfig | None = None,
    ) -> UserInterventionDirective:
        """Submits a user directive into either the step-boundary interject buffer or preemption queue."""
        clean_prompt = prompt_text.strip()
        if not clean_prompt:
            raise ValueError("Intervention prompt_text cannot be empty.")

        cfg = config or self._default_config
        directive_id = f"dir_{uuid.uuid4().hex[:12]}"
        now = time.time()

        directive = UserInterventionDirective(
            directive_id=directive_id,
            session_id=session_id,
            track=track,
            prompt_text=clean_prompt,
            priority=priority,
            status=InterventionStatus.PENDING,
            created_at=now,
        )

        with self._lock:
            session_records = self._all_directives.setdefault(session_id, {})
            session_records[directive_id] = directive

            if track == InterventionTrack.IMMEDIATE_INTERJECT:
                buf = self._interject_buffers.setdefault(session_id, [])
                buf.append(directive)
                # Sort descending by priority, then ascending by creation time
                buf.sort(key=lambda d: (-d.priority, d.created_at))
                # Bounded capacity eviction
                if len(buf) > cfg.max_pending_interjections:
                    evicted = buf.pop()
                    evicted.status = InterventionStatus.EXPIRED

            elif track == InterventionTrack.QUEUE_PREEMPTION:
                queue = self._preemption_queues.setdefault(session_id, [])
                queue.append(directive)
                # Sort descending by priority, then ascending by creation time
                queue.sort(key=lambda d: (-d.priority, d.created_at))
                # Bounded queue depth
                if len(queue) > cfg.max_preemption_queue_depth:
                    evicted = queue.pop()
                    evicted.status = InterventionStatus.EXPIRED

        return directive

    def drain_step_boundary_interjections(
        self,
        session_id: str,
        config: DualTrackInterventionConfig | None = None,
    ) -> StepBoundaryInjectionResult:
        """Atomically drains pending interjections at step boundary and formats them into an observation."""
        cfg = config or self._default_config
        now = time.time()

        with self._lock:
            buf = self._interject_buffers.get(session_id, [])
            if not buf:
                return StepBoundaryInjectionResult(
                    interjection_applied=False,
                    injected_message=None,
                    consumed_directive_ids=[],
                    remaining_pending_count=0,
                )

            active_directives: list[UserInterventionDirective] = []
            for d in buf:
                if d.status == InterventionStatus.PENDING:
                    if now - d.created_at > cfg.expiration_seconds:
                        d.status = InterventionStatus.EXPIRED
                    else:
                        active_directives.append(d)

            # Clear active buffer
            self._interject_buffers[session_id] = []

            if not active_directives:
                return StepBoundaryInjectionResult(
                    interjection_applied=False,
                    injected_message=None,
                    consumed_directive_ids=[],
                    remaining_pending_count=0,
                )

            consumed_ids: list[str] = []
            bullet_points: list[str] = []

            for d in active_directives:
                d.status = InterventionStatus.CONSUMED
                d.consumed_at = now
                consumed_ids.append(d.directive_id)
                bullet_points.append(f"- {d.prompt_text}")

            bullets_formatted = "\n".join(bullet_points)
            formatted_content = (
                f"<{cfg.interjection_xml_tag}>\n"
                f"{cfg.interjection_prefix_label}\n"
                f"{bullets_formatted}\n"
                f"</{cfg.interjection_xml_tag}>"
            )

            message: dict[str, object] = {
                "role": "user",
                "content": formatted_content,
            }

            return StepBoundaryInjectionResult(
                interjection_applied=True,
                injected_message=message,
                consumed_directive_ids=consumed_ids,
                remaining_pending_count=0,
            )

    def pop_next_preemption_task(
        self, session_id: str, config: DualTrackInterventionConfig | None = None
    ) -> UserInterventionDirective | None:
        """Pops and returns the highest-priority pending task from the preemption queue."""
        cfg = config or self._default_config
        now = time.time()

        with self._lock:
            queue = self._preemption_queues.get(session_id, [])
            while queue:
                candidate = queue.pop(0)
                if candidate.status == InterventionStatus.PENDING:
                    if now - candidate.created_at > cfg.expiration_seconds:
                        candidate.status = InterventionStatus.EXPIRED
                        continue
                    candidate.status = InterventionStatus.CONSUMED
                    candidate.consumed_at = now
                    return candidate

        return None

    def get_preemption_queue_snapshot(self, session_id: str) -> PreemptionQueueSnapshot:
        """Returns snapshot of pending tasks in the preemption queue."""
        with self._lock:
            queue = self._preemption_queues.get(session_id, [])
            pending = [d for d in queue if d.status == InterventionStatus.PENDING]
            return PreemptionQueueSnapshot(
                session_id=session_id,
                queued_directives=list(pending),
                queue_length=len(pending),
            )

    def cancel_intervention(self, session_id: str, directive_id: str) -> bool:
        """Cancels a pending intervention directive before it is consumed."""
        with self._lock:
            records = self._all_directives.get(session_id, {})
            directive = records.get(directive_id)
            if not directive or directive.status != InterventionStatus.PENDING:
                return False

            directive.status = InterventionStatus.CANCELLED

            # Clean from interject buffer
            buf = self._interject_buffers.get(session_id, [])
            self._interject_buffers[session_id] = [d for d in buf if d.directive_id != directive_id]

            # Clean from preemption queue
            queue = self._preemption_queues.get(session_id, [])
            self._preemption_queues[session_id] = [d for d in queue if d.directive_id != directive_id]

            return True

    def clear_session(self, session_id: str) -> None:
        """Clears all buffers, queues, and directive tracking for a session."""
        with self._lock:
            self._interject_buffers.pop(session_id, None)
            self._preemption_queues.pop(session_id, None)
            self._all_directives.pop(session_id, None)
