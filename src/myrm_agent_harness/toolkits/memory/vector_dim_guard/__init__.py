"""Vector index dimension guard and rebuild task suite module.

[INPUT]
- models.py, guard.py, orchestrator.py components.

[OUTPUT]
- VectorDimGuard, VectorRebuildOrchestrator, TaskLockConflictError, and domain models.

[POS]
- Facade package for Item 151 VectorDimGuardAndRebuildTaskSuite.
"""

from __future__ import annotations

from .guard import VectorDimGuard
from .models import (
    DimGuardResult,
    FailedItem,
    RebuildPhase,
    RebuildProgressEvent,
    RebuildTaskStatus,
)
from .orchestrator import TaskLockConflictError, VectorRebuildOrchestrator

__all__ = [
    "DimGuardResult",
    "FailedItem",
    "RebuildPhase",
    "RebuildProgressEvent",
    "RebuildTaskStatus",
    "TaskLockConflictError",
    "VectorDimGuard",
    "VectorRebuildOrchestrator",
]
