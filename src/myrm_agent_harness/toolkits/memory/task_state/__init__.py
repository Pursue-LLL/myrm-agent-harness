"""Structured Task State Machine and Compaction Preservation Engine.

Provides authoritative multi-turn task tracking, step progress, checklist todos,
blocker logging, and guaranteed zero-loss structured state anchors through
rolling context compaction cycles.

[INPUT]
- toolkits.memory.task_state.guard::CompactionStatePreservationGuard (POS: Compaction State Preservation
  Guard enforcing zero-loss task state retention.)
- toolkits.memory.task_state.models::CompactionAnchorPayload, StructuredTaskState, TaskStepItem,
  TaskStepStatus, TaskTodoItem (POS: Data models for Structured Task State Machine and Compaction
  Preservation.)
- toolkits.memory.task_state.tracker::StructuredTaskStateTracker (POS: Structured Task State Machine Tracker
  preserving task goals, steps, and todos.)

[OUTPUT]
- Package facade re-exporting 7 public names: CompactionAnchorPayload, CompactionStatePreservationGuard,
  StructuredTaskState, StructuredTaskStateTracker, TaskStepItem, TaskStepStatus, TaskTodoItem

[POS]
Structured Task State Machine and Compaction Preservation Engine.
"""

from .guard import CompactionStatePreservationGuard
from .models import (
    CompactionAnchorPayload,
    StructuredTaskState,
    TaskStepItem,
    TaskStepStatus,
    TaskTodoItem,
)
from .tracker import StructuredTaskStateTracker

__all__ = [
    "CompactionAnchorPayload",
    "CompactionStatePreservationGuard",
    "StructuredTaskState",
    "StructuredTaskStateTracker",
    "TaskStepItem",
    "TaskStepStatus",
    "TaskTodoItem",
]
