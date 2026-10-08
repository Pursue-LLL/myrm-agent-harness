"""Execution continuation audit and runner heartbeat reconciliation engine.

[INPUT]
- Heartbeat signals, run registrations, continuation requests.

[OUTPUT]
- ContinuationAuditVerdict validating task continuity and preventing split-brain/stale runs.

[POS]
- Harness core security module coordinating sandbox execution continuation and heartbeat audits.
"""

from __future__ import annotations

import time

from myrm_agent_harness.core.security.sandbox_log_continuation.types import (
    ContinuationAuditVerdict,
    ContinuationStatus,
    HeartbeatSignal,
    RunRecord,
)


class ExecutionContinuationAuditEngine:
    """Audits and reconciles execution continuations against heartbeat signals and task state."""

    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._task_runs: dict[str, list[str]] = {}

    def register_run(
        self,
        run_id: str,
        task_id: str,
        assignee_agent_id: str,
        is_terminal: bool = False,
        started_at: float | None = None,
    ) -> RunRecord:
        """Register a new run attached to a task."""
        now = started_at if started_at is not None else time.time()
        record = RunRecord(
            run_id=run_id,
            task_id=task_id,
            assignee_agent_id=assignee_agent_id,
            is_terminal=is_terminal,
            started_at=now,
            last_heartbeat_timestamp=now,
            last_heartbeat_seq=0,
        )
        self._runs[run_id] = record
        if task_id not in self._task_runs:
            self._task_runs[task_id] = []
        if run_id not in self._task_runs[task_id]:
            self._task_runs[task_id].append(run_id)
        return record

    def record_heartbeat(self, signal: HeartbeatSignal) -> bool:
        """Record an incoming runner heartbeat signal for an active execution."""
        record = self._runs.get(signal.run_id)
        if record is None:
            return False

        updated_record = RunRecord(
            run_id=record.run_id,
            task_id=record.task_id,
            assignee_agent_id=record.assignee_agent_id,
            is_terminal=(
                record.is_terminal
                or signal.status in ("completed", "failed", "terminating")
            ),
            started_at=record.started_at,
            last_heartbeat_timestamp=signal.timestamp,
            last_heartbeat_seq=signal.seq,
        )
        self._runs[signal.run_id] = updated_record
        return True

    def mark_run_terminal(self, run_id: str) -> bool:
        """Mark a run as terminally ended (e.g. cancelled or failed)."""
        record = self._runs.get(run_id)
        if record is None:
            return False
        self._runs[run_id] = RunRecord(
            run_id=record.run_id,
            task_id=record.task_id,
            assignee_agent_id=record.assignee_agent_id,
            is_terminal=True,
            started_at=record.started_at,
            last_heartbeat_timestamp=record.last_heartbeat_timestamp,
            last_heartbeat_seq=record.last_heartbeat_seq,
        )
        return True

    def get_run(self, run_id: str) -> RunRecord | None:
        """Retrieve run registration record."""
        return self._runs.get(run_id)

    def audit_continuation(
        self,
        task_id: str,
        requesting_agent_id: str,
        proposed_run_id: str,
        resume_source_run_id: str | None = None,
        current_time: float | None = None,
        max_heartbeat_gap_seconds: float = 60.0,
    ) -> ContinuationAuditVerdict:
        """Audit whether proposed continuation is permitted and authoritative."""
        now = current_time if current_time is not None else time.time()

        # If resuming from a prior run, verify source run exists and matches task
        if resume_source_run_id is not None:
            source_run = self._runs.get(resume_source_run_id)
            if source_run is None or source_run.task_id != task_id:
                return ContinuationAuditVerdict(
                    is_resumable=False,
                    status=ContinuationStatus.MISSING_ORIGIN_RUN,
                    task_id=task_id,
                    proposed_run_id=proposed_run_id,
                    resume_source_run_id=resume_source_run_id,
                    reconciliation_reason="Resume source run does not exist or does not belong to specified task.",
                    last_heartbeat_age_sec=None,
                )

            # Check agent ownership
            if source_run.assignee_agent_id != requesting_agent_id:
                return ContinuationAuditVerdict(
                    is_resumable=False,
                    status=ContinuationStatus.OWNERSHIP_MISMATCH,
                    task_id=task_id,
                    proposed_run_id=proposed_run_id,
                    resume_source_run_id=resume_source_run_id,
                    reconciliation_reason=(
                        f"Task ownership changed: owned by {source_run.assignee_agent_id}, "
                        f"requested by {requesting_agent_id}."
                    ),
                    last_heartbeat_age_sec=None,
                )

            # Check if source run was permanently terminated
            if source_run.is_terminal:
                return ContinuationAuditVerdict(
                    is_resumable=False,
                    status=ContinuationStatus.TASK_TERMINATED,
                    task_id=task_id,
                    proposed_run_id=proposed_run_id,
                    resume_source_run_id=resume_source_run_id,
                    reconciliation_reason="Source run is marked terminal; continuation cannot resume terminated state.",
                    last_heartbeat_age_sec=None,
                )

            # Check heartbeat freshness if source was running
            last_hb = source_run.last_heartbeat_timestamp or source_run.started_at
            heartbeat_age = max(0.0, now - last_hb)
            if heartbeat_age > max_heartbeat_gap_seconds:
                return ContinuationAuditVerdict(
                    is_resumable=False,
                    status=ContinuationStatus.STALE_HEARTBEAT,
                    task_id=task_id,
                    proposed_run_id=proposed_run_id,
                    resume_source_run_id=resume_source_run_id,
                    reconciliation_reason=(
                        f"Source run heartbeat is stale ({heartbeat_age:.1f}s > {max_heartbeat_gap_seconds:.1f}s limit)."
                    ),
                    last_heartbeat_age_sec=heartbeat_age,
                )

            return ContinuationAuditVerdict(
                is_resumable=True,
                status=ContinuationStatus.VALID,
                task_id=task_id,
                proposed_run_id=proposed_run_id,
                resume_source_run_id=resume_source_run_id,
                reconciliation_reason="Continuation approved with valid source run lineage and active heartbeat.",
                last_heartbeat_age_sec=heartbeat_age,
            )

        # New root run for the task
        return ContinuationAuditVerdict(
            is_resumable=True,
            status=ContinuationStatus.VALID,
            task_id=task_id,
            proposed_run_id=proposed_run_id,
            resume_source_run_id=None,
            reconciliation_reason="New execution run permitted for task.",
            last_heartbeat_age_sec=None,
        )
