"""Parallel DAG executor with tiered wave concurrency and failure short-circuiting.

Executes topologically independent tasks within the same wave concurrently via asyncio,
dramatically compressing end-to-end P95 response times.

[INPUT]
- __future__
- asyncio
- time
- collections
- dag_dependency_compiler
- task_graph_types

[OUTPUT]
- ToolRunnerCallable
- ParallelDAGExecutor

[POS]
Parallel DAG executor with tiered wave concurrency and failure short-circuiting.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Coroutine

from .dag_dependency_compiler import DAGDependencyCompiler
from .task_graph_types import (
    DAGExecutionMetrics,
    TaskNode,
    TaskStatus,
)

ToolRunnerCallable = Callable[[str, dict[str, str]], Coroutine[object, object, str] | str]


class ParallelDAGExecutor:
    """Dispatches compiled task graph waves concurrently with dependency state propagation."""

    def __init__(self, tool_runner: ToolRunnerCallable) -> None:
        self.tool_runner = tool_runner

    async def execute_graph(self, tasks: list[TaskNode]) -> DAGExecutionMetrics:
        """Topologically compile and execute tasks across parallel execution waves."""
        if not tasks:
            return DAGExecutionMetrics(
                total_tasks_executed=0,
                total_waves=0,
                parallel_duration_s=0.0,
                simulated_serial_duration_s=0.0,
                latency_reduction_ratio=0.0,
            )

        task_map: dict[str, TaskNode] = {t.task_id: t for t in tasks}
        compilation = DAGDependencyCompiler.compile_waves(tasks)

        start_wall_time = time.time()
        simulated_serial_time = 0.0

        for wave in compilation.waves:
            # Prepare parallel coroutines for all tasks in this wave
            coroutines: list[Coroutine[object, object, None]] = []
            for tid in wave.task_ids:
                node = task_map[tid]
                coroutines.append(self._execute_single_node(node, task_map))

            # Concurrently execute all independent tasks in the wave
            await asyncio.gather(*coroutines, return_exceptions=True)

        end_wall_time = time.time()
        parallel_wall_time = max(0.001, end_wall_time - start_wall_time)

        for t in tasks:
            simulated_serial_time += t.duration_s

        reduction_ratio = round(
            max(0.0, (simulated_serial_time - parallel_wall_time) / max(0.001, simulated_serial_time) * 100.0),
            1,
        )

        return DAGExecutionMetrics(
            total_tasks_executed=len(tasks),
            total_waves=len(compilation.waves),
            parallel_duration_s=round(parallel_wall_time, 4),
            simulated_serial_duration_s=round(simulated_serial_time, 4),
            latency_reduction_ratio=reduction_ratio,
        )

    async def _execute_single_node(
        self,
        node: TaskNode,
        task_map: dict[str, TaskNode],
    ) -> None:
        """Execute a single task node, verifying dependency health before dispatch."""
        # 1. Dependency Health Check: If any dependency failed, short-circuit
        for dep_id in node.dependencies:
            dep_node = task_map.get(dep_id)
            if dep_node is None or dep_node.status != TaskStatus.COMPLETED:
                node.status = TaskStatus.SKIPPED_DEPENDENCY_FAILED
                node.error_msg = f"Skipped: dependency '{dep_id}' was not completed successfully."
                return

        node.status = TaskStatus.RUNNING
        t0 = time.time()

        try:
            res = self.tool_runner(node.tool_name, node.parameters)
            if asyncio.iscoroutine(res):
                val = await res
            else:
                val = str(res)

            node.result = str(val)
            node.status = TaskStatus.COMPLETED
        except Exception as exc:
            node.error_msg = str(exc)
            node.status = TaskStatus.FAILED
        finally:
            node.duration_s = max(0.0001, time.time() - t0)
