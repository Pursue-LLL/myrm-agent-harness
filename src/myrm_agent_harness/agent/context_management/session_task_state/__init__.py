"""Session Task State & Anti-Compaction Task HUD Subpackage.

[INPUT]
- state_machine.py

[OUTPUT]
- TaskStatus, TaskItem, SessionTaskState, format_compaction_immune_task_hud

[POS]
Public facade of the compaction-immune session task state: task queue, status transitions and HUD formatting.
"""

from __future__ import annotations

from .state_machine import (
    SessionTaskState,
    TaskItem,
    TaskStatus,
    format_compaction_immune_task_hud,
)

__all__ = [
    "SessionTaskState",
    "TaskItem",
    "TaskStatus",
    "format_compaction_immune_task_hud",
]
