"""Idle Task Registry for crash-resilient persistence and concurrency control.

[INPUT]
- (none)

[OUTPUT]
- IdleTaskRecord: Represents a pending or running background idle task.
- IdleTaskRegistry: SQLite-backed task registry with atomic locking for idle ...
- get_idle_task_registry: Get or create the singleton registry bound to the workspa...

[POS]
Idle Task Registry for crash-resilient persistence and concurrency control.
"""

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

try:
    import aiosqlite

    from myrm_agent_harness.utils.db.sqlite import connect_async
except (ImportError, TypeError):
    aiosqlite = None  # type: ignore[assignment]


@dataclass
class IdleTaskRecord:
    """Represents a pending or running background idle task."""

    id: int
    session_id: str
    task_type: str
    payload: dict[str, Any]
    status: str
    created_at: float


class IdleTaskRegistry:
    """SQLite-backed task registry with atomic locking for idle tasks."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._initialized = False

    async def init_db(self) -> None:
        """Initialize the SQLite database and table."""
        if aiosqlite is None:
            logger.warning("aiosqlite not installed. IdleTaskRegistry disabled.")
            return

        if self._initialized:
            return

        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        async with connect_async(self.db_path) as db:
            await db.execute(
                """CREATE TABLE IF NOT EXISTS idle_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    payload TEXT,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL
                )"""
            )
            # Create an index for faster lookups
            await db.execute("CREATE INDEX IF NOT EXISTS idx_idle_tasks_status ON idle_tasks(status, session_id)")
            await db.commit()
            self._initialized = True

    async def enqueue(self, session_id: str, task_type: str, payload: dict[str, Any]) -> None:
        """Enqueue a new idle task if not already pending."""
        if not self._initialized:
            await self.init_db()
        if aiosqlite is None:
            return

        # Deduplicate: Avoid enqueuing the exact same task_type for the same session if already pending
        async with connect_async(self.db_path) as db:
            cursor = await db.execute(
                "SELECT 1 FROM idle_tasks WHERE session_id = ? AND task_type = ? AND status IN ('pending', 'running') LIMIT 1",
                (session_id, task_type),
            )
            exists = await cursor.fetchone()
            if exists:
                return

            await db.execute(
                "INSERT INTO idle_tasks (session_id, task_type, payload, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
                (session_id, task_type, json.dumps(payload), time.time()),
            )
            await db.commit()

    async def acquire_next(self, session_id: str) -> IdleTaskRecord | None:
        """Atomically lock and acquire the next pending task for the session.

        Uses SQLite's RETURNING clause for row-level locking, ensuring that
        even with multiple Uvicorn workers, only one process acquires the task.
        """
        if not self._initialized:
            await self.init_db()
        if aiosqlite is None:
            return None

        async with connect_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            # SQLite >= 3.35.0 supports UPDATE ... RETURNING
            # We use a subquery to find the oldest pending task ID for this session
            cursor = await db.execute(
                """
                UPDATE idle_tasks
                SET status = 'running'
                WHERE id = (
                    SELECT id FROM idle_tasks
                    WHERE status = 'pending' AND session_id = ?
                    ORDER BY created_at ASC
                    LIMIT 1
                )
                RETURNING *
                """,
                (session_id),
            )
            row = await cursor.fetchone()
            await db.commit()

            if row:
                return IdleTaskRecord(
                    id=row["id"],
                    session_id=row["session_id"],
                    task_type=row["task_type"],
                    payload=json.loads(row["payload"]),
                    status=row["status"],
                    created_at=row["created_at"],
                )
            return None

    async def mark_completed(self, task_id: int) -> None:
        """Mark a task as successfully completed."""
        if aiosqlite is None:
            return
        async with connect_async(self.db_path) as db:
            await db.execute("UPDATE idle_tasks SET status='completed' WHERE id=?", (task_id))
            await db.commit()

    async def mark_error(self, task_id: int) -> None:
        """Mark a task as failed."""
        if aiosqlite is None:
            return
        async with connect_async(self.db_path) as db:
            await db.execute("UPDATE idle_tasks SET status='error' WHERE id=?", (task_id))
            await db.commit()

    async def cleanup_old_tasks(self, days_old: int = 7) -> int:
        """Clean up completed/errored tasks older than X days."""
        if aiosqlite is None:
            return 0
        cutoff = time.time() - (days_old * 86400)
        async with connect_async(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM idle_tasks WHERE status IN ('completed', 'error') AND created_at < ?", (cutoff)
            )
            deleted = cursor.rowcount
            await db.commit()
            return deleted


_registry_instance: IdleTaskRegistry | None = None


def get_idle_task_registry(workspace_root: str) -> IdleTaskRegistry:
    """Get or create the singleton registry bound to the workspace root."""
    global _registry_instance
    if _registry_instance is None:
        db_path = os.path.join(workspace_root, ".context", "system", "idle_tasks.db")
        _registry_instance = IdleTaskRegistry(db_path)
    return _registry_instance
