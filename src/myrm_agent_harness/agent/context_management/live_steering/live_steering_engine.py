"""Core engine for Live Response Steering and Mid-Generation Correction Channel (Item 219).

[INPUT]
- LiveSteeringInstruction: User intervention submitted during ongoing execution.
- ToolSeamAnchor: Coordinates of the tool execution seam.
- LiveSteeringConfig: Tunable limits, queue caps, and suppression flags.

[OUTPUT]
- LiveResponseSteeringEngine: Non-blocking in-flight steering gateway and causal reconciler.
- LiveSteeringInjectionResult: Mounted steering payload for prompt observation injection.
- LiveSteeringReconciledHistory: Causally aligned conversational history preserving mid-flight steers.

[POS]
- Provides in-flight course correction and tool suppression without aborting whole runs,
- bridging human real-time intent with ongoing LLM generation and tool calling.
"""

from __future__ import annotations

import threading
from typing import Mapping

from .live_steering_types import (
    LiveSteeringConfig,
    LiveSteeringInjectionResult,
    LiveSteeringInstruction,
    LiveSteeringReconciledHistory,
    LiveSteerStatus,
    SteerSeverity,
    ToolSeamAnchor,
)


class LiveResponseSteeringEngine:
    """Non-blocking gateway managing live steering directives and causal history reconciliation."""

    def __init__(self, config: LiveSteeringConfig | None = None) -> None:
        self._config: LiveSteeringConfig = config or LiveSteeringConfig()
        self._pending_queues: dict[str, list[LiveSteeringInstruction]] = {}
        self._applied_records: dict[str, list[LiveSteeringInstruction]] = {}
        self._lock: threading.Lock = threading.Lock()

    @property
    def config(self) -> LiveSteeringConfig:
        """Returns the active configuration."""
        return self._config

    def _make_key(self, session_id: str, turn_id: str | None = None) -> str:
        if turn_id:
            return f"{session_id}::{turn_id}"
        return session_id

    def submit_live_steering(
        self,
        instruction: LiveSteeringInstruction,
    ) -> LiveSteeringInstruction:
        """Submits an in-flight steering directive into the non-blocking queue.

        Args:
            instruction: Strongly typed user steering instruction.

        Returns:
            The queued LiveSteeringInstruction.

        Raises:
            ValueError: If instruction content is blank.
        """
        clean_content = instruction.content.strip()
        if not clean_content:
            raise ValueError("Steering instruction content cannot be empty.")

        # Clamp overly long directives to prevent context blowout
        if len(clean_content) > self._config.max_steering_content_length:
            clean_content = clean_content[: self._config.max_steering_content_length]
            instruction.content = clean_content

        key = self._make_key(instruction.session_id, instruction.turn_id)

        with self._lock:
            if key not in self._pending_queues:
                self._pending_queues[key] = []

            queue = self._pending_queues[key]

            # If supersede is enabled, mark older pending directives in the same turn as superseded
            if self._config.allow_directive_supersede:
                for pending in queue:
                    if pending.status == LiveSteerStatus.QUEUED:
                        pending.mark_superseded()
                # Retain only non-superseded or active directives
                queue = [p for p in queue if p.status == LiveSteerStatus.QUEUED]
                self._pending_queues[key] = queue

            # Queue capacity eviction guard
            if len(queue) >= self._config.max_pending_queue_size:
                evicted = queue.pop(0)
                evicted.mark_discarded()

            queue.append(instruction)

        return instruction

    def has_pending_steering(
        self,
        session_id: str,
        turn_id: str | None = None,
    ) -> bool:
        """Non-blocking O(1) probe checking whether a steering directive is waiting.

        Called by generation loops and tool seam coordinators at every step boundary.
        """
        key = self._make_key(session_id, turn_id)
        with self._lock:
            queue = self._pending_queues.get(key)
            if not queue:
                return False
            return any(item.status == LiveSteerStatus.QUEUED for item in queue)

    def peek_pending_steering(
        self,
        session_id: str,
        turn_id: str | None = None,
    ) -> LiveSteeringInstruction | None:
        """Inspects the front queued steering instruction without consuming it."""
        key = self._make_key(session_id, turn_id)
        with self._lock:
            queue = self._pending_queues.get(key)
            if not queue:
                return None
            for item in queue:
                if item.status == LiveSteerStatus.QUEUED:
                    return item
            return None

    def intercept_at_tool_seam(
        self,
        session_id: str,
        turn_id: str,
        seam_anchor: ToolSeamAnchor,
        pending_tool_ids: list[str] | None = None,
    ) -> LiveSteeringInjectionResult | None:
        """Intercepts execution at a tool boundary and produces an injection payload.

        Args:
            session_id: Session identifier.
            turn_id: Current conversational turn identifier.
            seam_anchor: Execution seam coordinates.
            pending_tool_ids: Optional upcoming tool call IDs that can be suppressed.

        Returns:
            LiveSteeringInjectionResult if an instruction was consumed, or None.
        """
        key = self._make_key(session_id, turn_id)

        with self._lock:
            queue = self._pending_queues.get(key)
            if not queue:
                return None

            candidate: LiveSteeringInstruction | None = None
            for idx, item in enumerate(queue):
                if item.status == LiveSteerStatus.QUEUED:
                    candidate = queue.pop(idx)
                    break

            if candidate is None:
                return None

            candidate.mark_applied(step_index=seam_anchor.step_index)

            # Record in applied history for causal replay
            if key not in self._applied_records:
                self._applied_records[key] = []
            self._applied_records[key].append(candidate)

        # Evaluate tool suppression policy
        suppressed_tools: list[str] = []
        if (
            self._config.enable_tool_suppression
            and pending_tool_ids
            and candidate.severity
            in (SteerSeverity.ABORT_BRANCH, SteerSeverity.URGENT_INTERRUPT)
        ):
            suppressed_tools = list(pending_tool_ids)

        # Construct causal prompt payload
        causal_tag = f"live-steer::{candidate.instruction_id}::step-{seam_anchor.step_index}"
        injected_prompt = self._format_steering_prompt(candidate, seam_anchor, suppressed_tools)

        return LiveSteeringInjectionResult(
            applied=True,
            instruction_id=candidate.instruction_id,
            seam_step_index=seam_anchor.step_index,
            injected_prompt_content=injected_prompt,
            suppressed_tool_ids=suppressed_tools,
            causal_tag=causal_tag,
        )

    def _format_steering_prompt(
        self,
        instruction: LiveSteeringInstruction,
        anchor: ToolSeamAnchor,
        suppressed_tools: list[str],
    ) -> str:
        lines: list[str] = [
            f'<in_flight_steering instruction_id="{instruction.instruction_id}" step="{anchor.step_index}" severity="{instruction.severity.value}" channel="{instruction.channel_mode.value}">',
            "[Real-Time User Steering Interjection]:",
            instruction.content,
        ]

        if anchor.completed_tool_name:
            lines.append(f"[Seam Context]: Completed tool '{anchor.completed_tool_name}'.")

        if suppressed_tools:
            lines.append(
                f"[Tool Suppression Notice]: Pending tools {suppressed_tools} were cancelled by this steering directive."
            )

        lines.extend(
            [
                "[Guidance for Model]:",
                "The user interjected while active generation was in flight. Immediately adjust subsequent actions and reasoning to honor this directive without discarding prior valid findings.",
                "</in_flight_steering>",
            ]
        )
        return "\n".join(lines)

    def reconcile_causal_history(
        self,
        session_id: str,
        turn_id: str,
        raw_messages: list[dict[str, object]],
    ) -> LiveSteeringReconciledHistory:
        """Causally reconciles chat history by weaving mid-flight steers at their true seam points.

        Args:
            session_id: Session identifier.
            turn_id: Current conversational turn identifier.
            raw_messages: Original conversational message sequence.

        Returns:
            LiveSteeringReconciledHistory containing ordered messages and metadata.
        """
        key = self._make_key(session_id, turn_id)
        with self._lock:
            applied = list(self._applied_records.get(key, []))

        if not applied:
            return LiveSteeringReconciledHistory(
                session_id=session_id,
                turn_id=turn_id,
                total_steers_applied=0,
                reconciled_messages=list(raw_messages),
            )

        reconciled: list[dict[str, object]] = []
        steer_by_step: dict[int, list[LiveSteeringInstruction]] = {}
        for item in applied:
            target_step = item.target_step_index if item.target_step_index is not None else 0
            steer_by_step.setdefault(target_step, []).append(item)

        for step_idx, message in enumerate(raw_messages):
            reconciled.append(dict(message))
            if step_idx in steer_by_step:
                for st in steer_by_step[step_idx]:
                    steer_msg: dict[str, object] = {
                        "role": "user",
                        "content": f"[In-Flight Correction #{st.instruction_id}]: {st.content}",
                        "is_mid_generation_steer": True,
                        "steer_instruction_id": st.instruction_id,
                        "severity": st.severity.value,
                    }
                    reconciled.append(steer_msg)

        return LiveSteeringReconciledHistory(
            session_id=session_id,
            turn_id=turn_id,
            total_steers_applied=len(applied),
            reconciled_messages=reconciled,
        )

    def get_applied_instructions(
        self,
        session_id: str,
        turn_id: str | None = None,
    ) -> list[LiveSteeringInstruction]:
        """Returns copies of all applied steering instructions for audit and inspection."""
        key = self._make_key(session_id, turn_id)
        with self._lock:
            records = self._applied_records.get(key, [])
            return list(records)

    def clear_session(self, session_id: str) -> None:
        """Cleans up all pending and applied steering records for a session."""
        with self._lock:
            prefix = f"{session_id}::"
            to_del_pending = [
                k for k in self._pending_queues if k == session_id or k.startswith(prefix)
            ]
            for k in to_del_pending:
                self._pending_queues.pop(k, None)

            to_del_applied = [
                k for k in self._applied_records if k == session_id or k.startswith(prefix)
            ]
            for k in to_del_applied:
                self._applied_records.pop(k, None)

    def get_telemetry(self, session_id: str) -> dict[str, object]:
        """Provides telemetry for live steering activity across a session."""
        with self._lock:
            prefix = f"{session_id}::"
            pending_count = sum(
                len(q)
                for k, q in self._pending_queues.items()
                if k == session_id or k.startswith(prefix)
            )
            applied_count = sum(
                len(r)
                for k, r in self._applied_records.items()
                if k == session_id or k.startswith(prefix)
            )

        return {
            "session_id": session_id,
            "pending_steers": pending_count,
            "applied_steers": applied_count,
        }
