"""Task store implementation using SQLite.

This module provides a SQLite-based task store with support for:
- CRUD operations
- Priority-based querying
- Idempotency checks
- Result caching
- Multi-tenant isolation
- Efficient indexing


[INPUT]
- tasks.protocols::Task, TaskStatus, TaskError, RetryPolicy, ErrorRecoverability (POS: core task data models)

[OUTPUT]
- TaskFilters: query filter builder for task listing
- TaskStoreProtocol: abstract task store interface protocol
- SQLiteTaskStore: SQLite-backed task store implementation

[POS]
Task persistence layer. Provides SQLite-backed CRUD, priority querying, idempotency checks,
result caching, and multi-tenant isolation for the async task system.
"""

import json
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from .protocols import ErrorRecoverability, RetryPolicy, Task, TaskError, TaskStatus

_DEFAULT_ORDER_BY = "created_at DESC"
_ALLOWED_ORDER_COLUMNS = {
    "created_at",
    "updated_at",
    "started_at",
    "completed_at",
    "priority",
    "status",
    "task_type",
    "user_id",
    "task_id",
}
_ALLOWED_ORDER_DIRECTIONS = {"ASC", "DESC"}


def _sanitize_order_by(order_by: str) -> str:
    normalized = " ".join(order_by.strip().split())
    if not normalized:
        return _DEFAULT_ORDER_BY

    parts = normalized.split(" ")
    if len(parts) == 1:
        column = parts[0]
        direction = "ASC"
    elif len(parts) == 2:
        column, direction = parts
    else:
        return _DEFAULT_ORDER_BY

    direction_normalized = direction.upper()
    if column not in _ALLOWED_ORDER_COLUMNS:
        return _DEFAULT_ORDER_BY
    if direction_normalized not in _ALLOWED_ORDER_DIRECTIONS:
        return _DEFAULT_ORDER_BY
    return f"{column} {direction_normalized}"


class TaskFilters:
    """Filters for querying tasks."""

    def __init__(
        self,
        status: TaskStatus | list[TaskStatus] | None = None,
        task_type: str | list[str] | None = None,
        user_id: str | None = None,
        tags: list[str] | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
        order_by: str = _DEFAULT_ORDER_BY,
        task_ids: list[str] | None = None,
    ):
        self.status = status
        self.task_type = task_type
        self.user_id = user_id
        self.tags = tags
        self.created_after = created_after
        self.created_before = created_before
        self.limit = limit
        self.offset = offset
        self.order_by = _sanitize_order_by(order_by)
        self.task_ids = task_ids


class TaskStore(Protocol):
    """Protocol for task storage."""

    async def create_task(self, task: Task) -> Task: ...
    async def get_task(self, task_id: str) -> Task | None: ...
    async def update_task(self, task_id: str, **updates) -> Task: ...
    async def list_tasks(self, filters: TaskFilters) -> list[Task]: ...
    async def find_by_idempotency_key(self, key: str) -> Task | None: ...
    async def find_by_cache_key(self, key: str) -> Task | None: ...
    async def clean_old_tasks(self, days: int = 30) -> int: ...


