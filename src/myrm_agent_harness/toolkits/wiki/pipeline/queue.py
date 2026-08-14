"""Wiki ingestion queue using SQLite for persistent batch processing.

[INPUT]
sqlite3 (POS: standard library database)
pathlib::Path (POS: standard library file path operations)
typing::Literal, TypedDict (POS: standard library types)
..core.structure::WikiStructure (POS: database path retrieval)
.resilience::CompileCircuitStore, is_transient_error_kind (POS: compile pause + retry policy)

[OUTPUT]
WikiIngestionQueue: SQLite-driven persistent file ingestion queue
QueueItem: queue item type

[POS]
Wiki persistent queue. Queues large volumes of raw files for serial or controlled batch processing,
with checkpoint recovery, retry mechanism, and status tracking. Solves OOM and API rate-limit issues
during large-scale knowledge base imports.
"""

from __future__ import annotations

import contextlib
import sqlite3
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Literal, TypedDict, cast

from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure

from .resilience import (
    CompileCircuitStore,
    CompileRunSnapshot,
    is_transient_error_kind,
    sanitize_display_message,
)


class QueueItem(TypedDict):
    id: int
    file_path: str
    status: Literal["pending", "processing", "completed", "failed"]
    retry_count: int
    error_message: str | None
    error_kind: str | None
    retry_after: str | None
    created_at: str
    updated_at: str


