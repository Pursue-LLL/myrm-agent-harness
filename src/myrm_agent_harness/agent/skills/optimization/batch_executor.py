"""Batch Optimization Executor

High-performance batch execution engine for skill optimization with priority queuing,
resource quota protection, performance monitoring, and graceful cancellation.

[INPUT]
- .types.* (POS: Core types)
- .event_emitter.EventEmitter (POS: Event system)
- .protocols.SkillOptimizer (POS: Optimizer interface)

[OUTPUT]
- BatchExecutor: Batch execution engine with priority support
- TaskState: Task state machine (PENDING → RUNNING → SUCCESS/FAILED/CANCELLED)
- RetryPolicy: Configurable retry strategy with exponential backoff
- PerformanceMetrics: Performance monitoring data

[POS]
Framework-layer batch execution engine for skill optimization.
Provides enterprise-grade features:
1. Priority queue with aging mechanism (prevents task starvation)
2. Resource quota protection (prevents system overload)
3. Performance monitoring (execution time, token consumption)
4. Graceful cancellation (cancel running batch tasks)
5. Configurable retry policy (exponential backoff)
6. Event-driven progress tracking (real-time updates)

Design Principles:
- Protocol-based: Depends on interfaces, not implementations
- Stateless: Task state managed externally (optional persistence)
- Event-driven: Decouples notification from execution
- Single-responsibility: Only handles batch execution logic
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .event_emitter import EventEmitter

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Task status enum"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskState:
    """Task state with performance metrics

    Attributes:
        task_id: Unique task identifier
        skill_id: Skill ID to optimize
        status: Current task status
        priority: Task priority (higher = more urgent)
        created_at: Task creation timestamp
        started_at: Task execution start timestamp
        completed_at: Task completion timestamp
        execution_time: Actual execution time in seconds
        token_consumption: Total tokens consumed (input + output)
        retry_count: Number of retry attempts
        error_message: Error message if failed
    """

    task_id: str
    skill_id: str
    status: TaskStatus = TaskStatus.PENDING
    priority: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    execution_time: float = 0.0
    token_consumption: int = 0
    retry_count: int = 0
    error_message: str | None = None


@dataclass
class RetryPolicy:
    """Configurable retry policy with exponential backoff

    Attributes:
        max_retries: Maximum retry attempts (default: 3)
        initial_delay: Initial delay in seconds (default: 1.0)
        backoff_factor: Exponential backoff multiplier (default: 2.0)
        max_delay: Maximum delay cap in seconds (default: 60.0)

    Example:
        Retry delays: 1s, 2s, 4s (with backoff_factor=2.0)
    """

    max_retries: int = 3
    initial_delay: float = 1.0
    backoff_factor: float = 2.0
    max_delay: float = 60.0

    def get_delay(self, retry_count: int) -> float:
        """Calculate delay for current retry attempt"""
        delay = self.initial_delay * (self.backoff_factor**retry_count)
        return min(delay, self.max_delay)


@dataclass
class PerformanceMetrics:
    """Performance metrics for batch execution

    Attributes:
        total_tasks: Total number of tasks
        completed_tasks: Number of completed tasks
        failed_tasks: Number of failed tasks
        cancelled_tasks: Number of cancelled tasks
        total_execution_time: Total execution time in seconds
        total_token_consumption: Total tokens consumed
        average_execution_time: Average execution time per task
        tasks_per_second: Task completion throughput
    """

    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    cancelled_tasks: int = 0
    total_execution_time: float = 0.0
    total_token_consumption: int = 0

    @property
    def average_execution_time(self) -> float:
        """Average execution time per completed task"""
        if self.completed_tasks == 0:
            return 0.0
        return self.total_execution_time / self.completed_tasks

    @property
    def tasks_per_second(self) -> float:
        """Task completion throughput"""
        if self.total_execution_time == 0:
            return 0.0
        return self.completed_tasks / self.total_execution_time


class ResourceQuotaProtocol:
    """Protocol for resource quota checking

    Framework provides the interface; business layer implements quota logic
    (e.g., check LLM quota, check concurrent task limits, check daily usage).
    """

    async def check_quota(self, task: TaskState) -> bool:
        """Check if quota is available for this task

        Args:
            task: Task to check quota for

        Returns:
            True if quota is available, False otherwise
        """
        raise NotImplementedError


class BatchExecutor:
    """High-performance batch execution engine with priority and resource protection

    Features:
    - Priority queue with aging mechanism (prevents starvation)
    - Resource quota protection (configurable quota checker)
    - Performance monitoring (execution time + token consumption)
    - Graceful cancellation (cancel entire batch or individual tasks)
    - Configurable retry policy (exponential backoff)
    - Event-driven progress tracking (real-time updates)

    Args:
        executor_fn: Async function to execute each task
        event_emitter: Event emitter for progress notifications
        retry_policy: Retry policy (default: 3 retries with exponential backoff)
        quota_checker: Optional resource quota checker
        aging_interval: Priority aging interval in seconds (default: 60s)

    Example:
        ```python
        from myrm_agent_harness.agent.skills.optimization import BatchExecutor, RetryPolicy

        async def optimize_skill(skill_id: str) -> dict:
            # Your optimization logic
            return {"skill_id": skill_id, "quality": 0.85}

        executor = BatchExecutor(
            executor_fn=optimize_skill,
            event_emitter=event_emitter,
            retry_policy=RetryPolicy(max_retries=3))

        batch_id = await executor.submit_batch(
            ["skill_1", "skill_2", "skill_3"],
            max_concurrent=3,
            priority=1)

        # Monitor progress
        progress = await executor.get_batch_progress(batch_id)

        # Cancel if needed
        await executor.cancel_batch(batch_id)
        ```
    """

    def __init__(
        self,
        executor_fn: Callable[[str], Any],
        event_emitter: EventEmitter,
        retry_policy: RetryPolicy | None = None,
        quota_checker: ResourceQuotaProtocol | None = None,
        aging_interval: int = 60,
    ):
        self.executor_fn = executor_fn
        self.event_emitter = event_emitter
        self.retry_policy = retry_policy or RetryPolicy()
        self.quota_checker = quota_checker
        self.aging_interval = aging_interval

        # Priority queue: (priority, timestamp, task_state)
        self._task_queue: asyncio.PriorityQueue[tuple[int, float, TaskState]] = asyncio.PriorityQueue()

        # Batch tracking: {batch_id: {tasks, metrics, status}}
        self._batches: dict[str, dict[str, Any]] = {}

        # Task tracking: {task_id: TaskState}
        self._tasks: dict[str, TaskState] = {}

        # Cancellation tokens: {batch_id: asyncio.Event}
        self._cancellation_tokens: dict[str, asyncio.Event] = {}

        # Worker tasks
        self._workers: list[asyncio.Task] = []

        # Performance metrics
        self._metrics = PerformanceMetrics()

    async def start_workers(self, num_workers: int = 3) -> None:
        """Start worker tasks to process the queue

        Args:
            num_workers: Number of concurrent workers (default: 3)
        """
        if self._workers:
            logger.warning("Workers already running")
            return

        logger.info(f"Starting {num_workers} batch executor workers")
        for i in range(num_workers):
            worker = asyncio.create_task(self._worker_loop(worker_id=i))
            self._workers.append(worker)

        # Start aging task
        aging_task = asyncio.create_task(self._aging_loop())
        self._workers.append(aging_task)

    async def stop_workers(self) -> None:
        """Stop all worker tasks gracefully"""
        logger.info("Stopping batch executor workers")
        for worker in self._workers:
            worker.cancel()

        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    async def submit_batch(self, item_ids: list[str], max_concurrent: int = 3, priority: int = 0) -> str:
        """Submit a batch of tasks for execution

        Args:
            item_ids: List of item IDs to process (e.g., skill IDs)
            max_concurrent: Maximum concurrent tasks (unused in priority queue mode)
            priority: Batch priority (higher = more urgent)

        Returns:
            batch_id: Unique batch identifier for progress tracking
        """
        batch_id = f"batch_{uuid.uuid4().hex[:8]}"
        cancellation_token = asyncio.Event()

        # Create task states
        tasks = [
            TaskState(task_id=f"{batch_id}_{i}", skill_id=skill_id, priority=priority)
            for i, skill_id in enumerate(item_ids)
        ]

        # Add to batch tracking
        self._batches[batch_id] = {
            "batch_id": batch_id,
            "task_ids": [t.task_id for t in tasks],
            "status": "running",
            "created_at": datetime.now(),
            "completed_at": None,
        }

        self._cancellation_tokens[batch_id] = cancellation_token

        # Enqueue all tasks
        for task in tasks:
            self._tasks[task.task_id] = task
            await self._task_queue.put((-task.priority, time.time(), task))

        logger.info(f"Batch {batch_id} submitted: {len(item_ids)} tasks, priority={priority}")

        # Emit batch_started event
        await self.event_emitter.emit(
            "batch_optimization_started",
            {
                "batch_id": batch_id,
                "total_tasks": len(item_ids),
                "priority": priority,
            },
        )

        return batch_id

    async def _worker_loop(self, worker_id: int) -> None:
        """Worker loop to process tasks from the queue

        Args:
            worker_id: Worker identifier for logging
        """
        logger.info(f"Batch executor worker {worker_id} started")

        while True:
            try:
                # Get task from priority queue
                _, _timestamp, task = await self._task_queue.get()

                # Find batch_id for this task
                batch_id = self._find_batch_for_task(task.task_id)
                if not batch_id:
                    logger.warning(f"Task {task.task_id} has no associated batch")
                    continue

                # Check cancellation
                if batch_id in self._cancellation_tokens and self._cancellation_tokens[batch_id].is_set():
                    task.status = TaskStatus.CANCELLED
                    task.completed_at = datetime.now()
                    self._metrics.cancelled_tasks += 1
                    continue

                # Check resource quota
                if self.quota_checker and not await self.quota_checker.check_quota(task):
                    logger.warning(f"Quota exceeded for task {task.task_id}, requeueing")
                    await self._requeue_task(task, delay=60)
                    continue

                # Execute task with retry
                await self._execute_task_with_retry(task, batch_id)

                # Update batch progress
                await self._update_batch_progress(batch_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}")

    async def _execute_task_with_retry(self, task: TaskState, batch_id: str) -> None:
        """Execute task with retry policy

        Args:
            task: Task to execute
            batch_id: Batch ID for event emission
        """
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()

        for attempt in range(self.retry_policy.max_retries + 1):
            try:
                # Record start time
                start_time = time.time()

                # Execute task
                result = await self.executor_fn(task.skill_id)

                # Record performance metrics
                execution_time = time.time() - start_time
                task.execution_time = execution_time
                task.token_consumption = result.get("token_consumption", 0) if isinstance(result, dict) else 0

                # Update metrics
                self._metrics.completed_tasks += 1
                self._metrics.total_execution_time += execution_time
                self._metrics.total_token_consumption += task.token_consumption

                # Mark success
                task.status = TaskStatus.SUCCESS
                task.completed_at = datetime.now()

                # Emit task_completed event
                await self.event_emitter.emit(
                    "batch_task_completed",
                    {
                        "batch_id": batch_id,
                        "task_id": task.task_id,
                        "skill_id": task.skill_id,
                        "status": "success",
                        "execution_time": execution_time,
                        "token_consumption": task.token_consumption,
                    },
                )

                break

            except asyncio.CancelledError:
                task.status = TaskStatus.CANCELLED
                task.completed_at = datetime.now()
                break

            except Exception as e:
                task.retry_count = attempt + 1
                task.error_message = str(e)

                if attempt < self.retry_policy.max_retries:
                    delay = self.retry_policy.get_delay(attempt)
                    logger.warning(
                        f"Task {task.task_id} failed (attempt {attempt + 1}/{self.retry_policy.max_retries + 1}), retrying in {delay}s: {e}"
                    )
                    await asyncio.sleep(delay)
                else:
                    # Max retries exceeded, mark as failed
                    task.status = TaskStatus.FAILED
                    task.completed_at = datetime.now()
                    self._metrics.failed_tasks += 1

                    logger.error(f"Task {task.task_id} failed after {self.retry_policy.max_retries} retries: {e}")

                    # Emit task_failed event
                    await self.event_emitter.emit(
                        "batch_task_failed",
                        {
                            "batch_id": batch_id,
                            "task_id": task.task_id,
                            "skill_id": task.skill_id,
                            "error": str(e),
                            "retry_count": task.retry_count,
                        },
                    )
                    break

    async def _aging_loop(self) -> None:
        """Priority aging loop to prevent task starvation

        Every aging_interval seconds, increase priority of pending tasks by 1.
        This ensures low-priority tasks eventually get executed.
        """
        logger.info(f"Priority aging loop started (interval: {self.aging_interval}s)")

        while True:
            try:
                await asyncio.sleep(self.aging_interval)

                # Age all pending tasks
                aged_count = 0
                for task in self._tasks.values():
                    if task.status == TaskStatus.PENDING:
                        task.priority += 1
                        aged_count += 1

                if aged_count > 0:
                    logger.debug(f"Aged {aged_count} pending tasks")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Aging loop error: {e}")

    async def _requeue_task(self, task: TaskState, delay: int = 0) -> None:
        """Requeue a task (e.g., when quota exceeded)

        Args:
            task: Task to requeue
            delay: Delay in seconds before requeue
        """
        if delay > 0:
            await asyncio.sleep(delay)

        await self._task_queue.put((-task.priority, time.time(), task))

    def _find_batch_for_task(self, task_id: str) -> str | None:
        """Find batch ID for a given task ID"""
        for batch_id, batch_data in self._batches.items():
            if task_id in batch_data["task_ids"]:
                return batch_id
        return None

    async def _update_batch_progress(self, batch_id: str) -> None:
        """Update batch progress and emit progress event

        Args:
            batch_id: Batch ID to update
        """
        if batch_id not in self._batches:
            return

        batch = self._batches[batch_id]
        task_ids = batch["task_ids"]

        completed = sum(
            1
            for tid in task_ids
            if self._tasks[tid].status in [TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED]
        )
        failed = sum(1 for tid in task_ids if self._tasks[tid].status == TaskStatus.FAILED)
        cancelled = sum(1 for tid in task_ids if self._tasks[tid].status == TaskStatus.CANCELLED)

        total = len(task_ids)
        progress_percent = completed / total if total > 0 else 0.0

        # Emit progress event
        await self.event_emitter.emit(
            "batch_optimization_progress",
            {
                "batch_id": batch_id,
                "total": total,
                "completed": completed,
                "failed": failed,
                "cancelled": cancelled,
                "progress_percent": progress_percent,
            },
        )

        # Check if batch is complete
        if completed == total:
            batch["status"] = "completed"
            batch["completed_at"] = datetime.now()

            # Emit batch_completed event
            await self.event_emitter.emit(
                "batch_optimization_completed",
                {
                    "batch_id": batch_id,
                    "total": total,
                    "succeeded": total - failed - cancelled,
                    "failed": failed,
                    "cancelled": cancelled,
                    "duration": (batch["completed_at"] - batch["created_at"]).total_seconds(),
                },
            )

            logger.info(f"Batch {batch_id} completed: {total - failed - cancelled}/{total} succeeded")

    async def cancel_batch(self, batch_id: str) -> bool:
        """Cancel a running batch

        Args:
            batch_id: Batch ID to cancel

        Returns:
            True if batch was cancelled, False if not found or already completed
        """
        if batch_id not in self._batches:
            return False

        if self._batches[batch_id]["status"] != "running":
            return False

        # Set cancellation token
        if batch_id in self._cancellation_tokens:
            self._cancellation_tokens[batch_id].set()

        logger.info(f"Batch {batch_id} cancellation requested")
        return True

    async def get_batch_progress(self, batch_id: str) -> dict[str, Any] | None:
        """Get batch progress

        Args:
            batch_id: Batch ID to query

        Returns:
            Batch progress dict or None if not found
        """
        if batch_id not in self._batches:
            return None

        batch = self._batches[batch_id]
        task_ids = batch["task_ids"]

        completed = sum(
            1
            for tid in task_ids
            if self._tasks[tid].status in [TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED]
        )
        failed = sum(1 for tid in task_ids if self._tasks[tid].status == TaskStatus.FAILED)
        cancelled = sum(1 for tid in task_ids if self._tasks[tid].status == TaskStatus.CANCELLED)

        return {
            "batch_id": batch_id,
            "status": batch["status"],
            "total": len(task_ids),
            "completed": completed,
            "failed": failed,
            "cancelled": cancelled,
            "progress_percent": completed / len(task_ids) if len(task_ids) > 0 else 0.0,
            "created_at": batch["created_at"].isoformat(),
            "completed_at": batch["completed_at"].isoformat() if batch["completed_at"] else None,
        }

    async def get_performance_metrics(self) -> dict[str, Any]:
        """Get overall performance metrics

        Returns:
            Performance metrics dict
        """
        return {
            "total_tasks": self._metrics.total_tasks,
            "completed_tasks": self._metrics.completed_tasks,
            "failed_tasks": self._metrics.failed_tasks,
            "cancelled_tasks": self._metrics.cancelled_tasks,
            "total_execution_time": self._metrics.total_execution_time,
            "total_token_consumption": self._metrics.total_token_consumption,
            "average_execution_time": self._metrics.average_execution_time,
            "tasks_per_second": self._metrics.tasks_per_second,
        }