class SQLiteTaskStore:
    """SQLite-based task store implementation.

    Features:
    - Efficient B-tree indexes on task_id, user_id, status, priority
    - JSON storage for flexible payload/result/metadata
    - Transaction support for atomic updates
    - Connection pooling (one connection per instance)
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._init_db()

    async def initialize(self) -> None:
        """Async initialization hook (schema already initialized in __init__)."""
        pass

    def _init_db(self) -> None:
        """Initialize database schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = self._conn()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                task_type TEXT NOT NULL,
                user_id TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                payload TEXT NOT NULL,
                result TEXT,
                error_type TEXT,
                error_message TEXT,
                error_recoverable TEXT,
                error_traceback TEXT,
                priority INTEGER NOT NULL DEFAULT 5,
                timeout INTEGER NOT NULL DEFAULT 300,
                idempotency_key TEXT,
                cache_key TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                retry_policy TEXT,
                next_retry_at TEXT,
                progress REAL NOT NULL DEFAULT 0.0,
                progress_message TEXT,
                cancellation_reason TEXT,
                tags TEXT,
                metadata TEXT,
                worker_id TEXT,
                worker_heartbeat_at TEXT
            )
        """
        )

        # Create indexes for efficient querying
        conn.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON tasks(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON tasks(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_task_type ON tasks(task_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_priority_created ON tasks(priority DESC, created_at ASC)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_idempotency_key ON tasks(idempotency_key) WHERE idempotency_key IS NOT NULL"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_key ON tasks(cache_key) WHERE cache_key IS NOT NULL")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON tasks(created_at)")

        conn.commit()
        conn.close()

    def _conn(self) -> sqlite3.Connection:
        """Get database connection."""
        from myrm_agent_harness.utils.db.sqlite import DEFAULT, harden_connection_sync

        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        harden_connection_sync(conn, DEFAULT, db_path=self.db_path)
        return conn

    async def create_task(self, task: Task) -> Task:
        """Create new task."""
        conn = self._conn()
        try:
            conn.execute(
                """
                INSERT INTO tasks (
                    task_id, task_type, user_id, status, created_at, updated_at,
                    started_at, completed_at,
                    payload, result,
                    error_type, error_message, error_recoverable, error_traceback,
                    priority, timeout, idempotency_key, cache_key,
                    retry_count, retry_policy, next_retry_at,
                    progress, progress_message,
                    cancellation_reason, tags, metadata, worker_id, worker_heartbeat_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    task.task_id,
                    task.task_type,
                    task.user_id,
                    task.status.value,
                    task.created_at.isoformat(),
                    task.updated_at.isoformat(),
                    task.started_at.isoformat() if task.started_at else None,
                    task.completed_at.isoformat() if task.completed_at else None,
                    json.dumps(task.payload),
                    json.dumps(task.result) if task.result else None,
                    task.error.error_type if task.error else None,
                    task.error.message if task.error else None,
                    task.error.recoverable.value if task.error else None,
                    task.error.traceback if task.error else None,
                    task.priority,
                    task.timeout,
                    task.idempotency_key,
                    task.cache_key,
                    task.retry_count,
                    (json.dumps(asdict(task.retry_policy)) if task.retry_policy else None),
                    task.next_retry_at.isoformat() if task.next_retry_at else None,
                    task.progress,
                    task.progress_message,
                    task.cancellation_reason,
                    json.dumps(task.tags),
                    json.dumps(task.metadata),
                    task.worker_id,
                    (task.worker_heartbeat_at.isoformat() if task.worker_heartbeat_at else None),
                ),
            )
            conn.commit()
            return task
        finally:
            conn.close()

    async def get_task(self, task_id: str) -> Task | None:
        """Get task by ID."""
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if not row:
                return None
            return self._row_to_task(row)
        finally:
            conn.close()

    async def update_task(self, task_id: str, **updates) -> Task:
        """Update task fields."""
        conn = self._conn()
        try:
            # Build SET clause dynamically
            set_parts = []
            values = []

            for key, value in updates.items():
                if key == "status":
                    set_parts.append("status = ?")
                    values.append(value.value if isinstance(value, TaskStatus) else value)
                elif key == "error":
                    set_parts.extend(
                        [
                            "error_type = ?",
                            "error_message = ?",
                            "error_recoverable = ?",
                            "error_traceback = ?",
                        ]
                    )
                    error: TaskError | None = value
                    if error is None:
                        values.extend([None, None, None, None])
                    else:
                        values.extend(
                            [
                                error.error_type,
                                error.message,
                                error.recoverable.value,
                                error.traceback,
                            ]
                        )
                elif key == "result":
                    set_parts.append("result = ?")
                    values.append(None if value is None else json.dumps(value))
                elif key in ("payload", "metadata"):
                    set_parts.append(f"{key} = ?")
                    values.append(json.dumps(value))
                elif key == "tags":
                    set_parts.append("tags = ?")
                    values.append(json.dumps(value))
                elif key in (
                    "started_at",
                    "completed_at",
                    "next_retry_at",
                    "worker_heartbeat_at",
                ):
                    set_parts.append(f"{key} = ?")
                    values.append(value.isoformat() if value else None)
                else:
                    set_parts.append(f"{key} = ?")
                    values.append(value)

            set_parts.append("updated_at = ?")
            values.append(datetime.now(UTC).isoformat())
            values.append(task_id)

            conn.execute(f"UPDATE tasks SET {', '.join(set_parts)} WHERE task_id = ?", values)
            conn.commit()

            return await self.get_task(task_id)
        finally:
            conn.close()

    async def list_tasks(self, filters: TaskFilters) -> list[Task]:
        """List tasks with filters."""
        conn = self._conn()
        try:
            where_parts = []
            values = []

            if filters.status:
                statuses = filters.status if isinstance(filters.status, list) else [filters.status]
                placeholders = ",".join(["?"] * len(statuses))
                where_parts.append(f"status IN ({placeholders})")
                values.extend([s.value for s in statuses])

            if filters.task_type:
                types = filters.task_type if isinstance(filters.task_type, list) else [filters.task_type]
                placeholders = ",".join(["?"] * len(types))
                where_parts.append(f"task_type IN ({placeholders})")
                values.extend(types)

            if filters.task_ids:
                placeholders = ",".join(["?"] * len(filters.task_ids))
                where_parts.append(f"task_id IN ({placeholders})")
                values.extend(filters.task_ids)

            if filters.user_id:
                where_parts.append("user_id = ?")
                values.append(filters.user_id)

            if filters.created_after:
                where_parts.append("created_at >= ?")
                values.append(filters.created_after.isoformat())

            if filters.created_before:
                where_parts.append("created_at <= ?")
                values.append(filters.created_before.isoformat())

            # TODO: Tag filtering requires JSON query (not efficient in SQLite)

            where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

            query = f"""
                SELECT * FROM tasks
                {where_clause}
                ORDER BY {filters.order_by}
                LIMIT ? OFFSET ?
            """
            values.extend([filters.limit, filters.offset])

            rows = conn.execute(query, values).fetchall()
            return [self._row_to_task(row) for row in rows]
        finally:
            conn.close()

    async def find_by_idempotency_key(self, key: str) -> Task | None:
        """Find task by idempotency key."""
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM tasks WHERE idempotency_key = ? ORDER BY created_at DESC LIMIT 1",
                (key,),
            ).fetchone()
            return self._row_to_task(row) if row else None
        finally:
            conn.close()

    async def find_by_cache_key(self, key: str) -> Task | None:
        """Find succeeded task by cache key."""
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM tasks WHERE cache_key = ? AND status = ? ORDER BY completed_at DESC LIMIT 1",
                (key, TaskStatus.SUCCEEDED.value),
            ).fetchone()
            return self._row_to_task(row) if row else None
        finally:
            conn.close()

    async def clean_old_tasks(self, days: int = 30) -> int:
        """Delete old completed tasks."""
        conn = self._conn()
        try:
            cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
            cursor = conn.execute(
                "DELETE FROM tasks WHERE status IN (?, ?, ?) AND completed_at < ?",
                (
                    TaskStatus.SUCCEEDED.value,
                    TaskStatus.FAILED.value,
                    TaskStatus.CANCELLED.value,
                    cutoff,
                ),
            )
            deleted = cursor.rowcount
            conn.commit()
            return deleted
        finally:
            conn.close()

    def _row_to_task(self, row: sqlite3.Row) -> Task:
        """Convert SQL row to Task object."""
        error = None
        if row["error_type"]:
            error = TaskError(
                error_type=row["error_type"],
                message=row["error_message"],
                recoverable=ErrorRecoverability(row["error_recoverable"]),
                traceback=row["error_traceback"],
            )

        retry_policy = None
        if row["retry_policy"]:
            policy_dict = json.loads(row["retry_policy"])
            retry_policy = RetryPolicy(**policy_dict)

        return Task(
            task_id=row["task_id"],
            task_type=row["task_type"],
            user_id=row["user_id"],
            status=TaskStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            started_at=(datetime.fromisoformat(row["started_at"]) if row["started_at"] else None),
            completed_at=(datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None),
            payload=json.loads(row["payload"]),
            result=json.loads(row["result"]) if row["result"] else None,
            error=error,
            priority=row["priority"],
            timeout=row["timeout"],
            idempotency_key=row["idempotency_key"],
            cache_key=row["cache_key"],
            retry_count=row["retry_count"],
            retry_policy=retry_policy,
            next_retry_at=(datetime.fromisoformat(row["next_retry_at"]) if row["next_retry_at"] else None),
            progress=row["progress"],
            progress_message=row["progress_message"],
            cancellation_reason=row["cancellation_reason"],
            tags=json.loads(row["tags"]),
            metadata=json.loads(row["metadata"]),
            worker_id=row["worker_id"],
            worker_heartbeat_at=(
                datetime.fromisoformat(row["worker_heartbeat_at"]) if row["worker_heartbeat_at"] else None
            ),
        )


__all__ = ["SQLiteTaskStore", "TaskFilters", "TaskStore"]
