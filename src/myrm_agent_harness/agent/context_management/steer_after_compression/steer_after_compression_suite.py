# [INPUT]: active_worker_steer_resolver.py, oob_message_sanitizer.py, steer_compression_types.py
# [OUTPUT]: HermesWebuiSteerAfterCompressionSuite
# [POS]: agent/context_management/steer_after_compression/steer_after_compression_suite.py

"""Unified orchestration facade for post-compaction steering and out-of-band context sanitization.

[INPUT]
- agent.context_management.steer_after_compression.active_worker_steer_resolver::ActiveWorkerSteerResolver
  (POS: Resolver routing steer commands to active workers across session compaction rotations.)
- agent.context_management.steer_after_compression.oob_message_sanitizer::OOBMessageSanitizer
  (POS: Sanitizer stripping out-of-band management messages during replay context assembly.)
- agent.context_management.steer_after_compression.steer_compression_types::ActiveWorkerDescriptor,
  ContextTurnMessage, SanitizedReplayResult, SteerDispatchResult, SteerMessageKind,
  WorkerLifecycleState (POS: Strongly typed domain models and audit receipts.)

[OUTPUT]
- HermesWebuiSteerAfterCompressionSuite: Main facade combining resilient worker steering
  and OOB replay hygiene for long-running compressed sessions.

[POS]
Integration suite coordinating post-compaction worker steering and OOB context hygiene.
"""

from __future__ import annotations

from .active_worker_steer_resolver import ActiveWorkerSteerResolver
from .oob_message_sanitizer import OOBMessageSanitizer
from .steer_compression_types import (
    ActiveWorkerDescriptor,
    ContextTurnMessage,
    SanitizedReplayResult,
    SteerDispatchResult,
    SteerMessageKind,
    WorkerLifecycleState,
)


class HermesWebuiSteerAfterCompressionSuite:
    """End-to-end orchestration suite for post-compaction worker steering and OOB sanitization."""

    def __init__(
        self,
        resolver: ActiveWorkerSteerResolver | None = None,
        sanitizer: OOBMessageSanitizer | None = None,
    ) -> None:
        self._resolver = resolver or ActiveWorkerSteerResolver()
        self._sanitizer = sanitizer or OOBMessageSanitizer()

    @property
    def resolver(self) -> ActiveWorkerSteerResolver:
        """Access underlying active worker steer resolver."""
        return self._resolver

    @property
    def sanitizer(self) -> OOBMessageSanitizer:
        """Access underlying out-of-band message sanitizer."""
        return self._sanitizer

    def register_active_worker(
        self,
        worker_id: str,
        session_id: str,
        active_run_id: str = "",
        metadata: dict[str, str] | None = None,
    ) -> ActiveWorkerDescriptor:
        """Register an active worker bound to a session."""
        return self._resolver.register_worker(
            worker_id=worker_id,
            session_id=session_id,
            active_run_id=active_run_id,
            metadata=metadata,
        )

    def notify_compaction_rotation(
        self,
        prior_session_id: str,
        new_session_id: str,
    ) -> None:
        """Notify that context compaction occurred, binding session alias rotation."""
        self._resolver.record_compaction_alias(
            prior_session_id=prior_session_id,
            new_session_id=new_session_id,
        )

    def steer_worker(
        self,
        session_id: str,
        message: str,
        kind: SteerMessageKind = SteerMessageKind.OUT_OF_BAND_STEER,
    ) -> SteerDispatchResult:
        """Deliver a steer directive to the active worker, resolving compaction aliases."""
        return self._resolver.dispatch_steer(
            session_id=session_id,
            message=message,
            kind=kind,
        )

    def emergency_stop(
        self,
        session_id: str,
        reason: str = "User requested immediate stop",
    ) -> SteerDispatchResult:
        """Deliver an emergency stop directive, cancelling active worker in preflight."""
        # 1. Dispatch stop to active worker
        res = self._resolver.dispatch_steer(
            session_id=session_id,
            message=reason,
            kind=SteerMessageKind.OUT_OF_BAND_STOP,
        )
        # 2. Persist stop event durably as OOB turn for audit trail
        self._sanitizer.append_message(
            session_id=session_id,
            message_id=f"stop_{int(res.timestamp_utc * 1000)}",
            role="user",
            content=f"[STOP]: {reason}",
            is_oob=True,
            kind=SteerMessageKind.OUT_OF_BAND_STOP,
        )
        return res

    def settle_worker(
        self,
        worker_id: str,
        final_state: WorkerLifecycleState = WorkerLifecycleState.SETTLED,
    ) -> ActiveWorkerDescriptor:
        """Idempotent settle boundary for worker terminal exits."""
        return self._resolver.settle_worker(
            worker_id=worker_id,
            final_state=final_state,
        )

    def record_turn(
        self,
        session_id: str,
        message_id: str,
        role: str,
        content: str,
        is_oob: bool = False,
        kind: SteerMessageKind = SteerMessageKind.IN_BAND_PROMPT,
        metadata: dict[str, str] | None = None,
    ) -> ContextTurnMessage:
        """Persist a conversation or control turn durably."""
        return self._sanitizer.append_message(
            session_id=session_id,
            message_id=message_id,
            role=role,
            content=content,
            is_oob=is_oob,
            kind=kind,
            metadata=metadata,
        )

    def assemble_clean_replay(self, session_id: str) -> SanitizedReplayResult:
        """Assemble clean model prompt replay context with OOB controls stripped."""
        return self._sanitizer.sanitize_for_replay(session_id=session_id)

    def get_worker(self, worker_id: str) -> ActiveWorkerDescriptor:
        """Retrieve worker descriptor by identifier."""
        return self._resolver.get_worker(worker_id=worker_id)
