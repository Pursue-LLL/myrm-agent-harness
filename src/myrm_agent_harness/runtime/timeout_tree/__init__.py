"""Hierarchical Context Timeout Tree and Cancel Propagation Suite.

Parent-child timeout trees, neural cascade cancellation propagation,
and zero-wild-task reaper guard for deterministic agent lifecycle control.

[INPUT]
- hierarchical_timeout_node
- timeout_tree_types
- zombie_task_reaper

[OUTPUT]
- (模块级副作用与注册)

[POS]
Hierarchical Context Timeout Tree and Cancel Propagation Suite.
"""

from .hierarchical_timeout_node import TimeoutTreeNode
from .timeout_tree_types import (
    CancelHookCallback,
    CancelReason,
    CascadeCancelSignal,
    TaskExecutionHandle,
    TimeoutLevel,
    ZombieReaperReport,
)
from .zombie_task_reaper import ZombieTaskReaper

__all__ = [
    "CancelHookCallback",
    "CancelReason",
    "CascadeCancelSignal",
    "TaskExecutionHandle",
    "TimeoutLevel",
    "TimeoutTreeNode",
    "ZombieReaperReport",
    "ZombieTaskReaper",
]
