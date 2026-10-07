from __future__ import annotations

import datetime
from threading import Lock

from myrm_agent_harness.agent.streaming.graceful_interruption_types import (
    GracefulInterruptionReport,
    InterruptedArtifactSnapshot,
    InterruptionSignalKind,
)


class GracefulTurnInterrupter:
    """Thread-safe graceful turn interruption sentinel and clean breakpoint detector."""

    def __init__(
        self,
        session_id: str,
        turn_index: int = 1,
    ) -> None:
        self._session_id = session_id
        self._turn_index = turn_index
        self._lock = Lock()

        self._pending_signal: InterruptionSignalKind | None = None
        self._preempting_message: str | None = None
        self._is_interrupted: bool = False

        self._interrupted_step: int = 0
        self._total_planned_steps: int = 0
        self._executed_tool_summaries: list[str] = []

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def turn_index(self) -> int:
        return self._turn_index

    @property
    def is_interruption_requested(self) -> bool:
        with self._lock:
            return self._pending_signal is not None

    @property
    def is_interrupted(self) -> bool:
        with self._lock:
            return self._is_interrupted

    def request_graceful_interruption(
        self,
        signal_kind: InterruptionSignalKind = InterruptionSignalKind.GRACEFUL_PREEMPTION,
        preempting_message: str | None = None,
    ) -> None:
        """Post a graceful preemption or stop request from external user or orchestrator."""
        with self._lock:
            self._pending_signal = signal_kind
            self._preempting_message = preempting_message

    def record_successful_step(self, tool_summary: str) -> None:
        """Record completed tool summary to retain execution credit."""
        with self._lock:
            self._executed_tool_summaries.append(tool_summary)

    def check_breakpoint_and_interrupt(
        self,
        current_step: int,
        total_steps: int,
        executed_tool_summary: str | None = None,
    ) -> bool:
        """Probe whether execution should halt at the current atomic breakpoint.

        Returns True if a graceful interruption has been triggered and committed.
        """
        with self._lock:
            if executed_tool_summary is not None:
                self._executed_tool_summaries.append(executed_tool_summary)

            if self._pending_signal is not None:
                self._is_interrupted = True
                self._interrupted_step = current_step
                self._total_planned_steps = total_steps
                return True
            return False

    def generate_report(
        self,
        preserved_artifacts: list[InterruptedArtifactSnapshot],
    ) -> GracefulInterruptionReport:
        """Produce the comprehensive post-interruption diagnostic report."""
        with self._lock:
            signal = self._pending_signal or InterruptionSignalKind.GRACEFUL_PREEMPTION
            return GracefulInterruptionReport(
                session_id=self._session_id,
                turn_index=self._turn_index,
                step_index_interrupted=self._interrupted_step,
                total_planned_steps=self._total_planned_steps,
                signal_kind=signal,
                preempting_user_message=self._preempting_message,
                preserved_artifacts=list(preserved_artifacts),
                executed_tool_summaries=list(self._executed_tool_summaries),
                timestamp_iso=datetime.datetime.now(datetime.UTC).isoformat(),
            )

    def reset_for_next_turn(self, next_turn_index: int | None = None) -> None:
        """Reset internal flags for subsequent execution turn."""
        with self._lock:
            self._pending_signal = None
            self._preempting_message = None
            self._is_interrupted = False
            self._interrupted_step = 0
            self._total_planned_steps = 0
            self._executed_tool_summaries.clear()
            if next_turn_index is not None:
                self._turn_index = next_turn_index
            else:
                self._turn_index += 1
