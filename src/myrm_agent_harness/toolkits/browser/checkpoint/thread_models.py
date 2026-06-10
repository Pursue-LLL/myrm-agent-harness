"""Thread Registry data models and SQL schemas.


[INPUT]
- datetime::datetime (POS: Timestamp tracking)
- typing::Literal (POS: Status type safety)

[OUTPUT]
- ThreadStatus: Type alias for thread status
- ThreadRecord: Dataclass for thread metadata
- SQLITE_THREAD_TABLE_SQL: SQLite table schema

[POS]
Thread Registry data models. Defines thread record structures and database table schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

ThreadStatus = Literal["active", "completed", "failed"]


@dataclass
class ThreadRecord:
    """Thread metadata record for task lifecycle tracking.

    Tracks essential lifecycle state for checkpoint threads to enable automatic recovery.
    Only includes fields actively used in production recovery logic.

    Fields:
        thread_id: Unique thread identifier
        status: Current thread status (active/completed/failed)
        created_at: Thread creation timestamp
        last_active_at: Last activity timestamp (for zombie detection)

    Note:
        Monitoring data (checkpoint_count, recovery_count, URLs) is available
        in LangGraph checkpoint metadata and should be queried from there.
    """

    thread_id: str
    status: ThreadStatus
    created_at: datetime
    last_active_at: datetime

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary for serialization."""
        return {
            "thread_id": self.thread_id,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "last_active_at": self.last_active_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ThreadRecord:
        """Create from dictionary."""
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif not isinstance(created_at, datetime):
            created_at = datetime.now()

        last_active_at = data.get("last_active_at")
        if isinstance(last_active_at, str):
            last_active_at = datetime.fromisoformat(last_active_at)
        elif not isinstance(last_active_at, datetime):
            last_active_at = datetime.now()

        return cls(
            thread_id=str(data["thread_id"]),
            status=str(data.get("status", "active")),  # type: ignore
            created_at=created_at,
            last_active_at=last_active_at,
        )


# SQL schemas for thread registry table
SQLITE_THREAD_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS checkpoint_threads (
    thread_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_active_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_threads_status ON checkpoint_threads(status);
CREATE INDEX IF NOT EXISTS idx_threads_last_active ON checkpoint_threads(last_active_at);
"""
