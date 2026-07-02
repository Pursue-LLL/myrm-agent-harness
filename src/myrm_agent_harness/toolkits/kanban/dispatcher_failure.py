"""Kanban dispatcher failure handling — retry, auto-block, transient backoff.

[INPUT]
- kanban.types::KanbanTask, TaskStatus, BlockKind, TaskRunOutcome (POS: domain types)
- kanban.protocols::KanbanStore (POS: persistence protocol)

[OUTPUT]
- KanbanDispatcherFailureMixin: _handle_failure / _handle_timeout / _apply_failure_pipeline

[POS]
Failure, timeout, and retry pipeline for KanbanDispatcher — auto-block, transient backoff, retry re-queue.
Mixin host must provide _store, _board, emit(), wake(), _promote_dependents().
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from myrm_agent_harness.toolkits.kanban.types import (
    BlockKind,
    KanbanTask,
    TaskEventKind,
    TaskRunOutcome,
    TaskStatus,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)

_TRANSIENT_ERROR_RE = re.compile(
    r"(rate[\s_-]?limit|429|quota|too[\s_]many[\s_]requests|"
    r"capacity|overloaded|503|service[\s_]unavailable)",
    re.IGNORECASE,
)
_TRANSIENT_BACKOFF_SECONDS = 900


class KanbanDispatcherFailureMixin:
    """Failure, timeout, and retry pipeline for KanbanDispatcher."""

    async def _handle_failure(
        self,
        task_id: str,
        error: str,
        run_id: str,
    ) -> None:
        task = await self._store.get_task(task_id)
        if task is None:
            return
        if task.status != TaskStatus.RUNNING:
            logger.warning(
                "Task %s status changed to %s during execution, discarding failure",
                task_id[:8],
                task.status.value,
            )
            await self._store.complete_run(
                run_id,
                TaskRunOutcome.RECLAIMED,
                error="Status changed during execution",
            )
            return
        await self._apply_failure_pipeline(
            task,
            error,
            run_id,
            outcome=TaskRunOutcome.CRASHED,
            reason="crashed",
        )

    async def _handle_timeout(
        self,
        task_id: str,
        error: str,
        run_id: str,
        *,
        elapsed_seconds: float,
        limit_seconds: int,
    ) -> None:
        task = await self._store.get_task(task_id)
        if task is None:
            return
        if task.status != TaskStatus.RUNNING:
            logger.warning(
                "Task %s status changed to %s during execution, discarding timeout",
                task_id[:8],
                task.status.value,
            )
            await self._store.complete_run(
                run_id,
                TaskRunOutcome.RECLAIMED,
                error="Status changed during execution",
            )
            return
        await self._store.append_event(
            task_id,
            TaskEventKind.TIMED_OUT,
            payload={
                "elapsed_seconds": round(elapsed_seconds, 1),
                "limit_seconds": limit_seconds,
            },
            run_id=run_id,
        )
        logger.warning(
            "Task %s timed out after %.0fs (limit %ds)",
            task_id[:8],
            elapsed_seconds,
            limit_seconds,
        )
        await self._apply_failure_pipeline(
            task,
            error,
            run_id,
            outcome=TaskRunOutcome.TIMED_OUT,
            reason="timed_out",
        )

    async def _apply_failure_pipeline(
        self,
        task: KanbanTask,
        error: str,
        run_id: str,
        *,
        outcome: TaskRunOutcome,
        reason: str,
    ) -> None:
        """Shared retry → auto-block → fail pipeline for crashes and timeouts."""
        task_id = task.task_id
        settings = self._board.settings
        task.retry_count += 1
        task.consecutive_failures += 1
        task.error = error
        task.progress_note = None

        if task.consecutive_failures >= settings.auto_block_after_consecutive_failures:
            task.status = TaskStatus.BLOCKED
            task.block_kind = BlockKind.HUMAN
            task.blocked_reason = (
                f"Auto-blocked after {task.consecutive_failures} consecutive failures (last: {reason})"
            )
            logger.warning("Task %s auto-blocked: %s", task_id[:8], task.blocked_reason)
            await self._store.complete_run(run_id, outcome, error=error)
            await self._store.append_event(
                task_id,
                TaskEventKind.BLOCKED,
                payload={"reason": task.blocked_reason, "block_kind": "human"},
                run_id=run_id,
            )
            self.emit("task_blocked", task)
        elif task.is_retriable:
            is_transient = bool(_TRANSIENT_ERROR_RE.search(error))
            if is_transient:
                wake_at = datetime.now(UTC) + timedelta(seconds=_TRANSIENT_BACKOFF_SECONDS)
                task.status = TaskStatus.BLOCKED
                task.block_kind = BlockKind.SCHEDULED
                task.scheduled_until = wake_at
                task.blocked_reason = f"Transient error detected, auto-retry at {wake_at.strftime('%H:%M UTC')}"
                logger.info(
                    "Task %s transient error (attempt %d/%d), scheduled backoff until %s",
                    task_id[:8],
                    task.retry_count,
                    task.max_retries,
                    wake_at.isoformat(),
                )
                await self._store.complete_run(run_id, outcome, error=error)
                await self._store.append_event(
                    task_id,
                    TaskEventKind.BLOCKED,
                    payload={
                        "reason": task.blocked_reason,
                        "block_kind": "scheduled",
                        "transient_error": True,
                        "wake_at": wake_at.isoformat(),
                    },
                    run_id=run_id,
                )
                self.emit("task_blocked", task)
            else:
                task.status = TaskStatus.READY
                logger.info(
                    "Task %s %s (attempt %d/%d), re-queuing",
                    task_id[:8],
                    reason,
                    task.retry_count,
                    task.max_retries,
                )
                await self._store.complete_run(run_id, outcome, error=error)
                await self._store.append_event(
                    task_id,
                    TaskEventKind.RETRYING,
                    payload={
                        "attempt": task.retry_count,
                        "max": task.max_retries,
                        "reason": reason,
                    },
                    run_id=run_id,
                )
                self.emit("task_retrying", task)
        else:
            task.status = TaskStatus.FAILED
            task.completed_at = datetime.now(UTC)
            logger.warning("Task %s exhausted retries (last: %s)", task_id[:8], reason)
            await self._store.complete_run(run_id, outcome, error=error)
            await self._store.append_event(
                task_id,
                TaskEventKind.FAILED,
                run_id=run_id,
            )
            self.emit("task_failed", task)

        await self._store.save_task(task)

        if task.status == TaskStatus.FAILED:
            await self._promote_dependents(task_id)

        self.wake()
