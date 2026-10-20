"""Skill history types.

[INPUT]
- dataclasses::dataclass (POS: Python dataclass decorator)
- datetime::datetime (POS: timestamp type)

[OUTPUT]
- SkillHistoryRecord: History record data class
- SkillRollbackResult: Rollback result data class

[POS]
Data structures for skill modification history tracking.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SkillHistoryRecord:
    """Skill history record (immutable).

    Records a single modification to a skill, including who made it,
    when, what changed, and business context (thread_id, etc.).
    """

    # Core action info
    action: str  # save/patch/delete/write_file/remove_file/rollback
    author: str  # agent/human
    timestamp: datetime

    # File info
    file_path: str
    prev_content: str | None
    new_content: str | None

    # Context info
    thread_id: str | None = None
    session_id: str | None = None
    request_id: str | None = None
    user_agent: str | None = None

    # Security info
    scanner: dict[str, str] | None = None

    # Additional metadata
    metadata: dict[str, str] | None = None


@dataclass(frozen=True)
class SkillRollbackResult:
    """Skill rollback result (immutable)."""

    success: bool
    skill_name: str = ""
    skill_id: str = ""
    rolled_back_to: datetime | None = None
    error: str = ""
