"""Supervision coordinator managing live rosters, transcript buffers, and worker actions.

[INPUT]
- types.SubagentWorkerStatus, SubagentWorkerRosterItem, SubagentRosterOverview
- types.SupervisionActionResult, SupervisionActionType
- transcript_buffer.SubagentTranscriptBuffer

[OUTPUT]
- SubagentSupervisionCoordinator

[POS]
myrm_agent_harness/agent/sub_agents/supervision_hub/coordinator.py
"""

from __future__ import annotations

import logging
import threading
from typing import ClassVar

from myrm_agent_harness.agent.sub_agents.supervision_hub.transcript_buffer import (
    SubagentTranscriptBuffer,
)
from myrm_agent_harness.agent.sub_agents.supervision_hub.types import (
    SubagentRosterOverview,
    SubagentWorkerRosterItem,
    SubagentWorkerStatus,
    SupervisionActionResult,
    SupervisionActionType,
)

logger = logging.getLogger(__name__)


class SubagentSupervisionCoordinator:
    """Coordinator maintaining subagent live transcripts, roster overview, and control actions."""

    _instance: ClassVar[SubagentSupervisionCoordinator | None] = None
    _singleton_lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self) -> None:
        self._buffers: dict[str, SubagentTranscriptBuffer] = {}
        self._workers: dict[str, SubagentWorkerRosterItem] = {}
        self._session_workers: dict[str, set[str]] = {}  # session_id -> {task_id, ...}
        self._lock: threading.Lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> SubagentSupervisionCoordinator:
        """Get or initialize process-wide singleton coordinator."""
        if cls._instance is None:
            with cls._singleton_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def register_worker(
        self,
        session_id: str,
        task_id: str,
        agent_type: str,
        description: str = "",
        model: str = "default",
    ) -> SubagentWorkerRosterItem:
        """Register a new active subagent worker in the supervision roster."""
        with self._lock:
            item = SubagentWorkerRosterItem(
                task_id=task_id,
                agent_type=agent_type,
                status="running",
                current_activity="Initializing...",
                model=model,
                tokens_used=0,
                elapsed_seconds=0.0,
                last_tool="",
                can_steer=True,
                can_kill=True,
                can_revive=False,
                description=description,
            )
            self._workers[task_id] = item
            if session_id not in self._session_workers:
                self._session_workers[session_id] = set()
            self._session_workers[session_id].add(task_id)

            if task_id not in self._buffers:
                self._buffers[task_id] = SubagentTranscriptBuffer(task_id)

            return item

    def update_worker_activity(
        self,
        task_id: str,
        current_activity: str,
        last_tool: str = "",
        tokens_delta: int = 0,
        elapsed_seconds: float | None = None,
        status: SubagentWorkerStatus | None = None,
    ) -> None:
        """Update live execution state and resource consumption of a worker."""
        with self._lock:
            worker = self._workers.get(task_id)
            if not worker:
                return

            worker.current_activity = current_activity
            if last_tool:
                worker.last_tool = last_tool
            if tokens_delta > 0:
                worker.tokens_used += tokens_delta
            if elapsed_seconds is not None:
                worker.elapsed_seconds = elapsed_seconds
            if status is not None:
                worker.status = status
                worker.can_steer = status in ("running", "stuck")
                worker.can_kill = status in ("running", "stuck")
                worker.can_revive = status in ("parked", "interrupted", "failed")

    def append_transcript(
        self,
        task_id: str,
        tool_name: str,
        input_summary: str,
        output_summary: str,
        level: str = "info",
        duration_ms: int | None = None,
    ) -> None:
        """Record a live transcript entry for a worker."""
        with self._lock:
            buf = self._buffers.get(task_id)
            if not buf:
                buf = SubagentTranscriptBuffer(task_id)
                self._buffers[task_id] = buf

        log_level = "error" if level == "error" else "warn" if level == "warn" else "info"
        buf.append_entry(
            tool_name=tool_name,
            input_summary=input_summary,
            output_summary=output_summary,
            level=log_level,
            duration_ms=duration_ms,
        )

    def get_transcript_entries(
        self, task_id: str, limit: int | None = None
    ) -> list[dict[str, str | int | None]]:
        """Retrieve recorded transcript entries for a worker as dictionary list."""
        with self._lock:
            buf = self._buffers.get(task_id)
            if not buf:
                return []
            entries = buf.get_entries(limit=limit)

        return [
            {
                "entry_id": e.entry_id,
                "timestamp": e.timestamp,
                "tool_name": e.tool_name,
                "input_summary": e.input_summary,
                "output_summary": e.output_summary,
                "level": e.level,
                "duration_ms": e.duration_ms,
            }
            for e in entries
        ]

    def get_roster_overview(self, session_id: str) -> SubagentRosterOverview:
        """Compute aggregated roster overview for a session."""
        with self._lock:
            task_ids = self._session_workers.get(session_id, set())
            worker_items = [self._workers[tid] for tid in task_ids if tid in self._workers]

            total_workers = len(worker_items)
            active_workers = sum(1 for w in worker_items if w.status == "running")
            parked_workers = sum(1 for w in worker_items if w.status == "parked")
            stuck_workers = sum(1 for w in worker_items if w.status == "stuck")
            total_tokens = sum(w.tokens_used for w in worker_items)
            total_duration = max((w.elapsed_seconds for w in worker_items), default=0.0)

            return SubagentRosterOverview(
                session_id=session_id,
                total_workers=total_workers,
                active_workers=active_workers,
                parked_workers=parked_workers,
                stuck_workers=stuck_workers,
                total_tokens=total_tokens,
                total_duration_seconds=round(total_duration, 2),
                workers=worker_items,
            )

    def execute_action(
        self,
        task_id: str,
        action: SupervisionActionType,
        steering_message: str = "",
    ) -> SupervisionActionResult:
        """Execute supervision action (steer, kill, revive) on a worker."""
        with self._lock:
            worker = self._workers.get(task_id)
            if not worker:
                return SupervisionActionResult(
                    task_id=task_id,
                    action=action,
                    success=False,
                    message=f"Worker {task_id} not found in supervision registry",
                    new_status="failed",
                )

            if action == "steer":
                if not steering_message.strip():
                    return SupervisionActionResult(
                        task_id=task_id,
                        action=action,
                        success=False,
                        message="Steering message cannot be empty",
                        new_status=worker.status,
                    )
                worker.current_activity = f"Steering received: {steering_message[:50]}..."
                worker.status = "running"
                worker.can_revive = False
                self._append_system_entry(task_id, "steer_injected", steering_message)
                return SupervisionActionResult(
                    task_id=task_id,
                    action=action,
                    success=True,
                    message=f"Steering directive successfully dispatched to worker {task_id}",
                    new_status="running",
                )

            if action == "kill":
                worker.status = "failed"
                worker.current_activity = "Terminated by operator supervision"
                worker.can_steer = False
                worker.can_kill = False
                worker.can_revive = True
                self._append_system_entry(
                    task_id, "kill_operator", "Worker stopped manually by supervision action"
                )
                return SupervisionActionResult(
                    task_id=task_id,
                    action=action,
                    success=True,
                    message=f"Worker {task_id} terminated without interrupting parent session",
                    new_status="failed",
                )

            if action == "revive":
                if worker.status not in ("parked", "interrupted", "failed"):
                    return SupervisionActionResult(
                        task_id=task_id,
                        action=action,
                        success=False,
                        message=f"Worker {task_id} in {worker.status} state cannot be revived",
                        new_status=worker.status,
                    )
                worker.status = "running"
                worker.current_activity = "Revived and resumed execution from checkpoint"
                worker.can_steer = True
                worker.can_kill = True
                worker.can_revive = False
                self._append_system_entry(
                    task_id, "revive_resumed", "Worker revived successfully"
                )
                return SupervisionActionResult(
                    task_id=task_id,
                    action=action,
                    success=True,
                    message=f"Worker {task_id} resumed from checkpoint into running pool",
                    new_status="running",
                )

            return SupervisionActionResult(
                task_id=task_id,
                action=action,
                success=False,
                message=f"Unknown supervision action: {action}",
                new_status=worker.status,
            )

    def _append_system_entry(self, task_id: str, tool: str, text: str) -> None:
        buf = self._buffers.get(task_id)
        if buf:
            buf.append_entry(
                tool_name=tool,
                input_summary=text,
                output_summary="Acknowledged",
                level="info",
            )
