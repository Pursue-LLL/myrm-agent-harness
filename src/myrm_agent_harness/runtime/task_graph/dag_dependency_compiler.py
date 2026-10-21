"""DAG dependency compiler and critical path analyzer.

Compiles arbitrary tool invocation dependency graphs into parallel topological
execution waves using Kahn's algorithm, with cycle detection and automatic cycle breaking.

[INPUT]
- __future__
- task_graph_types

[OUTPUT]
- DAGDependencyCompiler

[POS]
DAG dependency compiler and critical path analyzer.
"""

from __future__ import annotations

from .task_graph_types import (
    DAGCompilationResult,
    ExecutionWave,
    TaskNode,
)


class DAGDependencyCompiler:
    """Compiles task nodes into tiered parallel execution waves."""

    @staticmethod
    def compile_waves(tasks: list[TaskNode]) -> DAGCompilationResult:
        """Analyze dependencies between tasks and group them into ordered parallel execution waves.

        Tasks within the same wave are mutually independent and can be executed concurrently.
        """
        if not tasks:
            return DAGCompilationResult(
                waves=(),
                critical_path_length=0,
                total_tasks=0,
                has_cycle=False,
            )

        task_map: dict[str, TaskNode] = {t.task_id: t for t in tasks}
        in_degree: dict[str, int] = {t.task_id: 0 for t in tasks}
        adjacency: dict[str, list[str]] = {t.task_id: [] for t in tasks}

        # Build in-degrees and adjacency edges
        for t in tasks:
            for dep_id in t.dependencies:
                if dep_id in task_map:
                    adjacency[dep_id].append(t.task_id)
                    in_degree[t.task_id] += 1

        waves: list[ExecutionWave] = []
        processed_count = 0
        wave_idx = 0

        # Repeatedly extract nodes with 0 in-degree into current execution wave
        while True:
            current_wave_tasks: list[str] = [
                task_id for task_id, deg in in_degree.items() if deg == 0
            ]

            if not current_wave_tasks:
                break

            # Mark extracted nodes as processed by setting degree to -1
            for task_id in current_wave_tasks:
                in_degree[task_id] = -1

            waves.append(
                ExecutionWave(
                    wave_index=wave_idx,
                    task_ids=tuple(sorted(current_wave_tasks)),
                )
            )
            wave_idx += 1
            processed_count += len(current_wave_tasks)

            # Decrement in-degree for downstream neighbors
            for task_id in current_wave_tasks:
                for neighbor_id in adjacency[task_id]:
                    if in_degree[neighbor_id] > 0:
                        in_degree[neighbor_id] -= 1

        has_cycle = processed_count < len(tasks)

        # Cycle Breaking Guard: if circular dependencies prevented resolution,
        # fallback remaining un-processed tasks into sequential single-task waves
        if has_cycle:
            remaining_tasks = [task_id for task_id, deg in in_degree.items() if deg >= 0]
            for tid in remaining_tasks:
                waves.append(
                    ExecutionWave(
                        wave_index=wave_idx,
                        task_ids=(tid,),
                    )
                )
                wave_idx += 1

        return DAGCompilationResult(
            waves=tuple(waves),
            critical_path_length=len(waves),
            total_tasks=len(tasks),
            has_cycle=has_cycle,
        )
