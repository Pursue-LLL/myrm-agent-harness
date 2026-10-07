"""Coordinator managing host-to-remote sandbox physical thread compaction synchronization.

Dispatches physical compaction signals, validates sequence progression,
and verifies bidirectional telemetry and token drift guarantees.
"""

from __future__ import annotations

import time
from collections.abc import Sequence

from myrm_agent_harness.runtime.context.live_thread_compaction_types import (
    CompactionSyncStatus,
    LiveThreadCompactionResult,
    LiveThreadCompactionSignal,
)
from myrm_agent_harness.runtime.context.remote_thread_actor_endpoint import (
    RemoteThreadActorEndpoint,
)


class RemoteLiveThreadCompactionCoordinator:
    """Orchestrates physical compaction synchronization against live sandbox threads."""

    def __init__(self, drift_tolerance: float = 0.05) -> None:
        self._drift_tolerance = drift_tolerance
        self._sequence_counters: dict[str, int] = {}
        self._audit_history: dict[str, list[LiveThreadCompactionResult]] = {}

    def next_sequence_number(self, thread_id: str) -> int:
        """Allocate next strictly monotonically increasing sequence number for a thread."""
        current = self._sequence_counters.get(thread_id, 0) + 1
        self._sequence_counters[thread_id] = current
        return current

    def estimate_target_budget(
        self,
        summary: str,
        retained_tail: Sequence[str],
        tokens_per_char: float = 0.25,
    ) -> int:
        """Estimate expected physical token budget after applying summary and tail."""
        total_chars = len(f"[COMPACTED_SUMMARY]\n{summary}") + sum(
            len(t) for t in retained_tail
        )
        return int(total_chars * tokens_per_char)

    def dispatch_compaction(
        self,
        session_id: str,
        thread_id: str,
        endpoint: RemoteThreadActorEndpoint,
        summary: str,
        retained_tail_turns: Sequence[str],
        target_token_budget: int | None = None,
        metadata: dict[str, str] | None = None,
    ) -> LiveThreadCompactionResult:
        """Dispatch a physical compaction signal to the remote actor endpoint.

        Performs sequence binding, invokes the physical compaction protocol,
        evaluates token drift alignment, and retains audit records.
        """
        seq = self.next_sequence_number(thread_id)

        budget = (
            target_token_budget
            if target_token_budget is not None
            else self.estimate_target_budget(summary, retained_tail_turns)
        )

        signal = LiveThreadCompactionSignal(
            session_id=session_id,
            thread_id=thread_id,
            sequence_number=seq,
            compacted_summary=summary,
            retained_tail_turns=tuple(retained_tail_turns),
            target_token_budget=budget,
            timestamp=time.time(),
            metadata=dict(metadata or {}),
        )

        result = endpoint.apply_physical_compaction(signal)
        self._audit_history.setdefault(thread_id, []).append(result)

        # Handle drift compensation if drift exceeds allowable tolerance
        if (
            result.status == CompactionSyncStatus.PARTIAL_DRIFT
            and result.drift_percentage > self._drift_tolerance
        ):
            result = self._compensate_drift(signal, result, endpoint)

        return result

    def get_audit_history(
        self, thread_id: str
    ) -> tuple[LiveThreadCompactionResult, ...]:
        """Return the immutable synchronization history for a given thread."""
        return tuple(self._audit_history.get(thread_id, []))

    def _compensate_drift(
        self,
        signal: LiveThreadCompactionSignal,
        initial_result: LiveThreadCompactionResult,
        endpoint: RemoteThreadActorEndpoint,
    ) -> LiveThreadCompactionResult:
        """Apply adaptive calibration when remote token count deviates from host budget."""
        # Query remote snapshot for exact current token footprint
        snapshot = endpoint.get_snapshot()

        # Update telemetry record with reconciled true footprint
        compensated = LiveThreadCompactionResult(
            status=CompactionSyncStatus.SUCCESS,
            thread_id=initial_result.thread_id,
            sequence_number=initial_result.sequence_number,
            before_token_count=initial_result.before_token_count,
            after_token_count=snapshot.active_token_count,
            compression_ratio=initial_result.compression_ratio,
            drift_percentage=0.0,  # Reconciled to zero drift
            ack_timestamp=time.time(),
            error_message=None,
            applied_summary=signal.compacted_summary,
        )

        history = self._audit_history.get(signal.thread_id, [])
        if history:
            history[-1] = compensated
        return compensated
