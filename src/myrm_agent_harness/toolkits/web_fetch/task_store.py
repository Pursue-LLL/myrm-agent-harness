"""CrawlTaskStore — SQLite WAL persistence for async crawl tasks.

Provides durable task queue for the deep_crawl pipeline. Tasks persist
across process restarts, enabling resume after crash or shutdown.

[INPUT]
- (none)

[OUTPUT]
- CrawlTaskStore: SQLite-backed task queue for deep_crawl operations

[POS]
Durable task storage for async deep_crawl pipeline. Uses SQLite WAL mode
for concurrent read/write safety within single-process sandbox semantics.
"""

from __future__ import annotations

import logging
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)


class CrawlTaskStatus(str, Enum):
    """Task lifecycle states."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class CrawlTask:
    """A single URL crawl task within a task group."""

    task_id: str
    group_id: str
    url: str
    depth: int
    status: CrawlTaskStatus
    result_path: str | None = None
    error: str | None = None
    created_at: float = 0.0
    completed_at: float | None = None


@dataclass(slots=True)
class CrawlTaskGroupSummary:
    """Aggregated status of a task group."""

    group_id: str
    total: int
    completed: int
    failed: int
    pending: int
    running: int
    cancelled: int
    result_dir: str
    created_at: float


class CrawlTaskStore:
    """SQLite-backed durable task store for deep_crawl operations.

    Uses WAL journaling for concurrent read safety and crash recovery.
    Designed for single-process sandbox semantics (no cross-process guarantees).
    """

    def __init__(self, db_path: str | Path):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self._db_path), timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS crawl_task_groups (
                    group_id TEXT PRIMARY KEY,
                    seed_url TEXT NOT NULL,
                    max_depth INTEGER NOT NULL DEFAULT 3,
                    max_pages INTEGER NOT NULL DEFAULT 100,
                    result_dir TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    completed_at REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS crawl_tasks (
                    task_id TEXT PRIMARY KEY,
                    group_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    depth INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    result_path TEXT,
                    error TEXT,
                    created_at REAL NOT NULL,
                    completed_at REAL,
                    FOREIGN KEY (group_id) REFERENCES crawl_task_groups(group_id)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_group_status
                ON crawl_tasks(group_id, status)
            """)
            conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_group_url
                ON crawl_tasks(group_id, url)
            """)
            conn.execute(
                "UPDATE crawl_tasks SET status = ? WHERE status = ?",
                (CrawlTaskStatus.PENDING.value, CrawlTaskStatus.RUNNING.value),
            )

    def create_group(
        self,
        seed_url: str,
        result_dir: str,
        *,
        max_depth: int = 3,
        max_pages: int = 100,
    ) -> str:
        """Create a new task group, return group_id."""
        group_id = f"tg_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO crawl_task_groups
                   (group_id, seed_url, max_depth, max_pages, result_dir, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (group_id, seed_url, max_depth, max_pages, result_dir, time.time()),
            )
        return group_id

    def add_task(self, group_id: str, url: str, depth: int = 0) -> str | None:
        """Add a URL task to the group. Returns task_id or None if URL already exists."""
        from .url_normalizer import normalize_url

        normalized = normalize_url(url)
        task_id = f"ct_{uuid.uuid4().hex[:12]}"
        try:
            with self._connect() as conn:
                conn.execute(
                    """INSERT INTO crawl_tasks
                       (task_id, group_id, url, depth, status, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (task_id, group_id, normalized, depth, CrawlTaskStatus.PENDING.value, time.time()),
                )
            return task_id
        except sqlite3.IntegrityError:
            return None

    def add_tasks_batch(self, group_id: str, urls: list[tuple[str, int]]) -> int:
        """Batch-add URLs (url, depth). Returns count of newly added tasks."""
        from .url_normalizer import normalize_url

        added = 0
        with self._connect() as conn:
            for url, depth in urls:
                normalized = normalize_url(url)
                task_id = f"ct_{uuid.uuid4().hex[:12]}"
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO crawl_tasks
                           (task_id, group_id, url, depth, status, created_at)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (task_id, group_id, normalized, depth, CrawlTaskStatus.PENDING.value, time.time()),
                    )
                    if conn.execute("SELECT changes()").fetchone()[0] > 0:
                        added += 1
                except sqlite3.IntegrityError:
                    pass
        return added

    def claim_next_pending(self, group_id: str) -> CrawlTask | None:
        """Atomically claim next pending task (set status=running). Returns None if queue empty."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT task_id, group_id, url, depth, status, result_path, error, created_at, completed_at
                   FROM crawl_tasks
                   WHERE group_id = ? AND status = ?
                   ORDER BY depth ASC, created_at ASC
                   LIMIT 1""",
                (group_id, CrawlTaskStatus.PENDING.value),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE crawl_tasks SET status = ? WHERE task_id = ?",
                (CrawlTaskStatus.RUNNING.value, row["task_id"]),
            )
            return CrawlTask(
                task_id=row["task_id"],
                group_id=row["group_id"],
                url=row["url"],
                depth=row["depth"],
                status=CrawlTaskStatus.RUNNING,
                result_path=row["result_path"],
                error=row["error"],
                created_at=row["created_at"],
                completed_at=row["completed_at"],
            )

    def mark_completed(self, task_id: str, result_path: str) -> None:
        """Mark task as completed with result file path."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE crawl_tasks SET status = ?, result_path = ?, completed_at = ? WHERE task_id = ?",
                (CrawlTaskStatus.COMPLETED.value, result_path, time.time(), task_id),
            )

    def mark_failed(self, task_id: str, error: str) -> None:
        """Mark task as failed with error message."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE crawl_tasks SET status = ?, error = ?, completed_at = ? WHERE task_id = ?",
                (CrawlTaskStatus.FAILED.value, error, time.time(), task_id),
            )

    def get_group_summary(self, group_id: str) -> CrawlTaskGroupSummary | None:
        """Get aggregated status for a task group."""
        with self._connect() as conn:
            group_row = conn.execute(
                "SELECT * FROM crawl_task_groups WHERE group_id = ?", (group_id,)
            ).fetchone()
            if not group_row:
                return None

            counts = conn.execute(
                """SELECT status, COUNT(*) as cnt
                   FROM crawl_tasks WHERE group_id = ?
                   GROUP BY status""",
                (group_id,),
            ).fetchall()

            status_counts: dict[str, int] = {row["status"]: row["cnt"] for row in counts}
            total = sum(status_counts.values())

            return CrawlTaskGroupSummary(
                group_id=group_id,
                total=total,
                completed=status_counts.get(CrawlTaskStatus.COMPLETED.value, 0),
                failed=status_counts.get(CrawlTaskStatus.FAILED.value, 0),
                pending=status_counts.get(CrawlTaskStatus.PENDING.value, 0),
                running=status_counts.get(CrawlTaskStatus.RUNNING.value, 0),
                cancelled=status_counts.get(CrawlTaskStatus.CANCELLED.value, 0),
                result_dir=group_row["result_dir"],
                created_at=group_row["created_at"],
            )

    def get_group_max_pages(self, group_id: str) -> int:
        """Get the max_pages limit for a task group."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT max_pages FROM crawl_task_groups WHERE group_id = ?", (group_id,)
            ).fetchone()
            return row["max_pages"] if row else 100

    def get_group_max_depth(self, group_id: str) -> int:
        """Get the max_depth limit for a task group."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT max_depth FROM crawl_task_groups WHERE group_id = ?", (group_id,)
            ).fetchone()
            return row["max_depth"] if row else 3

    def get_group_total_tasks(self, group_id: str) -> int:
        """Get total task count for a group."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM crawl_tasks WHERE group_id = ?", (group_id,)
            ).fetchone()
            return row["cnt"] if row else 0

    def cancel_group(self, group_id: str) -> int:
        """Cancel all pending tasks in a group. Returns count of cancelled tasks."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE crawl_tasks SET status = ?, completed_at = ? WHERE group_id = ? AND status = ?",
                (CrawlTaskStatus.CANCELLED.value, time.time(), group_id, CrawlTaskStatus.PENDING.value),
            )
            row = conn.execute("SELECT changes()").fetchone()
            return row[0] if row else 0

    def is_group_cancelled(self, group_id: str) -> bool:
        """Check if group has been cancelled (any tasks in cancelled state)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM crawl_tasks WHERE group_id = ? AND status = ? LIMIT 1",
                (group_id, CrawlTaskStatus.CANCELLED.value),
            ).fetchone()
            return row is not None

    def has_pending_or_running(self, group_id: str) -> bool:
        """Check if group has any pending or running tasks."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT COUNT(*) as cnt FROM crawl_tasks
                   WHERE group_id = ? AND status IN (?, ?)""",
                (group_id, CrawlTaskStatus.PENDING.value, CrawlTaskStatus.RUNNING.value),
            ).fetchone()
            return (row["cnt"] if row else 0) > 0
