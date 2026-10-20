"""Persistent Kanban Job Queue and Massive Parallel Dogfooding Runner Suite.

[INPUT]
- batch_runner
- queue_manager
- types

[OUTPUT]
- (模块级副作用与注册)

[POS]
Persistent Kanban Job Queue and Massive Parallel Dogfooding Runner Suite.

"""

from .batch_runner import MassiveParallelBatchRunner
from .queue_manager import PersistentKanbanQueueManager
from .types import (
    BatchRunnerConfig,
    BlackboardEntry,
    JobPriority,
    KanbanComment,
    KanbanJob,
    KanbanJobStatus,
    SwarmTopologyStage,
    TrajectoryRecord,
)

__all__ = [
    "BatchRunnerConfig",
    "BlackboardEntry",
    "JobPriority",
    "KanbanComment",
    "KanbanJob",
    "KanbanJobStatus",
    "MassiveParallelBatchRunner",
    "PersistentKanbanQueueManager",
    "SwarmTopologyStage",
    "TrajectoryRecord",
]
