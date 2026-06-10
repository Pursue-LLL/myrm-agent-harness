"""Thread Registry storage layer for checkpoint task tracking.

Maintains registry of active threads to enable automatic recovery of incomplete tasks.


[INPUT]
- aiosqlite::Connection (POS: Database connection for thread storage)
- .thread_models::ThreadRecord, SQLITE_THREAD_TABLE_SQL (POS: Data models and schemas)

[OUTPUT]
- ThreadStore: Storage layer for checkpoint_threads table
- create_thread_tables: SQL table creation for SQLite

[POS]
Thread Registry storage layer. Operates on checkpoint_threads table, providing thread
registration, activity updates, queries, and deletion. Acts as a Task Registry tracking
thread lifecycle state for auto-recovery on startup.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from .thread_models import (
    SQLITE_THREAD_TABLE_SQL,
    ThreadRecord,
    ThreadStatus,
)

if TYPE_CHECKING:
    import aiosqlite

logger = logging.getLogger(__name__)


class ThreadStore:
    """Storage layer for checkpoint thread registry (SQLite, single sandbox instance)."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        logger.info("ThreadStore: initialized (backend=sqlite)")

    async def setup(self) -> None:
        """Create checkpoint_threads table if not exists."""
        await self._conn.executescript(SQLITE_THREAD_TABLE_SQL)
        await self._conn.commit()
        logger.info("ThreadStore: checkpoint_threads table ready")

    async def register(self, thread_id: str) -> None:
        """Register a new active thread."""
        now_str = datetime.now().isoformat()
        await self._conn.execute(
            """
            INSERT INTO checkpoint_threads
            (thread_id, status, created_at, last_active_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
                status = 'active',
                last_active_at = excluded.last_active_at
            """,
            (thread_id, "active", now_str, now_str),
        )
        await self._conn.commit()
        logger.debug("ThreadRegistry: registered (thread_id=%s)", thread_id)

    async def update_activity(self, thread_id: str) -> None:
        """Update thread activity timestamp."""
        now_str = datetime.now().isoformat()
        await self._conn.execute(
            "UPDATE checkpoint_threads SET last_active_at = ? WHERE thread_id = ?",
            (now_str, thread_id),
        )
        await self._conn.commit()

    async def mark_completed(self, thread_id: str) -> None:
        """Mark thread as completed."""
        await self._update_status(thread_id, "completed")
        logger.debug("ThreadRegistry: marked completed (thread_id=%s)", thread_id)

    async def mark_failed(self, thread_id: str) -> None:
        """Mark thread as failed."""
        await self._update_status(thread_id, "failed")
        logger.debug("ThreadRegistry: marked failed (thread_id=%s)", thread_id)

    async def _update_status(self, thread_id: str, status: ThreadStatus) -> None:
        await self._conn.execute(
            "UPDATE checkpoint_threads SET status = ? WHERE thread_id = ?",
            (status, thread_id),
        )
        await self._conn.commit()

    async def find_active_threads(self, max_age_hours: float | None = None) -> list[ThreadRecord]:
        """Find all active threads."""
        if max_age_hours is not None:
            cutoff_time = (datetime.now() - timedelta(hours=max_age_hours)).isoformat()
            cursor = await self._conn.execute(
                """
                SELECT thread_id, status, created_at, last_active_at
                FROM checkpoint_threads
                WHERE status = 'active' AND last_active_at >= ?
                ORDER BY last_active_at DESC
                """,
                (cutoff_time,),
            )
        else:
            cursor = await self._conn.execute(
                """
                SELECT thread_id, status, created_at, last_active_at
                FROM checkpoint_threads
                WHERE status = 'active'
                ORDER BY last_active_at DESC
                """
            )

        rows = await cursor.fetchall()
        return [self._row_to_record(row) for row in rows]

    def _row_to_record(self, row: tuple[object, ...]) -> ThreadRecord:
        thread_id, status, created_at, last_active_at = row

        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        if isinstance(last_active_at, str):
            last_active_at = datetime.fromisoformat(last_active_at)

        return ThreadRecord(
            thread_id=str(thread_id),
            status=str(status),  # type: ignore[arg-type]
            created_at=created_at,  # type: ignore[arg-type]
            last_active_at=last_active_at,  # type: ignore[arg-type]
        )

    async def delete(self, thread_id: str) -> bool:
        """Delete thread record."""
        cursor = await self._conn.execute(
            "DELETE FROM checkpoint_threads WHERE thread_id = ?",
            (thread_id,),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def cleanup_old_records(self, *, max_age_days: float = 7.0) -> int:
        """Clean up old completed/failed thread records to prevent table bloat."""
        cutoff_str = (datetime.now() - timedelta(days=max_age_days)).isoformat()
        cursor = await self._conn.execute(
            """
            DELETE FROM checkpoint_threads
            WHERE last_active_at < ? AND status != 'active'
            """,
            (cutoff_str,),
        )
        await self._conn.commit()
        deleted = cursor.rowcount

        if deleted > 0:
            logger.info("ThreadStore: cleaned up %d old records (cutoff=%s)", deleted, cutoff_str)

        return deleted

    async def get(self, thread_id: str) -> ThreadRecord | None:
        """Get thread record by ID."""
        cursor = await self._conn.execute(
            """
            SELECT thread_id, status, created_at, last_active_at
            FROM checkpoint_threads
            WHERE thread_id = ?
            """,
            (thread_id,),
        )
        row = await cursor.fetchone()
        return self._row_to_record(row) if row else None


async def create_thread_tables(conn: aiosqlite.Connection) -> None:
    """Create checkpoint_threads table."""
    await conn.executescript(SQLITE_THREAD_TABLE_SQL)
    await conn.commit()
    logger.info("ThreadStore: table created (backend=sqlite)")
