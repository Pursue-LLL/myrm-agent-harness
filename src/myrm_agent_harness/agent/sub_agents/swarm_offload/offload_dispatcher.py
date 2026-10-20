"""10-15 Concurrency Swarm Dispatcher with Transparent Cloud Sandbox Offload (Item 60).

[INPUT]
- List of SwarmTaskDefinition items (up to 15 concurrent tasks).
- ResourceWatermarkMonitor instance for host load-aware routing.
- Configurable OffloadStrategy (ADAPTIVE, FORCE_LOCAL, FORCE_CLOUD).
- Pluggable local/cloud worker runners for testing and runtime execution.

[OUTPUT]
- High-throughput parallel execution across local host and cloud sandboxes.
- SwarmBatchSummary containing metrics, offload ratios, and artifact pointers.

[POS]
- Core concurrency orchestration engine solving the physical laptop bottleneck (Item 60).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from .types import (
    ExecutionTarget,
    OffloadStrategy,
    SwarmBatchSummary,
    SwarmTaskDefinition,
    SwarmWorkerRecord,
    WorkerState,
)
from .watermark_monitor import ResourceWatermarkMonitor

logger = logging.getLogger(__name__)

# Type aliases for worker runners: receives (task, target) -> returns (exit_code, payload, artifact_ptr)
WorkerRunner = Callable[[SwarmTaskDefinition, ExecutionTarget], Awaitable[tuple[int, str, str | None]]]


async def default_worker_runner(
    task: SwarmTaskDefinition,
    target: ExecutionTarget,
) -> tuple[int, str, str | None]:
    """Default simulated worker runner with realistic micro-latency and artifact emission."""
    # Lightweight non-blocking sleep to simulate parallel worker computation
    await asyncio.sleep(0.01)
    if "fail" in task.command_or_prompt.lower():
        return (1, f"Task {task.task_id} failed simulated error", None)

    ptr = f"vault://artifacts/{task.task_id}/result.json" if target == ExecutionTarget.CLOUD_SANDBOX else None
    return (0, f"Executed {task.title} successfully on {target.value}", ptr)


class SwarmOffloadDispatcher:
    """Orchestrates 10-15 high-concurrency subagents with transparent cloud offloading."""

    def __init__(
        self,
        monitor: ResourceWatermarkMonitor | None = None,
        default_strategy: OffloadStrategy = OffloadStrategy.ADAPTIVE,
        max_concurrency: int = 15,
        worker_runner: WorkerRunner | None = None,
    ) -> None:
        self.monitor = monitor or ResourceWatermarkMonitor()
        self.strategy = default_strategy
        self.max_concurrency = max_concurrency
        self.runner = worker_runner or default_worker_runner
        self._semaphore = asyncio.Semaphore(max_concurrency)

    def set_strategy(self, strategy: OffloadStrategy) -> None:
        """Update current offloading strategy."""
        self.strategy = strategy

    def resolve_target(self, task: SwarmTaskDefinition) -> ExecutionTarget:
        """Resolve whether the task goes to local host or cloud sandbox."""
        if self.strategy == OffloadStrategy.FORCE_CLOUD:
            return ExecutionTarget.CLOUD_SANDBOX
        if self.strategy == OffloadStrategy.FORCE_LOCAL:
            return ExecutionTarget.LOCAL_HOST

        # Adaptive strategy: evaluate host watermark and task preference
        return self.monitor.evaluate_target(task.preferred_target)

    async def _execute_single_worker(
        self,
        task: SwarmTaskDefinition,
    ) -> SwarmWorkerRecord:
        """Execute a single worker within semaphore constraints and safety guards."""
        target = self.resolve_target(task)
        worker_id = f"worker-{uuid.uuid4().hex[:8]}"
        record = SwarmWorkerRecord(
            worker_id=worker_id,
            task_id=task.task_id,
            execution_target=target,
            state=WorkerState.RUNNING,
            started_at=time.time(),
        )

        is_local = target == ExecutionTarget.LOCAL_HOST
        if is_local:
            self.monitor.register_local_worker_start()

        start_time = time.perf_counter()
        async with self._semaphore:
            try:
                # Wrap with task timeout
                exit_code, payload, ptr = await asyncio.wait_for(
                    self.runner(task, target),
                    timeout=task.timeout_seconds,
                )
                duration_ms = (time.perf_counter() - start_time) * 1000.0

                record.finished_at = time.time()
                record.duration_ms = round(duration_ms, 2)
                record.exit_code = exit_code
                record.result_payload = payload
                record.artifact_pointer = ptr

                if exit_code == 0:
                    record.state = WorkerState.COMPLETED
                else:
                    record.state = WorkerState.FAILED
                    record.error = payload

            except TimeoutError:
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                record.finished_at = time.time()
                record.duration_ms = round(duration_ms, 2)
                record.state = WorkerState.TIMED_OUT
                record.exit_code = 124
                record.error = f"Worker timed out after {task.timeout_seconds}s"

            except Exception as exc:
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                record.finished_at = time.time()
                record.duration_ms = round(duration_ms, 2)
                record.state = WorkerState.FAILED
                record.exit_code = 1
                record.error = str(exc)

            finally:
                if is_local:
                    self.monitor.register_local_worker_finish()

        return record

    async def dispatch_swarm_batch(
        self,
        tasks: list[SwarmTaskDefinition],
        batch_id: str | None = None,
    ) -> SwarmBatchSummary:
        """Dispatch 10-15 subagents concurrently and collect aggregated summary."""
        bid = batch_id or f"swarm-batch-{uuid.uuid4().hex[:8]}"
        self.monitor.reset_peaks()

        logger.info(
            "Dispatching swarm batch %s with %d tasks (Strategy: %s, MaxConcurrency: %d)",
            bid,
            len(tasks),
            self.strategy.value,
            self.max_concurrency,
        )

        # Launch all tasks concurrently
        worker_coros = [self._execute_single_worker(t) for t in tasks]
        worker_records = await asyncio.gather(*worker_coros)

        # Aggregate metrics
        local_count = sum(1 for r in worker_records if r.execution_target == ExecutionTarget.LOCAL_HOST)
        cloud_count = sum(1 for r in worker_records if r.execution_target == ExecutionTarget.CLOUD_SANDBOX)
        completed_count = sum(1 for r in worker_records if r.state == WorkerState.COMPLETED)
        failed_count = sum(1 for r in worker_records if r.state in (WorkerState.FAILED, WorkerState.TIMED_OUT))

        total_duration = sum(r.duration_ms for r in worker_records)
        avg_duration = round(total_duration / len(worker_records), 2) if worker_records else 0.0
        peak_cpu, peak_mem = self.monitor.get_peak_usage()

        return SwarmBatchSummary(
            batch_id=bid,
            total_tasks=len(tasks),
            local_workers_count=local_count,
            cloud_workers_count=cloud_count,
            completed_count=completed_count,
            failed_count=failed_count,
            avg_duration_ms=avg_duration,
            peak_cpu_percent=peak_cpu,
            peak_memory_percent=peak_mem,
            offload_strategy=self.strategy,
            workers=list(worker_records),
        )
