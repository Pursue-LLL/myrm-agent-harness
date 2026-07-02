"""Kanban dispatcher — event-driven task scheduling.

Handles: startup orphan rescue, dispatch loop, heartbeat monitoring,
zombie detection & reclaim, auto-block on consecutive failures, per-task
retries, transient error smart backoff (429/503/quota → SCHEDULED block
with auto-wakeup).

[INPUT]
- .types::KanbanBoard, KanbanTask, TaskStatus, BoardSettings, TaskTimeoutError (POS: Kanban domain types.)
- .protocols::KanbanStore, TaskRunner (POS: Protocols for the kanban toolkit.)
- .dispatcher_failure::KanbanDispatcherFailureMixin (POS: Failure/timeout/retry pipeline for KanbanDispatcher.)

[OUTPUT]
- KanbanDispatcher: Event-driven multi-task scheduler.

[POS]
Kanban dispatcher — event-driven task scheduling.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.kanban.dispatcher_failure import (
    KanbanDispatcherFailureMixin,
    _TRANSIENT_BACKOFF_SECONDS,
    _TRANSIENT_ERROR_RE,
)
from myrm_agent_harness.toolkits.kanban.types import (
    BlockKind,
    KanbanTask,
    TaskEventKind,
    TaskRunOutcome,
    TaskStatus,
    TaskTimeoutError,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.kanban.protocols import (
        CompletionVerifier,
        KanbanStore,
        TaskRunner,
    )
    from myrm_agent_harness.toolkits.kanban.types import KanbanBoard

logger = get_agent_logger(__name__)

KanbanEventCallback = Callable[[str, KanbanTask], None]


class KanbanDispatcher(KanbanDispatcherFailureMixin):
    """Event-driven multi-task scheduler.

    Lifecycle:
        dispatcher = KanbanDispatcher(store, runner, board)
        await dispatcher.start()
        ...
        await dispatcher.stop()
    """

    def __init__(
        self,
        store: KanbanStore,
        runner: TaskRunner,
        board: KanbanBoard,
        worker_id: str | None = None,
        verifier: CompletionVerifier | None = None,
    ) -> None:
        self._store = store
        self._runner = runner
        self._board = board
        self._worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self._verifier = verifier

        self._dispatch_task: asyncio.Task[None] | None = None
        self._zombie_task: asyncio.Task[None] | None = None
        self._running = False
        self._wake_event = asyncio.Event()
        self._exec_tasks: set[asyncio.Task[None]] = set()
        self._task_id_to_exec: dict[str, asyncio.Task[None]] = {}

        self._event_callbacks: list[KanbanEventCallback] = []

    # -- Public API --

    @property
    def worker_id(self) -> str:
        return self._worker_id

    @property
    def is_running(self) -> bool:
        return self._running

    def on_event(self, callback: KanbanEventCallback) -> None:
        """Register a callback for task lifecycle events (for SSE/EventBus)."""
        self._event_callbacks.append(callback)

    async def start(self) -> None:
        """Start the dispatch and zombie-detection loops.

        On startup, rescues orphaned RUNNING tasks left by a prior crash
        before entering the main loops.
        """
        if self._running:
            return
        self._running = True
        await self._rescue_orphaned_tasks()
        self._dispatch_task = asyncio.create_task(self._dispatch_loop(), name="kanban-dispatch")
        self._zombie_task = asyncio.create_task(self._zombie_loop(), name="kanban-zombie")
        logger.info(
            "Kanban dispatcher started for board=%s worker=%s",
            self._board.board_id,
            self._worker_id,
        )

    async def stop(self, graceful_timeout: float = 30.0) -> None:
        """Stop all loops and wait for executing tasks to finish."""
        self._running = False
        self._wake_event.set()
        for task in (self._dispatch_task, self._zombie_task):
            if task and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._dispatch_task = None
        self._zombie_task = None

        if self._exec_tasks:
            logger.info(
                "Waiting for %d executing tasks (timeout=%.0fs)",
                len(self._exec_tasks),
                graceful_timeout,
            )
            _done, pending = await asyncio.wait(
                self._exec_tasks,
                timeout=graceful_timeout,
            )
            for t in pending:
                t.cancel()
            if pending:
                logger.warning(
                    "%d tasks did not finish within %.0fs, cancelled",
                    len(pending),
                    graceful_timeout,
                )

        logger.info("Kanban dispatcher stopped for board=%s", self._board.board_id)

    def wake(self) -> None:
        """Signal the dispatcher to check for new tasks immediately."""
        self._wake_event.set()

    async def cancel_execution(self, task_id: str) -> bool:
        """Cancel the asyncio.Task executing a kanban task without modifying task state.

        Returns True if a running execution was cancelled, False if the task
        was not being executed by this dispatcher.
        """
        exec_task = self._task_id_to_exec.get(task_id)
        if exec_task is None or exec_task.done():
            return False

        exec_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await exec_task
        return True

    async def reclaim_task(self, task_id: str, reason: str | None = None) -> bool:
        """Manually reclaim a running task: cancel its worker, close the run,
        reset to READY so the dispatcher can re-schedule it.

        Returns True if a running worker was cancelled, False if the task
        was not being executed by this dispatcher.
        """
        exec_task = self._task_id_to_exec.get(task_id)
        if exec_task is None or exec_task.done():
            return False

        exec_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await exec_task

        task = await self._store.get_task(task_id)
        if task is None:
            return True

        runs = await self._store.list_runs(task_id)
        active_run_id: str | None = None
        for r in reversed(runs):
            if not r.is_finished:
                active_run_id = r.run_id
                await self._store.complete_run(
                    r.run_id,
                    TaskRunOutcome.RECLAIMED,
                    error=f"manual_reclaim: {reason or 'user request'}",
                )
                break

        task.status = TaskStatus.READY
        task.consecutive_failures = 0
        task.error = ""
        task.last_heartbeat_at = None
        task.progress_note = None
        await self._store.save_task(task)
        await self._store.append_event(
            task_id,
            TaskEventKind.RECLAIMED,
            payload={"manual": True, "reason": reason or "user request"},
            run_id=active_run_id,
        )
        self.emit("task_reclaimed", task)
        self.wake()
        logger.info(
            "Task %s manually reclaimed: %s",
            task_id[:8],
            reason or "user request",
        )
        return True

    # -- Dispatch loop --

    async def _dispatch_loop(self) -> None:
        settings = self._board.settings
        while self._running:
            try:
                running_count = len(await self._store.list_running_tasks(self._board.board_id))
                available_slots = settings.max_concurrent_tasks - running_count

                if available_slots > 0:
                    ready_tasks = await self._store.list_ready_tasks(self._board.board_id)
                    for task in ready_tasks[:available_slots]:
                        claimed = await self._store.claim_task(task.task_id, self._worker_id)
                        if claimed:
                            t = asyncio.create_task(
                                self._execute_task(task.task_id),
                                name=f"kanban-exec-{task.task_id[:8]}",
                            )
                            self._exec_tasks.add(t)
                            self._task_id_to_exec[task.task_id] = t

                            def _on_exec_done(
                                fut: asyncio.Task[None],
                                tid: str = task.task_id,
                            ) -> None:
                                self._exec_tasks.discard(fut)
                                self._task_id_to_exec.pop(tid, None)

                            t.add_done_callback(_on_exec_done)

                self._wake_event.clear()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        self._wake_event.wait(),
                        timeout=settings.heartbeat_interval_seconds,
                    )

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Kanban dispatch loop error")
                await asyncio.sleep(5)

    async def _execute_task(self, task_id: str) -> None:
        """Execute a single task with heartbeat, run tracking, and auto-block."""
        task = await self._store.get_task(task_id)
        if task is None:
            return
        if task.status != TaskStatus.RUNNING:
            logger.warning(
                "Task %s status drifted to %s after claim, aborting execution",
                task_id[:8],
                task.status.value,
            )
            return

        run = await self._store.create_run(task_id, self._worker_id)
        await self._store.append_event(
            task_id,
            TaskEventKind.CLAIMED,
            payload={"worker_id": self._worker_id},
            run_id=run.run_id,
        )
        self.emit("task_started", task)

        heartbeat_handle = asyncio.create_task(
            self._heartbeat_loop(task_id),
            name=f"kanban-hb-{task_id[:8]}",
        )

        try:
            success, result_text = await self._runner.run(task)
            heartbeat_handle.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_handle

            if success:
                await self._handle_success(task_id, result_text, run.run_id)
            else:
                await self._handle_failure(task_id, result_text, run.run_id)
        except asyncio.CancelledError:
            heartbeat_handle.cancel()
            raise
        except TaskTimeoutError as exc:
            heartbeat_handle.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_handle
            await self._handle_timeout(
                task_id,
                str(exc),
                run.run_id,
                elapsed_seconds=exc.elapsed_seconds,
                limit_seconds=exc.limit_seconds,
            )
        except Exception as exc:
            heartbeat_handle.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_handle
            await self._handle_failure(task_id, str(exc), run.run_id)

    async def _handle_success(
        self,
        task_id: str,
        result: str,
        run_id: str,
    ) -> None:
        task = await self._store.get_task(task_id)
        if task is None:
            return
        if task.status != TaskStatus.RUNNING:
            if task.status == TaskStatus.COMPLETED:
                # Agent called kanban_complete directly — task already done.
                # Finalize run as COMPLETED and ensure dependents are promoted.
                await self._store.complete_run(
                    run_id,
                    TaskRunOutcome.COMPLETED,
                    summary=task.result or result,
                )
                self.emit("task_completed", task)
                await self._promote_dependents(task_id)
                self.wake()
                logger.info("Task %s completed via kanban_complete tool", task_id[:8])
            else:
                logger.warning(
                    "Task %s status changed to %s during execution, discarding success result",
                    task_id[:8],
                    task.status.value,
                )
                await self._store.complete_run(
                    run_id,
                    TaskRunOutcome.RECLAIMED,
                    error="Status changed during execution",
                )
            return

        if self._verifier:
            try:
                vr = await asyncio.wait_for(
                    self._verifier.verify(task, result),
                    timeout=60.0,
                )
            except TimeoutError:
                logger.warning("Task %s verification timed out", task_id[:8])
                await self._store.append_event(
                    task_id,
                    TaskEventKind.VERIFICATION_FAILED,
                    payload={"reason": "Verification timed out"},
                    run_id=run_id,
                )
                await self._handle_failure(task_id, "Verification timed out", run_id)
                return
            except Exception as exc:
                logger.warning("Task %s verification error: %s", task_id[:8], exc)
                await self._store.append_event(
                    task_id,
                    TaskEventKind.VERIFICATION_FAILED,
                    payload={"reason": f"Verification error: {exc}"},
                    run_id=run_id,
                )
                await self._handle_failure(
                    task_id,
                    f"Verification error: {exc}",
                    run_id,
                )
                return

            if not vr.passed:
                reason = vr.reason or "Completion verification failed"
                logger.warning(
                    "Task %s failed verification: %s",
                    task_id[:8],
                    reason,
                )
                await self._store.append_event(
                    task_id,
                    TaskEventKind.VERIFICATION_FAILED,
                    payload={"reason": reason, "error_logs": vr.error_logs or ""},
                    run_id=run_id,
                )
                self.emit("verification_failed", task)
                await self._handle_failure(task_id, reason, run_id)
                return

        task.status = TaskStatus.COMPLETED
        task.result = result
        task.completed_at = datetime.now(UTC)
        task.consecutive_failures = 0
        task.block_cycle_count = 0
        task.progress_note = None
        await self._store.save_task(task)
        await self._store.complete_run(
            run_id,
            TaskRunOutcome.COMPLETED,
            summary=result,
        )
        await self._store.append_event(
            task_id,
            TaskEventKind.COMPLETED,
            run_id=run_id,
        )
        self.emit("task_completed", task)
        await self._promote_dependents(task_id)
        self.wake()
        logger.info("Task %s completed", task_id[:8])

    # -- Dependency promotion --

    async def _promote_dependents(self, completed_task_id: str) -> None:
        """Promote BACKLOG children to READY when all their parents are terminal."""
        children_ids = await self._store.list_children(completed_task_id)
        for child_id in children_ids:
            child = await self._store.get_task(child_id)
            if child is None or child.status != TaskStatus.BACKLOG:
                continue
            if await self._store.are_dependencies_met(child_id):
                child.status = TaskStatus.READY
                await self._store.save_task(child)
                await self._store.append_event(
                    child_id,
                    TaskEventKind.PROMOTED,
                    payload={"trigger_task_id": completed_task_id},
                )
                self.emit("task_promoted", child)
                logger.info(
                    "Task %s promoted to READY (parent %s completed)",
                    child_id[:8],
                    completed_task_id[:8],
                )

    # -- Heartbeat --

    async def _heartbeat_loop(self, task_id: str) -> None:
        interval = self._board.settings.heartbeat_interval_seconds
        while True:
            await asyncio.sleep(interval)
            try:
                await self._store.update_heartbeat(task_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Heartbeat update failed for task %s, will retry next interval", task_id[:8], exc_info=True)

    # -- Startup rescue --

    async def _rescue_orphaned_tasks(self) -> None:
        """Reclaim RUNNING tasks orphaned by a prior process crash.

        Called once during ``start()`` before the dispatch/zombie loops begin.
        Uses the same ``_reclaim_task`` pipeline (retry/block/fail/event/emit)
        so behaviour is identical to zombie detection — just immediate.

        Best-effort: store errors are logged but never prevent dispatcher
        startup.
        """
        try:
            orphans = await self._store.list_running_tasks(self._board.board_id)
        except Exception:
            logger.warning("Startup rescue: failed to query running tasks, skipping", exc_info=True)
            return
        active_ids = set(self._task_id_to_exec)
        rescued = 0
        for task in orphans:
            if task.task_id in active_ids:
                continue
            try:
                await self._reclaim_task(task)
                rescued += 1
            except Exception:
                logger.warning("Startup rescue: failed to reclaim task %s", task.task_id[:8], exc_info=True)
        if rescued:
            logger.info(
                "Rescued %d orphaned task(s) on startup for board=%s",
                rescued,
                self._board.board_id,
            )

    # -- Zombie detection --

    async def _zombie_loop(self) -> None:
        settings = self._board.settings
        check_interval = max(settings.zombie_timeout_seconds // 2, 30)
        while self._running:
            try:
                zombies = await self._store.list_zombie_tasks(self._board.board_id, settings.zombie_timeout_seconds)
                for task in zombies:
                    logger.warning(
                        "Zombie detected: task=%s, last_heartbeat=%s",
                        task.task_id[:8],
                        task.last_heartbeat_at,
                    )
                    await self._reclaim_task(task)

                await self._wakeup_scheduled_tasks()

                await asyncio.sleep(check_interval)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Kanban zombie loop error")
                await asyncio.sleep(check_interval)

    async def _wakeup_scheduled_tasks(self) -> None:
        """Auto-unblock tasks whose scheduled_until has passed."""
        due_tasks = await self._store.list_due_scheduled_tasks(self._board.board_id)
        for task in due_tasks:
            deps_met = await self._store.are_dependencies_met(task.task_id)
            target = TaskStatus.READY if deps_met else TaskStatus.BACKLOG
            task.status = target
            task.blocked_reason = None
            task.block_kind = None
            task.scheduled_until = None
            task.consecutive_failures = 0
            task.error = ""
            await self._store.save_task(task)
            await self._store.append_event(
                task.task_id,
                TaskEventKind.UNBLOCKED,
                payload={"source": "auto_schedule", "target": target.value},
            )
            self.emit("task_unblocked", task)
            logger.info(
                "Task %s auto-unblocked (scheduled wakeup) -> %s",
                task.task_id[:8],
                target.value,
            )
        if due_tasks:
            self.wake()

    async def _reclaim_task(self, task: KanbanTask) -> None:
        """Reclaim a zombie task: retry or fail based on budget."""
        exec_task = self._task_id_to_exec.get(task.task_id)
        if exec_task and not exec_task.done():
            exec_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await exec_task

        task.retry_count += 1
        task.consecutive_failures += 1
        task.error = "Reclaimed from zombie state (heartbeat timeout)"
        task.progress_note = None

        runs = await self._store.list_runs(task.task_id)
        active_run_id: str | None = None
        for r in reversed(runs):
            if not r.is_finished:
                active_run_id = r.run_id
                await self._store.complete_run(
                    r.run_id,
                    TaskRunOutcome.RECLAIMED,
                    error="Heartbeat timeout",
                )
                break

        await self._store.append_event(
            task.task_id,
            TaskEventKind.RECLAIMED,
            payload={"reason": "heartbeat_timeout"},
            run_id=active_run_id,
        )

        settings = self._board.settings
        if task.consecutive_failures >= settings.auto_block_after_consecutive_failures:
            task.status = TaskStatus.BLOCKED
            task.block_kind = BlockKind.HUMAN
            task.blocked_reason = f"Auto-blocked after zombie reclaim ({task.consecutive_failures} failures)"
            self.emit("task_blocked", task)
        elif task.is_retriable:
            task.status = TaskStatus.READY
            task.last_heartbeat_at = None
            self.emit("task_retrying", task)
        else:
            task.status = TaskStatus.FAILED
            task.completed_at = datetime.now(UTC)
            self.emit("task_failed", task)

        await self._store.save_task(task)
        self.wake()

    # -- Event emission --

    def emit(self, event_type: str, task: KanbanTask) -> None:
        """Emit a lifecycle event to all registered callbacks."""
        for cb in self._event_callbacks:
            try:
                cb(event_type, task)
            except Exception:
                logger.exception("Kanban event callback error")