class WikiIngestionQueue:
    """SQLite-backed persistent queue for wiki ingestion."""

    def __init__(self, structure: WikiStructure):
        self._structure = structure
        self.db_path = self._structure.base_dir / ".ingestion_queue.db"
        self._circuit = CompileCircuitStore(self.db_path)
        self._init_db()

    @property
    def circuit(self) -> CompileCircuitStore:
        return self._circuit

    @contextlib.contextmanager
    def _get_conn(self) -> Iterator[sqlite3.Connection]:
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ingestion_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT UNIQUE NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    retry_count INTEGER DEFAULT 0,
                    error_message TEXT,
                    error_kind TEXT,
                    retry_after TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_status ON ingestion_queue(status)
            """
            )
            self._migrate_schema(conn)

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(ingestion_queue)").fetchall()}
        if "error_kind" not in columns:
            conn.execute("ALTER TABLE ingestion_queue ADD COLUMN error_kind TEXT")
        if "retry_after" not in columns:
            conn.execute("ALTER TABLE ingestion_queue ADD COLUMN retry_after TIMESTAMP")

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
                    error_kind = NULL,
                    retry_after = NULL,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (path_str,),
            )
            return cursor.lastrowid or 0

    def add_batch(self, file_paths: Sequence[Path | str]) -> None:
        """Add multiple files to the queue."""
        from myrm_agent_harness.toolkits.wiki.pipeline.corpus_dedup.eligibility import (
            CorpusEligibilityFilter,
        )

        path_objects = [Path(path) for path in file_paths]
        filtered = CorpusEligibilityFilter(self._structure).filter_raw_paths(path_objects)
        if not filtered:
            return
        with self._get_conn() as conn:
            conn.executemany(
                """
                INSERT INTO ingestion_queue (file_path, status, updated_at)
                VALUES (?, 'pending', CURRENT_TIMESTAMP)
                ON CONFLICT(file_path) DO UPDATE SET
                    status = 'pending',
                    retry_count = 0,
                    error_message = NULL,
                    error_kind = NULL,
                    retry_after = NULL,
                    updated_at = CURRENT_TIMESTAMP
                """,
                [(str(p),) for p in filtered],
            )

    def list_pending_file_paths(self) -> list[str]:
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                SELECT file_path FROM ingestion_queue
                WHERE status = 'pending'
                ORDER BY created_at ASC
                """
            )
            return [str(row["file_path"]) for row in cursor.fetchall()]

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
            return [dict(row) for row in cursor.fetchall()]  # type: ignore[misc]

    def get_failed_items(self, limit: int = 20) -> list[QueueItem]:
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM ingestion_queue
                WHERE status = 'failed'
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]  # type: ignore[misc]

    def mark_processing(self, item_id: int) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE ingestion_queue SET status = 'processing', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (item_id,),
            )

    def mark_completed(self, item_id: int) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE ingestion_queue
                SET status = 'completed',
                    error_message = NULL,
                    error_kind = NULL,
                    retry_after = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (item_id,),
            )

    def mark_failed(
        self,
        item_id: int,
        error_message: str,
        *,
        error_kind: str = "unknown",
        retry_after_seconds: int = 0,
    ) -> None:
        safe_message = sanitize_display_message(error_message)
        with self._get_conn() as conn:
            if retry_after_seconds > 0:
                conn.execute(
                    """
                    UPDATE ingestion_queue
                    SET status = 'failed',
                        retry_count = retry_count + 1,
                        error_message = ?,
                        error_kind = ?,
                        retry_after = datetime('now', ? || ' seconds'),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (safe_message, error_kind, f"+{retry_after_seconds}", item_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE ingestion_queue
                    SET status = 'failed',
                        retry_count = retry_count + 1,
                        error_message = ?,
                        error_kind = ?,
                        retry_after = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (safe_message, error_kind, item_id),
                )

    def get_transient_retryable_items(self, max_retries: int = 3, limit: int = 5) -> list[QueueItem]:
        """Failed transient items eligible for automatic retry (respects backoff)."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM ingestion_queue
                WHERE status = 'failed'
                  AND retry_count < ?
                  AND error_kind IS NOT NULL
                  AND (
                    retry_after IS NULL
                    OR retry_after <= CURRENT_TIMESTAMP
                  )
                ORDER BY updated_at ASC
                LIMIT ?
                """,
                (max_retries, limit * 3),
            )
            items = cast(list[QueueItem], [dict(row) for row in cursor.fetchall()])
        return [item for item in items if is_transient_error_kind(item.get("error_kind") or "")][:limit]

    def reset_for_retry(self, item_id: int) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE ingestion_queue
                SET status = 'pending',
                    retry_after = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (item_id,),
            )

    def reset_transient_failed(self) -> int:
        """Reset only transient failed items back to pending."""
        with self._get_conn() as conn:
            cursor = conn.execute("SELECT id, error_kind FROM ingestion_queue WHERE status = 'failed'")
            reset_ids = [row["id"] for row in cursor.fetchall() if is_transient_error_kind(row["error_kind"] or "")]
            if not reset_ids:
                return 0
            conn.executemany(
                """
                UPDATE ingestion_queue
                SET status = 'pending',
                    error_message = NULL,
                    retry_after = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                [(item_id,) for item_id in reset_ids],
            )
            return len(reset_ids)

    def reset_failed(self) -> int:
        """Reset all failed items to pending (manual recovery)."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                UPDATE ingestion_queue
                SET status = 'pending',
                    error_message = NULL,
                    error_kind = NULL,
                    retry_after = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE status = 'failed'
                """
            )
            return int(cursor.rowcount)

    def cancel_pending(self) -> int:
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                UPDATE ingestion_queue
                SET status = 'failed',
                    error_message = 'Cancelled by user',
                    error_kind = 'cancelled',
                    retry_after = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE status = 'pending'
                """
            )
            return int(cursor.rowcount)

    def reset_stale_processing(self, stale_seconds: int = 300) -> int:
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
            return int(cursor.rowcount)

    def get_stats(self) -> dict[str, int]:
        with self._get_conn() as conn:
            cursor = conn.execute("SELECT status, COUNT(*) as count FROM ingestion_queue GROUP BY status")
            stats = {"pending": 0, "processing": 0, "completed": 0, "failed": 0}
            for row in cursor.fetchall():
                status = row["status"]
                if status in stats:
                    stats[status] = row["count"]
            return stats

    def get_compile_run(self) -> CompileRunSnapshot:
        return self._circuit.get_snapshot()

    def pause_compile(self, reason: str, primary_error_kind: str) -> None:
        self._circuit.pause(reason, primary_error_kind)

    def resume_compile(self) -> None:
        self._circuit.resume()

    def is_compile_paused(self) -> bool:
        return self._circuit.is_paused()

    def set_compile_phase(
        self,
        phase: str,
        *,
        facet_count: int = 0,
        warning_count: int = 0,
        survey_skipped: bool = False,
    ) -> None:
        from .resilience.types import CompilePhase

        typed_phase: CompilePhase
        if phase in {"idle", "structure_survey", "semantic_compile", "postprocess"}:
            typed_phase = phase  # type: ignore[assignment]
        else:
            typed_phase = "idle"
        self._circuit.set_phase(
            typed_phase,
            facet_count=facet_count,
            warning_count=warning_count,
            survey_skipped=survey_skipped,
        )
