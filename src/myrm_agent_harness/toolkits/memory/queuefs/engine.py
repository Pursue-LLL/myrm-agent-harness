"""[POS]: src/myrm_agent_harness/toolkits/memory/queuefs/engine.py
[INPUT]: Semantic processing requests, DAG stage definitions, and lock coordinator.
[OUTPUT]: QueueFSDAGEngine orchestrating asynchronous resource ingestion and stage transitions.
"""

import asyncio
import time
import uuid

from .lock import PathSemanticLockManager
from .models import (
    QueueFSConfig,
    QueueFSStats,
    SemanticDAGStage,
    SemanticDAGTask,
    SemanticLockMode,
    SemanticTaskStatus,
)


class TaskNotFoundError(Exception):
    """Raised when querying a non-existent task ID."""


class QueueFSDAGEngine:
    """Asynchronous QueueFS engine managing named semantic tasks across sequential DAG stages."""

    def __init__(
        self,
        config: QueueFSConfig | None = None,
        lock_manager: PathSemanticLockManager | None = None,
    ) -> None:
        self.config = config or QueueFSConfig()
        self.lock_manager = lock_manager or PathSemanticLockManager(
            default_ttl_seconds=self.config.lock_ttl_seconds
        )
        self._tasks: dict[str, SemanticDAGTask] = {}
        self._op_lock = asyncio.Lock()

    def submit_task(
        self,
        resource_uri: str,
        payload: str = "",
        stages: list[SemanticDAGStage] | None = None,
    ) -> SemanticDAGTask:
        """Submit a new resource for asynchronous semantic processing without blocking caller."""
        now = time.time()
        task_id = f"qfs_task_{uuid.uuid4().hex[:12]}"
        planned_stages = (
            stages
            if stages is not None
            else [
                SemanticDAGStage.INGESTION,
                SemanticDAGStage.CHUNKING,
                SemanticDAGStage.SIDECAR,
                SemanticDAGStage.EMBEDDING,
                SemanticDAGStage.INDEXING,
            ]
        )

        task = SemanticDAGTask(
            task_id=task_id,
            resource_uri=resource_uri,
            payload=payload,
            stages=planned_stages,
            current_stage=planned_stages[0] if planned_stages else SemanticDAGStage.INGESTION,
            status=SemanticTaskStatus.PENDING,
            progress_pct=0.0,
            created_at_epoch=now,
            updated_at_epoch=now,
        )
        self._tasks[task_id] = task
        return task

    def get_task(self, task_id: str) -> SemanticDAGTask | None:
        """Retrieve task by unique identifier."""
        return self._tasks.get(task_id)

    def list_tasks(
        self,
        status: SemanticTaskStatus | None = None,
        limit: int = 50,
    ) -> list[SemanticDAGTask]:
        """List tracked tasks optionally filtered by execution status."""
        tasks = list(self._tasks.values())
        if status is not None:
            tasks = [t for t in tasks if t.status == status]
        tasks.sort(key=lambda t: t.created_at_epoch, reverse=True)
        return tasks[:limit]

    async def advance_stage(self, task_id: str) -> SemanticDAGTask:
        """Advance task to its subsequent DAG stage, updating progress."""
        async with self._op_lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise TaskNotFoundError(f"Task '{task_id}' not found")

            if task.status in (SemanticTaskStatus.COMPLETED, SemanticTaskStatus.FAILED):
                return task

            task.status = SemanticTaskStatus.RUNNING
            task.updated_at_epoch = time.time()

            try:
                current_idx = task.stages.index(task.current_stage)
            except ValueError:
                current_idx = 0

            next_idx = current_idx + 1
            if next_idx < len(task.stages):
                task.current_stage = task.stages[next_idx]
                task.progress_pct = round((next_idx / len(task.stages)) * 100.0, 1)
            else:
                task.status = SemanticTaskStatus.COMPLETED
                task.progress_pct = 100.0

            return task

    async def execute_pipeline(self, task_id: str) -> SemanticDAGTask:
        """Run entire DAG pipeline sequentially under path lock protection."""
        task = self._tasks.get(task_id)
        if task is None:
            raise TaskNotFoundError(f"Task '{task_id}' not found")

        # Acquire path lock during processing
        async with self.lock_manager.lock_scope(
            path_pattern=task.resource_uri,
            owner=f"worker_{task_id}",
            mode=SemanticLockMode.EXCLUSIVE,
        ):
            while task.status not in (SemanticTaskStatus.COMPLETED, SemanticTaskStatus.FAILED):
                await self.advance_stage(task_id)
                # Yield control briefly to simulate async step execution
                await asyncio.sleep(0.001)

        return task

    def fail_task(self, task_id: str, error_message: str) -> SemanticDAGTask:
        """Mark task as failed with diagnostic message."""
        task = self._tasks.get(task_id)
        if task is None:
            raise TaskNotFoundError(f"Task '{task_id}' not found")
        task.status = SemanticTaskStatus.FAILED
        task.error_message = error_message
        task.updated_at_epoch = time.time()
        return task

    def get_stats(self) -> QueueFSStats:
        """Collect aggregated queue statistics and active lock counts."""
        pending_c = sum(1 for t in self._tasks.values() if t.status == SemanticTaskStatus.PENDING)
        running_c = sum(1 for t in self._tasks.values() if t.status == SemanticTaskStatus.RUNNING)
        completed_c = sum(1 for t in self._tasks.values() if t.status == SemanticTaskStatus.COMPLETED)
        failed_c = sum(1 for t in self._tasks.values() if t.status == SemanticTaskStatus.FAILED)

        return QueueFSStats(
            pending_tasks=pending_c,
            running_tasks=running_c,
            completed_tasks=completed_c,
            failed_tasks=failed_c,
            active_locks=self.lock_manager.active_locks_count(),
        )
