"""Core types and data contracts for High-Concurrency Swarm & Adaptive Cloud Offload (Item 60).

[INPUT]
- Pure domain data definitions, dataclasses, and enums.

[OUTPUT]
- OffloadStrategy, ExecutionTarget, WorkerState, TaskPriority,
  ResourceWatermark, SwarmTaskDefinition, SwarmWorkerRecord, SwarmBatchSummary.

[POS]
- Harness foundation for Item 60 10-15 concurrency subagent swarm scheduling
  and host physical resource preservation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class OffloadStrategy(StrEnum):
    """Strategy controlling local vs cloud sandbox offloading."""

    ADAPTIVE = "adaptive"  # Automatically offload when host resource watermark exceeded
    FORCE_LOCAL = "force_local"  # Never offload to cloud (run on local host only)
    FORCE_CLOUD = "force_cloud"  # Force all subagent workers to cloud sandboxes


class ExecutionTarget(StrEnum):
    """Where a swarm subagent worker executes."""

    LOCAL_HOST = "local_host"
    CLOUD_SANDBOX = "cloud_sandbox"


class WorkerState(StrEnum):
    """Lifecycle state of a swarm worker."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class TaskPriority(StrEnum):
    """Priority level for queued swarm tasks."""

    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"



@dataclass(slots=True)
class ResourceWatermark:
    """Snapshot of host physical resource utilization and offload recommendation."""

    cpu_percent: float
    memory_percent: float
    active_local_workers: int
    max_recommended_local_workers: int = 4
    cpu_threshold_percent: float = 80.0
    memory_threshold_percent: float = 80.0
    timestamp: float = field(default_factory=time.time)

    @property
    def is_over_watermark(self) -> bool:
        """Return True if local host is under excessive pressure."""
        return (
            self.cpu_percent >= self.cpu_threshold_percent
            or self.memory_percent >= self.memory_threshold_percent
            or self.active_local_workers >= self.max_recommended_local_workers
        )

    @property
    def recommendation(self) -> ExecutionTarget:
        """Recommended target for next worker."""
        if self.is_over_watermark:
            return ExecutionTarget.CLOUD_SANDBOX
        return ExecutionTarget.LOCAL_HOST


@dataclass(slots=True)
class SwarmTaskDefinition:
    """Definition of an individual task within a high-concurrency swarm."""

    task_id: str
    title: str
    command_or_prompt: str
    priority: TaskPriority = TaskPriority.NORMAL
    weight: float = 1.0
    timeout_seconds: float = 30.0
    preferred_target: ExecutionTarget | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class SwarmWorkerRecord:
    """Execution record for an individual swarm subagent worker."""

    worker_id: str
    task_id: str
    execution_target: ExecutionTarget
    state: WorkerState
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    duration_ms: float = 0.0
    exit_code: int = 0
    result_payload: str = ""
    artifact_pointer: str | None = None
    error: str | None = None


@dataclass(slots=True)
class SwarmBatchSummary:
    """Aggregated outcome of a high-concurrency swarm dispatch batch."""

    batch_id: str
    total_tasks: int
    local_workers_count: int
    cloud_workers_count: int
    completed_count: int
    failed_count: int
    avg_duration_ms: float
    peak_cpu_percent: float
    peak_memory_percent: float
    offload_strategy: OffloadStrategy
    workers: list[SwarmWorkerRecord] = field(default_factory=list)
