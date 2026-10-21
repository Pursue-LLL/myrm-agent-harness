"""Data types and schemas for Task Graph Critical Path Pruning and Early Exit Optimization Suite.

Defines task nodes, DAG execution waves, compilation metrics, and information
sufficiency early exit verdicts to minimize P95 response latencies.

[INPUT]
- __future__
- time
- dataclasses
- enum

[OUTPUT]
- TaskStatus
- TaskNode
- ExecutionWave
- DAGCompilationResult
- EarlyExitVerdict
- DAGExecutionMetrics

[POS]
Data types and schemas for Task Graph Critical Path Pruning and Early Exit Optimization Suite.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class TaskStatus(StrEnum):
    """Lifecycle status of a node in the task dependency graph."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED_DEPENDENCY_FAILED = "skipped_dependency_failed"


@dataclass
class TaskNode:
    """A single executable tool invocation node within a task graph."""

    task_id: str
    tool_name: str
    parameters: dict[str, str] = field(default_factory=dict)
    dependencies: tuple[str, ...] = field(default_factory=tuple)
    status: TaskStatus = TaskStatus.PENDING
    result: str = ""
    error_msg: str = ""
    duration_s: float = 0.0


@dataclass(frozen=True)
class ExecutionWave:
    """A parallel execution tier consisting of mutually independent task nodes."""

    wave_index: int
    task_ids: tuple[str, ...]


@dataclass(frozen=True)
class DAGCompilationResult:
    """Result of compiling a set of task nodes into topological parallel waves."""

    waves: tuple[ExecutionWave, ...]
    critical_path_length: int
    total_tasks: int
    has_cycle: bool


@dataclass(frozen=True)
class EarlyExitVerdict:
    """Decision indicating whether reasoning loop should terminate early."""

    should_exit: bool
    reason: str
    covered_aspects: tuple[str, ...]
    missing_aspects: tuple[str, ...]
    iteration_count: int
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class DAGExecutionMetrics:
    """Latency and compression metrics achieved via task graph parallel execution."""

    total_tasks_executed: int
    total_waves: int
    parallel_duration_s: float
    simulated_serial_duration_s: float
    latency_reduction_ratio: float
