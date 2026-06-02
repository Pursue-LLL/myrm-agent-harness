"""File activity tracker for concurrent subagent conflict detection.

Maintains a per-file activity log recording which agent modified which lines.
Provides line-level overlap detection so the conflict validator can distinguish
between dangerous overlapping edits and safe non-overlapping parallel edits.

[INPUT]
- agent.middlewares._session_context::get_subagent_task_id (POS: ContextVar for subagent task ID)

[OUTPUT]
- FileActivityTracker: Singleton tracker for file write activities
- FileAccess: Dataclass recording a single file write access
- ConflictResult: Dataclass describing a detected conflict
- ConflictLevel: Enum for conflict severity
- get_file_activity_tracker: Module-level singleton accessor

[POS]
File activity tracker. Tracks which agent modified which files and line ranges,
enabling line-level conflict detection for concurrent subagent operations.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from enum import StrEnum


class ConflictLevel(StrEnum):
    """Severity of a file conflict between concurrent agents."""

    OVERLAPPING = "overlapping"
    SAME_FILE_NON_OVERLAPPING = "same_file_non_overlapping"


@dataclass(frozen=True, slots=True)
class FileAccess:
    """Records a single file write access by an agent."""

    agent_id: str
    line_start: int
    line_end: int
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class ConflictResult:
    """Describes a detected conflict between two agents editing the same file."""

    level: ConflictLevel
    conflicting_agent_id: str
    conflicting_lines: tuple[int, int]
    your_lines: tuple[int, int]
    seconds_ago: float

    @property
    def is_blocking(self) -> bool:
        return self.level == ConflictLevel.OVERLAPPING

    def to_message(self, path: str) -> str:
        ago = int(self.seconds_ago)
        if self.level == ConflictLevel.OVERLAPPING:
            return (
                f"File conflict: {path} lines {self.your_lines[0]}-{self.your_lines[1]} "
                f"overlap with lines {self.conflicting_lines[0]}-{self.conflicting_lines[1]} "
                f"modified by {self.conflicting_agent_id} {ago}s ago. "
                f"Read the latest version with file_read before editing."
            )
        return (
            f"File notice: {path} was also modified by {self.conflicting_agent_id} {ago}s ago "
            f"(lines {self.conflicting_lines[0]}-{self.conflicting_lines[1]}, non-overlapping with your "
            f"lines {self.your_lines[0]}-{self.your_lines[1]}). Proceeding safely."
        )


class FileActivityTracker:
    """Tracks file write activities across concurrent agents.

    Process-internal singleton. All subagents sharing the same Python process
    register their writes here, enabling pre-write conflict checks.
    """

    __slots__ = ("_activities",)

    def __init__(self) -> None:
        # {normalized_path: [FileAccess, ...]}
        self._activities: dict[str, list[FileAccess]] = {}

    def record_write(self, agent_id: str, path: str, line_start: int, line_end: int) -> None:
        """Record a completed write operation."""
        norm = os.path.normpath(path)
        access = FileAccess(agent_id=agent_id, line_start=line_start, line_end=line_end)
        self._activities.setdefault(norm, []).append(access)

    def check_conflict(
        self, agent_id: str, path: str, line_start: int, line_end: int
    ) -> ConflictResult | None:
        """Check if the proposed write conflicts with recent activity by other agents.

        Returns the most severe conflict found, or None if safe.
        """
        norm = os.path.normpath(path)
        accesses = self._activities.get(norm)
        if not accesses:
            return None

        now = time.time()
        worst: ConflictResult | None = None

        for access in accesses:
            if access.agent_id == agent_id:
                continue

            seconds_ago = now - access.timestamp

            if access.line_start <= line_end and line_start <= access.line_end:
                conflict = ConflictResult(
                    level=ConflictLevel.OVERLAPPING,
                    conflicting_agent_id=access.agent_id,
                    conflicting_lines=(access.line_start, access.line_end),
                    your_lines=(line_start, line_end),
                    seconds_ago=seconds_ago,
                )
                return conflict

            if worst is None or worst.level != ConflictLevel.OVERLAPPING:
                worst = ConflictResult(
                    level=ConflictLevel.SAME_FILE_NON_OVERLAPPING,
                    conflicting_agent_id=access.agent_id,
                    conflicting_lines=(access.line_start, access.line_end),
                    your_lines=(line_start, line_end),
                    seconds_ago=seconds_ago,
                )

        return worst

    def clear_agent(self, agent_id: str) -> None:
        """Remove all activity records for a specific agent (cleanup on task completion)."""
        for path in list(self._activities):
            self._activities[path] = [a for a in self._activities[path] if a.agent_id != agent_id]
            if not self._activities[path]:
                del self._activities[path]

    def clear(self) -> None:
        """Clear all activity records."""
        self._activities.clear()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_tracker: FileActivityTracker | None = None


def get_file_activity_tracker() -> FileActivityTracker:
    """Get the process-wide FileActivityTracker singleton."""
    global _tracker
    if _tracker is None:
        _tracker = FileActivityTracker()
    return _tracker
