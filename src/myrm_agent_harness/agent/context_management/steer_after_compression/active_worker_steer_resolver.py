# [INPUT]: steer_compression_types.py
# [OUTPUT]: ActiveWorkerSteerResolver
# [POS]: agent/context_management/steer_after_compression/active_worker_steer_resolver.py

"""Core resolution and dispatch engine for steering active workers after context compaction.

[INPUT]
- agent.context_management.steer_after_compression.steer_compression_types::ActiveWorkerDescriptor,
  SteerDispatchResult, SteerMessageKind, SteerResolutionStatus, WorkerLifecycleState
  (POS: Strongly typed domain models and lifecycle contracts.)

[OUTPUT]
- ActiveWorkerSteerResolver: Coordinates direct and alias-based worker resolution, preflight stops,
  and idempotent settle boundaries across compaction rotations.

[POS]
Post-compaction worker routing and lifecycle settle coordinator.
"""

from __future__ import annotations

import time

from .steer_compression_types import (
    ActiveWorkerDescriptor,
    SteerDispatchResult,
    SteerMessageKind,
    SteerResolutionStatus,
    WorkerLifecycleState,
)


class ActiveWorkerSteerResolver:
    """Resolves and delivers steer directives to active workers across session compaction."""

    def __init__(self) -> None:
        self._workers: dict[str, ActiveWorkerDescriptor] = {}
        # session_id -> list of worker_ids
        self._session_to_workers: dict[str, list[str]] = {}
        # prior_session_id -> target_session_id (for compaction session rotation)
        self._compaction_aliases: dict[str, str] = {}

    def register_worker(
        self,
        worker_id: str,
        session_id: str,
        active_run_id: str = "",
        metadata: dict[str, str] | None = None,
    ) -> ActiveWorkerDescriptor:
        """Register an active execution worker bound to a session.

        Args:
            worker_id: Unique worker identifier.
            session_id: Bound session identifier.
            active_run_id: Current run execution id.
            metadata: Optional metadata attributes.

        Returns:
            The created ActiveWorkerDescriptor in RUNNING state.

        Raises:
            ValueError: If worker_id is already registered.
        """
        if worker_id in self._workers:
            msg = f"Worker '{worker_id}' is already registered."
            raise ValueError(msg)

        descriptor = ActiveWorkerDescriptor(
            worker_id=worker_id,
            session_id=session_id,
            state=WorkerLifecycleState.RUNNING,
            active_run_id=active_run_id,
            registered_at_utc=time.time(),
            metadata=dict(metadata or {}),
        )
        self._workers[worker_id] = descriptor
        if session_id not in self._session_to_workers:
            self._session_to_workers[session_id] = []
        self._session_to_workers[session_id].append(worker_id)
        return descriptor

    def record_compaction_alias(self, prior_session_id: str, new_session_id: str) -> None:
        """Record a session identifier rotation caused by context compaction.

        Args:
            prior_session_id: The session ID prior to compaction.
            new_session_id: The session ID after compaction rotation.
        """
        self._compaction_aliases[prior_session_id] = new_session_id

    def resolve_active_worker(
        self, session_id: str
    ) -> tuple[ActiveWorkerDescriptor | None, SteerResolutionStatus]:
        """Resolve the active running worker for a session, checking aliases if needed.

        Args:
            session_id: The session ID to resolve.

        Returns:
            Tuple of (descriptor or None, resolution_status).
        """
        # 1. Direct match
        direct_worker = self._find_active_in_session(session_id)
        if direct_worker is not None:
            return direct_worker, SteerResolutionStatus.RESOLVED_DIRECT

        # 2. Check compaction aliases
        visited: set[str] = {session_id}
        current_sid = session_id
        while current_sid in self._compaction_aliases:
            target_sid = self._compaction_aliases[current_sid]
            if target_sid in visited:
                break
            visited.add(target_sid)
            alias_worker = self._find_active_in_session(target_sid)
            if alias_worker is not None:
                return alias_worker, SteerResolutionStatus.RESOLVED_COMPACTED_ALIAS
            current_sid = target_sid

        return None, SteerResolutionStatus.WORKER_NOT_FOUND

    def _find_active_in_session(self, session_id: str) -> ActiveWorkerDescriptor | None:
        """Find an un-settled worker in a session."""
        worker_ids = self._session_to_workers.get(session_id, [])
        for wid in reversed(worker_ids):
            worker = self._workers.get(wid)
            if worker and worker.state in (
                WorkerLifecycleState.RUNNING,
                WorkerLifecycleState.FINALIZING,
            ):
                return worker
        return None

    def dispatch_steer(
        self,
        session_id: str,
        message: str,
        kind: SteerMessageKind = SteerMessageKind.OUT_OF_BAND_STEER,
    ) -> SteerDispatchResult:
        """Deliver a steer instruction or emergency stop to an active worker.

        Args:
            session_id: Session identifier (can be pre-compaction or post-compaction).
            message: Steer content or stop directive.
            kind: Category of the steering message.

        Returns:
            SteerDispatchResult audit receipt.
        """
        now = time.time()
        worker, res_status = self.resolve_active_worker(session_id)

        if worker is None:
            # Check if there was a worker that already settled
            worker_ids = self._session_to_workers.get(session_id, [])
            if worker_ids:
                last_worker = self._workers.get(worker_ids[-1])
                if last_worker and last_worker.state in (
                    WorkerLifecycleState.SETTLED,
                    WorkerLifecycleState.STOPPED,
                ):
                    return SteerDispatchResult(
                        status=SteerResolutionStatus.WORKER_ALREADY_SETTLED,
                        worker_id=last_worker.worker_id,
                        session_id=session_id,
                        message=message,
                        kind=kind,
                        timestamp_utc=now,
                        delivered=False,
                    )

            return SteerDispatchResult(
                status=SteerResolutionStatus.WORKER_NOT_FOUND,
                worker_id=None,
                session_id=session_id,
                message=message,
                kind=kind,
                timestamp_utc=now,
                delivered=False,
            )

        # Handle emergency STOP
        if kind == SteerMessageKind.OUT_OF_BAND_STOP:
            worker.state = WorkerLifecycleState.STOPPED
            worker.settled_at_utc = now
            worker.steer_inbox.append(f"[STOP]: {message}")
            return SteerDispatchResult(
                status=SteerResolutionStatus.STOPPED_IN_PREFLIGHT,
                worker_id=worker.worker_id,
                session_id=session_id,
                message=message,
                kind=kind,
                timestamp_utc=now,
                delivered=True,
            )

        # Normal steer delivery
        worker.steer_inbox.append(message)
        return SteerDispatchResult(
            status=res_status,
            worker_id=worker.worker_id,
            session_id=session_id,
            message=message,
            kind=kind,
            timestamp_utc=now,
            delivered=True,
        )

    def settle_worker(
        self,
        worker_id: str,
        final_state: WorkerLifecycleState = WorkerLifecycleState.SETTLED,
    ) -> ActiveWorkerDescriptor:
        """Idempotent settle boundary for worker terminal exits.

        Args:
            worker_id: Unique worker identifier.
            final_state: Terminal exit state (SETTLED or STOPPED).

        Returns:
            Settled ActiveWorkerDescriptor.

        Raises:
            KeyError: If worker_id is not registered.
        """
        if worker_id not in self._workers:
            msg = f"Worker '{worker_id}' is not registered."
            raise KeyError(msg)

        worker = self._workers[worker_id]
        if worker.state in (WorkerLifecycleState.SETTLED, WorkerLifecycleState.STOPPED):
            # Already settled idempotently
            return worker

        worker.state = final_state
        worker.settled_at_utc = time.time()
        return worker

    def get_worker(self, worker_id: str) -> ActiveWorkerDescriptor:
        """Retrieve a worker by identifier."""
        if worker_id not in self._workers:
            msg = f"Worker '{worker_id}' is not registered."
            raise KeyError(msg)
        return self._workers[worker_id]
