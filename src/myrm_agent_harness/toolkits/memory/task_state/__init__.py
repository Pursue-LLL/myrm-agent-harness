"""Structured Task State Machine and Compaction Preservation Engine.

Provides authoritative multi-turn task tracking, step progress, checklist todos,
blocker logging, and guaranteed zero-loss structured state anchors through
rolling context compaction cycles.
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
