"""High-Concurrency Subagent Swarm and Adaptive Cloud Offload Package (Item 60).

[INPUT]
- types::{
    OffloadStrategy, ExecutionTarget, WorkerState, TaskPriority,
    ResourceWatermark, SwarmTaskDefinition, SwarmWorkerRecord, SwarmBatchSummary,
  }
- watermark_monitor::{ResourceWatermarkMonitor}
- offload_dispatcher::{SwarmOffloadDispatcher, default_worker_runner}

[OUTPUT]
- Public module exports for Item 60 swarm dispatch and host resource preservation.

[POS]
- Harness sub_agents subsystem entry for high-concurrency 10-15 agent scheduling.
"""

from __future__ import annotations

from .offload_dispatcher import SwarmOffloadDispatcher, default_worker_runner
from .types import (
    ExecutionTarget,
    OffloadStrategy,
    ResourceWatermark,
    SwarmBatchSummary,
    SwarmTaskDefinition,
    SwarmWorkerRecord,
    TaskPriority,
    WorkerState,
)
from .watermark_monitor import ResourceWatermarkMonitor

__all__ = [
    "ExecutionTarget",
    "OffloadStrategy",
    "ResourceWatermark",
    "ResourceWatermarkMonitor",
    "SwarmBatchSummary",
    "SwarmOffloadDispatcher",
    "SwarmTaskDefinition",
    "SwarmWorkerRecord",
    "TaskPriority",
    "WorkerState",
    "default_worker_runner",
]
