"""Thread Registry storage layer for checkpoint task tracking.

Maintains registry of active threads to enable automatic recovery of incomplete tasks.


[INPUT]
- aiosqlite::Connection | asyncpg::Pool (POS: Database connection for thread storage)
- .thread_models::ThreadRecord, SQLITE_THREAD_TABLE_SQL, POSTGRES_THREAD_TABLE_SQL (POS: Data models and schemas)

[OUTPUT]
- ThreadStore: Storage layer for checkpoint_threads table
- create_thread_tables: SQL table creation for SQLite/PostgreSQL

[POS]
Thread Registry storage layer. Operates on checkpoint_threads table, providing thread
registration, activity updates, queries, and deletion. Acts as a Task Registry tracking
thread lifecycle state for auto-recovery on startup. Supports SQLite (single) and PostgreSQL (multi) backends.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from .thread_models import (
    POSTGRES_THREAD_TABLE_SQL,
    SQLITE_THREAD_TABLE_SQL,
    ThreadRecord,
    ThreadStatus,
)

if TYPE_CHECKING:
    import aiosqlite
    import asyncpg

logger = logging.getLogger(__name__)


class ThreadStore:
    """Storage layer for checkpoint thread registry.

    Task Registry for tracking thread lifecycle state. Enables automatic recovery
    of incomplete tasks on application startup.

    Thread lifecycle:
    1. register() -> creates entry with status="active"
    2. update_activity() -> updates last_active_at timestamp
    3. mark_completed() / mark_failed() -> sets final status
    4. find_active_threads() -> returns threads with status="active"

    Design rationale:
    - Minimal fields: only essential lifecycle state (thread_id, status, timestamps)
    - Separate from LangGraph checkpoints (zero coupling)
    - Status-based query with efficient index scan
    - Timestamp-based zombie detection (48h cutoff)
    - Monitoring data (URLs, counters) stored in LangGraph checkpoint metadata

    Supports both SQLite (single-instance) and PostgreSQL (multi-instance).
    """

    def __init__(
        self,
        conn: aiosqlite.Connection | asyncpg.Pool,
        backend: Literal["sqlite", "postgres"] = "sqlite",
    ) -> None:
        """Initialize thread store.

        Args:
            conn: Database connection (sqlite.Connection or asyncpg.Pool)
            backend: Database backend type
        """
        self._conn = conn
        self._backend = backend
        logger.info(f"ThreadStore: initialized (backend={backend})")

    async def setup(self) -> None:
        """Create checkpoint_threads table if not exists."""
        sql = SQLITE_THREAD_TABLE_SQL if self._backend == "sqlite" else POSTGRES_THREAD_TABLE_SQL

        if self._backend == "sqlite":
            conn: aiosqlite.Connection = self._conn  # type: ignore
            await conn.executescript(sql)
            await conn.commit()
        else:
            pool: asyncpg.Pool = self._conn  # type: ignore
            async with pool.acquire() as conn:
                await conn.execute(sql)

        logger.info("ThreadStore: checkpoint_threads table ready")

    async def register(self, thread_id: str) -> None:
        """Register a new active thread.

        Args:
            thread_id: Thread identifier
        """
        await self._do_register(thread_id)

    async def _do_register(self, thread_id: str) -> None:
        """Internal implementation of register."""
        now = datetime.now()
        now_str = now.isoformat()

        if self._backend == "sqlite":
            conn: aiosqlite.Connection = self._conn  # type: ignore
            await conn.execute(
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
            await conn.commit()
        else:
            pool: asyncpg.Pool = self._conn  # type: ignore
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO checkpoint_threads
                    (thread_id, status, created_at, last_active_at)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT(thread_id) DO UPDATE SET
                        status = 'active',
                        last_active_at = EXCLUDED.last_active_at
                    """,
                    thread_id,
                    "active",
                    now,
                    now,
                )

        logger.debug(f"ThreadRegistry: registered (thread_id={thread_id})")

    async def update_activity(self, thread_id: str) -> None:
        """Update thread activity timestamp.

        Updates last_active_at to current time, used for zombie detection (48h cutoff).

        Args:
            thread_id: Thread identifier
        """
        await self._do_update_activity(thread_id)

    async def _do_update_activity(self, thread_id: str) -> None:
        """Internal implementation of update_activity."""
        now = datetime.now()
        now_str = now.isoformat()

        if self._backend == "sqlite":
            conn: aiosqlite.Connection = self._conn  # type: ignore
            await conn.execute(
                "UPDATE checkpoint_threads SET last_active_at = ? WHERE thread_id = ?",
                (now_str, thread_id),
            )
            await conn.commit()
        else:
            pool: asyncpg.Pool = self._conn  # type: ignore
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE checkpoint_threads SET last_active_at = $1 WHERE thread_id = $2",
                    now,
                    thread_id,
                )

    async def mark_completed(self, thread_id: str) -> None:
        """Mark thread as completed.

        Args:
            thread_id: Thread identifier
        """
        await self._update_status(thread_id, "completed")
        logger.debug(f"ThreadRegistry: marked completed (thread_id={thread_id})")

    async def mark_failed(self, thread_id: str) -> None:
        """Mark thread as failed.

        Args:
            thread_id: Thread identifier
        """
        await self._update_status(thread_id, "failed")
        logger.debug(f"ThreadRegistry: marked failed (thread_id={thread_id})")

    async def _update_status(self, thread_id: str, status: ThreadStatus) -> None:
        """Update thread status.

        Args:
            thread_id: Thread identifier
            status: New status
        """
        if self._backend == "sqlite":
            conn: aiosqlite.Connection = self._conn  # type: ignore
            await conn.execute(
                "UPDATE checkpoint_threads SET status = ? WHERE thread_id = ?",
                (status, thread_id),
            )
            await conn.commit()
        else:
            pool: asyncpg.Pool = self._conn  # type: ignore
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE checkpoint_threads SET status = $1 WHERE thread_id = $2",
                    status,
                    thread_id,
                )

    async def find_active_threads(self, max_age_hours: float | None = None) -> list[ThreadRecord]:
        """Find all active threads.

        Args:
            max_age_hours: Optional age filter (only return threads active within N hours)

        Returns:
            List of active thread records
        """
        if self._backend == "sqlite":
            return await self._find_active_sqlite(max_age_hours)
        else:
            return await self._find_active_postgres(max_age_hours)

    async def _find_active_sqlite(self, max_age_hours: float | None) -> list[ThreadRecord]:
        """Find active threads (SQLite backend)."""
        conn: aiosqlite.Connection = self._conn  # type: ignore

        if max_age_hours is not None:
            from datetime import timedelta

            cutoff_time = (datetime.now() - timedelta(hours=max_age_hours)).isoformat()
            cursor = await conn.execute(
                """
                SELECT thread_id, status, created_at, last_active_at
                FROM checkpoint_threads
                WHERE status = 'active' AND last_active_at >= ?
                ORDER BY last_active_at DESC
                """,
                (cutoff_time,),
            )
        else:
            cursor = await conn.execute(
                """
                SELECT thread_id, status, created_at, last_active_at
                FROM checkpoint_threads
                WHERE status = 'active'
                ORDER BY last_active_at DESC
                """
            )

        rows = await cursor.fetchall()
        return [self._row_to_record(row) for row in rows]

    async def _find_active_postgres(self, max_age_hours: float | None) -> list[ThreadRecord]:
        """Find active threads (PostgreSQL backend)."""
        pool: asyncpg.Pool = self._conn  # type: ignore

        if max_age_hours is not None:
            from datetime import timedelta

            cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT thread_id, status, created_at, last_active_at
                    FROM checkpoint_threads
                    WHERE status = 'active' AND last_active_at >= $1
                    ORDER BY last_active_at DESC
                    """,
                    cutoff_time,
                )
        else:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT thread_id, status, created_at, last_active_at
                    FROM checkpoint_threads
                    WHERE status = 'active'
                    ORDER BY last_active_at DESC
                    """
                )

        return [self._row_to_record(row) for row in rows]

    def _row_to_record(self, row: tuple[object, ...] | dict[str, object]) -> ThreadRecord:
        """Convert database row to ThreadRecord.

        Args:
            row: Database row (tuple for sqlite, dict-like Record for postgres)

        Returns:
            ThreadRecord instance
        """
        if isinstance(row, (list, tuple)):
            # SQLite: positional tuple
            thread_id, status, created_at, last_active_at = row
        else:
            # PostgreSQL: dict-like Record
            thread_id = row["thread_id"]
            status = row["status"]
            created_at = row["created_at"]
            last_active_at = row["last_active_at"]

        # Parse timestamps
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        if isinstance(last_active_at, str):
            last_active_at = datetime.fromisoformat(last_active_at)

        return ThreadRecord(
            thread_id=str(thread_id),
            status=str(status),  # type: ignore
            created_at=created_at,  # type: ignore
            last_active_at=last_active_at,  # type: ignore
        )

    async def delete(self, thread_id: str) -> bool:
        """Delete thread record.

        Args:
            thread_id: Thread identifier

        Returns:
            True if record existed and was deleted
        """
        if self._backend == "sqlite":
            conn: aiosqlite.Connection = self._conn  # type: ignore
            cursor = await conn.execute(
                "DELETE FROM checkpoint_threads WHERE thread_id = ?",
                (thread_id,),
            )
            await conn.commit()
            return cursor.rowcount > 0
        else:
            pool: asyncpg.Pool = self._conn  # type: ignore
            async with pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM checkpoint_threads WHERE thread_id = $1",
                    thread_id,
                )
                # PostgreSQL returns "DELETE N" where N is row count
                return int(result.split()[-1]) > 0

    async def cleanup_old_records(self, *, max_age_days: float = 7.0) -> int:
        """Clean up old completed/failed thread records to prevent table bloat.

        Args:
            max_age_days: Delete records older than this (default 7.0, keeps active always)

        Returns:
            Number of records deleted
        """
        from datetime import timedelta

        cutoff_time = datetime.now() - timedelta(days=max_age_days)

        if self._backend == "sqlite":
            cutoff_str = cutoff_time.isoformat()
            conn: aiosqlite.Connection = self._conn  # type: ignore
            cursor = await conn.execute(
                """
                DELETE FROM checkpoint_threads
                WHERE last_active_at < ? AND status != 'active'
                """,
                (cutoff_str,),
            )
            await conn.commit()
            deleted = cursor.rowcount
        else:
            pool: asyncpg.Pool = self._conn  # type: ignore
            async with pool.acquire() as conn:
                result = await conn.execute(
                    """
                    DELETE FROM checkpoint_threads
                    WHERE last_active_at < $1 AND status != 'active'
                    """,
                    cutoff_time,
                )
                deleted = int(result.split()[-1])

        if deleted > 0:
            logger.info("ThreadStore: cleaned up %d old records (cutoff=%s)", deleted, cutoff_time.isoformat())

        return deleted

    async def get(self, thread_id: str) -> ThreadRecord | None:
        """Get thread record by ID.

        Args:
            thread_id: Thread identifier

        Returns:
            ThreadRecord or None if not found
        """
        if self._backend == "sqlite":
            conn: aiosqlite.Connection = self._conn  # type: ignore
            cursor = await conn.execute(
                """
                SELECT thread_id, status, created_at, last_active_at
                FROM checkpoint_threads
                WHERE thread_id = ?
                """,
                (thread_id,),
            )
            row = await cursor.fetchone()
            return self._row_to_record(row) if row else None
        else:
            pool: asyncpg.Pool = self._conn  # type: ignore
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT thread_id, status, created_at, last_active_at
                    FROM checkpoint_threads
                    WHERE thread_id = $1
                    """,
                    thread_id,
                )
                return self._row_to_record(row) if row else None


async def create_thread_tables(
    conn: aiosqlite.Connection | asyncpg.Pool,
    backend: Literal["sqlite", "postgres"] = "sqlite",
) -> None:
    """Create checkpoint_threads table.

    Args:
        conn: Database connection
        backend: Database backend type
    """
    sql = SQLITE_THREAD_TABLE_SQL if backend == "sqlite" else POSTGRES_THREAD_TABLE_SQL

    if backend == "sqlite":
        sqlite_conn: aiosqlite.Connection = conn  # type: ignore
        await sqlite_conn.executescript(sql)
        await sqlite_conn.commit()
    else:
        pool: asyncpg.Pool = conn  # type: ignore
        async with pool.acquire() as pg_conn:
            await pg_conn.execute(sql)

    logger.info(f"ThreadStore: table created (backend={backend})")
