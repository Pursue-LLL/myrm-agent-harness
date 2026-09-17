"""Data models and types for the Local Working Memory Block subsystem.

Provides structured, type-safe representations for runtime in-memory goals,
subtasks, execution scratchpad entries, and transient error-avoidance traps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal


class SubtaskStatus(StrEnum):
    """Execution lifecycle status of an individual subtask."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(slots=True)
class SubtaskItem:
    """Individual subtask entry tracked in the working block."""

    id: str
    title: str
    status: SubtaskStatus = SubtaskStatus.PENDING
    notes: str = ""


@dataclass(slots=True)
class TrapRecord:
    """Transient failure-site trap to prevent immediate error recurrence."""

    fingerprint: str
    avoidance_rule: str
    tool_name: str | None = None
    occurred_turn: int = 0


@dataclass(slots=True)
class LocalWorkingState:
    """Aggregated snapshot of the active working memory block.

    Maintains the top-level goal, active subtasks breakdown, transient error
    traps, and lightweight key-value scratchpad for the current agent run.
    """

    goal: str = ""
    status: Literal["active", "interrupted", "completed", "failed"] = "active"
    subtasks: list[SubtaskItem] = field(default_factory=list)
    traps: list[TrapRecord] = field(default_factory=list)
    scratchpad: dict[str, str] = field(default_factory=dict)
    active_turn: int = 0
