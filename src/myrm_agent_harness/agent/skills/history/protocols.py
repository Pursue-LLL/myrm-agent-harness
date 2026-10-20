"""Skill history backend protocol.

[INPUT]
- typing::Protocol, runtime_checkable (POS: Python protocol for duck typing)
- .types::SkillHistoryRecord (POS: History record type)

[OUTPUT]
- SkillHistoryBackend: Protocol for history storage backends

[POS]
Protocol for skill history storage. Allows different storage backends
(JSONL, database, S3, etc.) without modifying the HistoryTrackingSkillWriteBackend.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .types import SkillHistoryRecord


@runtime_checkable
class SkillHistoryBackend(Protocol):
    """Protocol for skill history storage backend.

    Abstracts history persistence:
    - JsonlHistoryBackend: File-based storage (default)
    - DatabaseHistoryBackend: SQL/NoSQL database storage
    """

    async def append_history(
        self,
        skill_name: str,
        record: SkillHistoryRecord,
    ) -> None:
        """Append a new history record.

        Args:
            skill_name: Skill name
            record: History record to append
        """
        ...

    async def list_history(
        self,
        skill_name: str,
        limit: int = 100,
    ) -> list[SkillHistoryRecord]:
        """List skill modification history.

        Returns records in reverse chronological order (newest first).

        Args:
            skill_name: Skill name
            limit: Max records to return (default 100)

        Returns:
            List of history records (newest first)
        """
        ...

    async def get_history_count(
        self,
        skill_name: str,
    ) -> int:
        """Get total count of history records.

        Args:
            skill_name: Skill name

        Returns:
            Total number of history records
        """
        ...
