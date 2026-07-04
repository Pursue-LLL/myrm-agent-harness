"""Wiki ingestion queue using SQLite for persistent batch processing.

[INPUT]
sqlite3 (POS: standard library database)
pathlib::Path (POS: standard library file path operations)
typing::Literal, TypedDict (POS: standard library types)
..core.structure::WikiStructure (POS: database path retrieval)

[OUTPUT]
WikiIngestionQueue: SQLite-driven persistent file ingestion queue
QueueItem: queue item type

[POS]
Wiki persistent queue. Queues large volumes of raw files for serial or controlled batch processing,
with checkpoint recovery, retry mechanism, and status tracking. Solves OOM and API rate-limit issues
during large-scale knowledge base imports.
"""

import contextlib
import sqlite3
from pathlib import Path
from typing import Literal, TypedDict

from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure


class QueueItem(TypedDict):
    id: int
    file_path: str
    status: Literal["pending", "processing", "completed", "failed"]
    retry_count: int
    error_message: str | None
    created_at: str
    updated_at: str


class WikiIngestionQueue:
    """SQLite-backed persistent queue for wiki ingestion."""

    def __init__(self, structure: WikiStructure):
        self._structure = structure
        # Put DB in the base directory of the wiki
        self.db_path = self._structure.base_dir / ".ingestion_queue.db"
        self._init_db()

    @contextlib.contextmanager
    def _get_conn(self):
        from myrm_agent_harness.utils.db.sqlite import DEFAULT, harden_connection_sync

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        harden_connection_sync(conn, DEFAULT, db_path=self.db_path)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ingestion_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT UNIQUE NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    retry_count INTEGER DEFAULT 0,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Create index for fast status querying
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_status ON ingestion_queue(status)
            """)

    def add_item(self, file_path: Path | str) -> int:
        """Add a file to the queue. Returns item ID."""
        path_str = str(file_path)
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO ingestion_queue (file_path, status, updated_at)
                VALUES (?, 'pending', CURRENT_TIMESTAMP)
                ON CONFLICT(file_path) DO UPDATE SET
                    status = 'pending',
                    retry_count = 0,
                    error_message = NULL,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (path_str,),
            )
            return cursor.lastrowid or 0

    def add_batch(self, file_paths: list[Path | str]) -> None:
        """Add multiple files to the queue."""
        with self._get_conn() as conn:
            conn.executemany(
                """
                INSERT INTO ingestion_queue (file_path, status, updated_at)
                VALUES (?, 'pending', CURRENT_TIMESTAMP)
                ON CONFLICT(file_path) DO UPDATE SET
                    status = 'pending',
                    retry_count = 0,
                    error_message = NULL,
                    updated_at = CURRENT_TIMESTAMP
                """,
                [(str(p),) for p in file_paths],
            )

    def get_pending_items(self, limit: int = 10) -> list[QueueItem]:
        """Get batch of pending items to process."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM ingestion_queue
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (limit,),
            )
            # The type ignore is needed because sqlite3.Row isn't exactly matching TypedDict
            return [dict(row) for row in cursor.fetchall()]  # type: ignore

    def mark_processing(self, item_id: int) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE ingestion_queue SET status = 'processing', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (item_id,),
            )

    def mark_completed(self, item_id: int) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE ingestion_queue SET status = 'completed', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (item_id,),
            )

    def mark_failed(self, item_id: int, error_message: str) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE ingestion_queue
                SET status = 'failed',
                    retry_count = retry_count + 1,
                    error_message = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (error_message, item_id),
            )

    def get_retryable_items(self, max_retries: int = 3, limit: int = 5) -> list[QueueItem]:
        """Get failed items that haven't exceeded max retry count."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM ingestion_queue
                WHERE status = 'failed' AND retry_count < ?
                ORDER BY updated_at ASC
                LIMIT ?
                """,
                (max_retries, limit),
            )
            return [dict(row) for row in cursor.fetchall()]  # type: ignore

    def reset_for_retry(self, item_id: int) -> None:
        """Reset a specific failed item to pending for retry."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE ingestion_queue SET status = 'pending', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (item_id,),
            )

    def reset_failed(self) -> int:
        """Reset all failed items to pending."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "UPDATE ingestion_queue SET status = 'pending', error_message = NULL WHERE status = 'failed'"
            )
            return cursor.rowcount

    def cancel_pending(self) -> int:
        """Cancel all pending items."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "UPDATE ingestion_queue SET status = 'failed', error_message = 'Cancelled by user' WHERE status = 'pending'"
            )
            return cursor.rowcount

    def reset_stale_processing(self, stale_seconds: int = 300) -> int:
        """Reset items stuck in 'processing' state back to 'pending'.

        Items remain in 'processing' if a worker crashes mid-flight.
        This method recovers them based on a staleness threshold.
        """
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                UPDATE ingestion_queue
                SET status = 'pending', updated_at = CURRENT_TIMESTAMP
                WHERE status = 'processing'
                  AND updated_at < datetime('now', ? || ' seconds')
                """,
                (f"-{stale_seconds}",),
            )
            return cursor.rowcount

    def get_stats(self) -> dict[str, int]:
        """Get queue statistics."""
        with self._get_conn() as conn:
            cursor = conn.execute("SELECT status, COUNT(*) as count FROM ingestion_queue GROUP BY status")
            stats = {"pending": 0, "processing": 0, "completed": 0, "failed": 0}
            for row in cursor.fetchall():
                status = row["status"]
                if status in stats:
                    stats[status] = row["count"]
            return stats
