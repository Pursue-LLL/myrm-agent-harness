"""Background evolution task management with observability and graceful shutdown.

Provides production-grade background task execution for evolution triggers
(tool degradation, metric monitoring) with timeout protection, progress tracking,
concurrent semaphore control, and optional global load-aware scheduling.

[INPUT]
- runtime.maintenance.protocols::AgentHealthScore, (POS: Maintenance scheduling protocols and data types.)

[OUTPUT]
- BackgroundEvolutionTask: Metadata for a background evolution task.
- BackgroundEvolutionTaskManager: Manage background evolution tasks with timeout, progress ...

[POS]
Background evolution task management with observability and graceful shutdown.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any

from myrm_agent_harness.runtime.maintenance.protocols import (
    AgentHealthScore,
    CapacityDenial,
    CapacityTicket,
    MaintenanceScheduler,
    MaintenanceTaskType,
)

logger = logging.getLogger(__name__)

__all__ = [
    "BackgroundEvolutionTask",
    "BackgroundEvolutionTaskManager",
]


@dataclass
class BackgroundEvolutionTask:
    """Metadata for a background evolution task."""

    task_id: str
    task: asyncio.Task[None]
    label: str
    trigger_type: str
    skill_ids: list[str]
    started_at: float
    progress: str | None = None
    ticket: CapacityTicket | None = None


class BackgroundEvolutionTaskManager:
    """Manage background evolution tasks with timeout, progress tracking, and graceful shutdown.

    Framework layer component (开箱即用):
    - Automatic timeout protection (default 30s)
    - Progress tracking for observability
    - Concurrent semaphore control (local) + optional global load-aware scheduling
    - Graceful shutdown (await all pending tasks)
    - Exception handling and logging
    """

    def __init__(
        self,
        *,
        shutdown_timeout: float = 30.0,
        max_concurrent_background: int = 5,
        scheduler: MaintenanceScheduler | None = None,
    ) -> None:
        self._tasks: dict[str, BackgroundEvolutionTask] = {}
        self._shutdown_timeout = shutdown_timeout
        self._semaphore = asyncio.Semaphore(max_concurrent_background)
        self._lock = asyncio.Lock()
        self._scheduler = scheduler

    async def schedule(
        self,
        coro: Coroutine[None, None, None],
        *,
        label: str,
        trigger_type: str,
        skill_ids: list[str] | None = None,
        health_score: AgentHealthScore | None = None,
    ) -> str | None:
        """Schedule a background evolution task.

        If a MaintenanceScheduler is configured, requests capacity first.
        Returns None if the scheduler denies the request (system too busy).
        """
        skill_ids = skill_ids or []

        ticket: CapacityTicket | None = None
        if self._scheduler:
            result = await self._scheduler.request_capacity(MaintenanceTaskType.EVOLUTION, health_score=health_score)
            if isinstance(result, CapacityDenial):
                logger.info(
                    "Evolution task '%s' deferred: %s (retry after %.0fs)",
                    label,
                    result.reason,
                    result.retry_after_seconds,
                )
                return None
            ticket = result

        task_id = f"{label}_{uuid.uuid4().hex[:8]}"

        async def _wrapped() -> None:
            async with self._semaphore:
                try:
                    await coro
                    logger.debug("Background task %s completed", task_id)
                except asyncio.CancelledError:
                    logger.warning("Background task %s cancelled", task_id)
                    raise
                except Exception as e:
                    logger.error("Background task %s failed: %s", task_id, e, exc_info=True)
                    raise
                finally:
                    async with self._lock:
                        meta = self._tasks.pop(task_id, None)
                    if meta and meta.ticket and self._scheduler:
                        await self._scheduler.release_capacity(meta.ticket)

        task = asyncio.create_task(_wrapped(), name=task_id)

        async with self._lock:
            self._tasks[task_id] = BackgroundEvolutionTask(
                task_id=task_id,
                task=task,
                label=label,
                trigger_type=trigger_type,
                skill_ids=skill_ids,
                started_at=time.time(),
                ticket=ticket,
            )

        logger.info("Scheduled background task: %s (%s, %d skills)", task_id, trigger_type, len(skill_ids))
        return task_id

    async def wait_all(self, timeout: float | None = None) -> dict[str, Any]:
        """Wait for all background tasks to complete (with timeout protection).

        Used during graceful shutdown to ensure all pending evolutions complete.

        Args:
            timeout: Max seconds to wait (default: self._shutdown_timeout)

        Returns:
            Summary dict:
            - total: Total task count
            - completed: Successfully completed count
            - timeout: Timeout cancel count
            - failed: Exception count
            - task_ids: List of all task IDs
        """
        timeout = timeout or self._shutdown_timeout

        async with self._lock:
            if not self._tasks:
                return {"total": 0, "completed": 0, "timeout": 0, "failed": 0, "task_ids": []}

            tasks = [meta.task for meta in self._tasks.values()]
            task_ids = list(self._tasks.keys())

        logger.info("Waiting for %d background evolution task(s) (timeout=%.0fs)...", len(tasks), timeout)

        try:
            results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=timeout)
        except TimeoutError:
            # Timeout: cancel remaining tasks
            async with self._lock:
                for task_id, meta in list(self._tasks.items()):
                    if not meta.task.done():
                        meta.task.cancel()
                        logger.warning("Background task %s cancelled (timeout)", task_id)

            # Wait briefly for cancellation to complete
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=2.0)

            results = [TimeoutError()] * len(tasks)

        # Analyze results
        completed = sum(1 for r in results if not isinstance(r, Exception))
        timeout_count = sum(1 for r in results if isinstance(r, asyncio.TimeoutError))
        failed = sum(1 for r in results if isinstance(r, Exception) and not isinstance(r, asyncio.TimeoutError))

        return {
            "total": len(tasks),
            "completed": completed,
            "timeout": timeout_count,
            "failed": failed,
            "task_ids": task_ids,
        }

    def get_status(self) -> list[dict[str, Any]]:
        """Get current status of all background tasks (non-blocking).

        Returns:
            List of task status dicts with:
            - task_id, label, trigger_type, skill_ids
            - running_time (seconds)
            - progress (optional message)
            - done (boolean)
        """
        # No async needed - just read current state
        return [
            {
                "task_id": task_id,
                "label": meta.label,
                "trigger_type": meta.trigger_type,
                "skill_ids": meta.skill_ids,
                "running_time": time.time() - meta.started_at,
                "progress": meta.progress,
                "done": meta.task.done(),
            }
            for task_id, meta in self._tasks.items()
        ]

    async def update_progress(self, task_id: str, progress: str) -> None:
        """Update progress message for a task.

        Args:
            task_id: Task identifier
            progress: Progress message (e.g., "Confirming 3 skills...")
        """
        async with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].progress = progress

    def count_active(self) -> int:
        """Get count of active background tasks."""
        return len(self._tasks)
