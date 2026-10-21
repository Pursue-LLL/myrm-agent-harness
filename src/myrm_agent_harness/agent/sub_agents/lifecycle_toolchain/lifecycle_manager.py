"""myrm_agent_harness/agent/sub_agents/lifecycle_toolchain/lifecycle_manager.py

[INPUT]
- threading
- time
- uuid
- datetime
- types

[OUTPUT]
- SubagentLifecycleManager

[POS]
myrm_agent_harness/agent/sub_agents/lifecycle_toolchain/lifecycle_manager.py
"""

import threading
import time
import uuid
from datetime import UTC, datetime

from .types import (
    SubagentEventItem,
    SubagentInputMessage,
    SubagentLifecycleError,
    SubagentNotFoundError,
    SubagentSpawnRequest,
    SubagentStatusEnum,
    SubagentTaskRecord,
    SubagentWaitResult,
)


class SubagentLifecycleManager:
    """Thread-safe native lifecycle manager for subagents."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tasks: dict[str, SubagentTaskRecord] = {}

    def spawn(self, request: SubagentSpawnRequest) -> SubagentTaskRecord:
        """Spawn a new subagent task in isolated execution space."""
        if not request.task_prompt.strip():
            raise SubagentLifecycleError("Task prompt cannot be empty.")
        if not request.parent_session_id.strip():
            raise SubagentLifecycleError("Parent session ID cannot be empty.")

        now_iso = datetime.now(UTC).isoformat()
        record = SubagentTaskRecord(
            subagent_id=request.subagent_id,
            parent_session_id=request.parent_session_id,
            task_prompt=request.task_prompt,
            agent_profile=request.agent_profile,
            tools_whitelist=list(request.tools_whitelist),
            status=SubagentStatusEnum.RUNNING,
            timeout_seconds=request.timeout_seconds,
            created_at=now_iso,
            started_at=now_iso,
        )

        event = SubagentEventItem(
            event_id=f"evt-{uuid.uuid4().hex[:8]}",
            event_type="SUBAGENT_SPAWNED",
            subagent_id=record.subagent_id,
            payload={
                "parent_session_id": request.parent_session_id,
                "agent_profile": request.agent_profile,
                "timeout_seconds": request.timeout_seconds,
            },
        )
        record.events.append(event)

        with self._lock:
            self._tasks[record.subagent_id] = record
            return record

    def get_subagent(self, subagent_id: str) -> SubagentTaskRecord:
        """Retrieve subagent record or raise SubagentNotFoundError."""
        with self._lock:
            self.check_timeouts()
            record = self._tasks.get(subagent_id)
            if not record:
                raise SubagentNotFoundError(
                    f"Subagent {subagent_id} not found."
                )
            return record

    def list_subagents(
        self,
        parent_session_id: str | None = None,
        status_filter: SubagentStatusEnum | None = None,
        limit: int = 50,
    ) -> list[SubagentTaskRecord]:
        """List subagents with optional parent session and status filtering."""
        with self._lock:
            self.check_timeouts()
            records = list(self._tasks.values())

            if parent_session_id:
                records = [
                    r for r in records if r.parent_session_id == parent_session_id
                ]

            if status_filter:
                records = [r for r in records if r.status == status_filter]

            records.sort(key=lambda r: r.created_at, reverse=True)
            return records[:limit]

    def send_input(
        self,
        subagent_id: str,
        content: str,
        sender_role: str = "orchestrator",
    ) -> SubagentInputMessage:
        """Inject supplementary message or guidance into active subagent queue."""
        if not content.strip():
            raise SubagentLifecycleError("Input content cannot be empty.")

        with self._lock:
            record = self.get_subagent(subagent_id)
            if record.is_terminal():
                raise SubagentLifecycleError(
                    f"Cannot inject input to terminal subagent {subagent_id} (status: {record.status.value})."
                )

            msg = SubagentInputMessage(
                message_id=f"msg-{uuid.uuid4().hex[:8]}",
                subagent_id=subagent_id,
                content=content,
                sender_role=sender_role,
            )
            record.input_queue.append(msg)

            event = SubagentEventItem(
                event_id=f"evt-{uuid.uuid4().hex[:8]}",
                event_type="INPUT_INJECTED",
                subagent_id=subagent_id,
                payload={
                    "message_id": msg.message_id,
                    "sender_role": sender_role,
                },
            )
            record.events.append(event)
            return msg

    def kill(
        self,
        subagent_id: str,
        reason: str = "manual_kill",
    ) -> SubagentTaskRecord:
        """Terminate a running subagent immediately."""
        with self._lock:
            record = self.get_subagent(subagent_id)
            if record.is_terminal():
                return record

            now_iso = datetime.now(UTC).isoformat()
            record.status = SubagentStatusEnum.KILLED
            record.ended_at = now_iso
            record.kill_reason = reason

            event = SubagentEventItem(
                event_id=f"evt-{uuid.uuid4().hex[:8]}",
                event_type="SUBAGENT_KILLED",
                subagent_id=subagent_id,
                payload={"reason": reason},
            )
            record.events.append(event)
            return record

    def complete(
        self,
        subagent_id: str,
        result_summary: str,
        token_usage: int = 0,
        step_count: int = 0,
    ) -> SubagentTaskRecord:
        """Mark a subagent as successfully completed."""
        with self._lock:
            record = self.get_subagent(subagent_id)
            if record.is_terminal():
                return record

            now_iso = datetime.now(UTC).isoformat()
            record.status = SubagentStatusEnum.COMPLETED
            record.ended_at = now_iso
            record.result_summary = result_summary
            record.token_usage = token_usage
            record.step_count = step_count

            event = SubagentEventItem(
                event_id=f"evt-{uuid.uuid4().hex[:8]}",
                event_type="SUBAGENT_COMPLETED",
                subagent_id=subagent_id,
                payload={
                    "token_usage": token_usage,
                    "step_count": step_count,
                },
            )
            record.events.append(event)
            return record

    def fail(
        self,
        subagent_id: str,
        error_detail: str,
    ) -> SubagentTaskRecord:
        """Mark a subagent as failed."""
        with self._lock:
            record = self.get_subagent(subagent_id)
            if record.is_terminal():
                return record

            now_iso = datetime.now(UTC).isoformat()
            record.status = SubagentStatusEnum.FAILED
            record.ended_at = now_iso
            record.error_detail = error_detail

            event = SubagentEventItem(
                event_id=f"evt-{uuid.uuid4().hex[:8]}",
                event_type="SUBAGENT_FAILED",
                subagent_id=subagent_id,
                payload={"error_detail": error_detail[:200]},
            )
            record.events.append(event)
            return record

    def check_timeouts(self) -> list[str]:
        """Scan running subagents and mark expired ones as TIMEOUT."""
        timed_out_ids: list[str] = []
        now = datetime.now(UTC)

        with self._lock:
            for sub_id, record in self._tasks.items():
                if record.status == SubagentStatusEnum.RUNNING and record.started_at:
                    try:
                        started_dt = datetime.fromisoformat(record.started_at)
                        elapsed = (now - started_dt).total_seconds()
                        if elapsed > record.timeout_seconds:
                            record.status = SubagentStatusEnum.TIMEOUT
                            record.ended_at = now.isoformat()
                            record.error_detail = f"Execution timed out after {elapsed:.1f}s (budget: {record.timeout_seconds}s)"
                            event = SubagentEventItem(
                                event_id=f"evt-{uuid.uuid4().hex[:8]}",
                                event_type="SUBAGENT_TIMEOUT",
                                subagent_id=sub_id,
                                payload={"elapsed_seconds": elapsed},
                            )
                            record.events.append(event)
                            timed_out_ids.append(sub_id)
                    except ValueError:
                        pass
        return timed_out_ids

    def wait(
        self,
        subagent_ids: list[str],
        timeout_seconds: float = 30.0,
        poll_interval: float = 0.05,
    ) -> SubagentWaitResult:
        """Wait for specified subagents to finish or until timeout expires."""
        deadline = time.time() + timeout_seconds

        while time.time() < deadline:
            with self._lock:
                self.check_timeouts()
                records = [
                    self._tasks[sid]
                    for sid in subagent_ids
                    if sid in self._tasks
                ]
                all_done = len(records) == len(subagent_ids) and all(
                    r.is_terminal() for r in records
                )
                if all_done:
                    break

            time.sleep(poll_interval)

        with self._lock:
            self.check_timeouts()
            final_records = [
                self._tasks[sid] for sid in subagent_ids if sid in self._tasks
            ]
            completed_c = sum(
                1 for r in final_records if r.status == SubagentStatusEnum.COMPLETED
            )
            failed_c = sum(
                1 for r in final_records if r.status == SubagentStatusEnum.FAILED
            )
            killed_c = sum(
                1 for r in final_records if r.status == SubagentStatusEnum.KILLED
            )
            timeout_c = sum(
                1 for r in final_records if r.status == SubagentStatusEnum.TIMEOUT
            )
            all_terminal = len(final_records) == len(subagent_ids) and all(
                r.is_terminal() for r in final_records
            )

            return SubagentWaitResult(
                all_completed=all_terminal,
                completed_count=completed_c,
                failed_count=failed_c,
                killed_count=killed_c,
                timeout_count=timeout_c,
                tasks=final_records,
            )
