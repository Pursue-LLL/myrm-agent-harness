"""SQLite durable ledger for background bash jobs (BSDL Core).

[INPUT]
- _background_job_store_core::BackgroundJobRecord (POS: record model)
- utils.db.sqlite::CACHE, harden_connection_sync (POS: SQLite hardening)

[OUTPUT]
- BackgroundJobStore: CRUD + finish dedupe + reconcile
- configure_background_job_store / get_background_job_store: Singleton lifecycle

[POS]
Harness persistence for background shell metadata — registry stays in-process for live I/O.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from myrm_agent_harness.agent.meta_tools.bash._background_job_store_core import (
    BackgroundJobRecord,
    BackgroundJobStoreStatus,
    reconcile_orphaned_job_ids,
)
from myrm_agent_harness.utils.db.sqlite import CACHE, harden_connection_sync

logger = logging.getLogger(__name__)

_STORE: BackgroundJobStore | None = None
_CONFIGURED_PATH: Path | None = None


class BackgroundJobStore:
    """Durable metadata store for background bash jobs."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path))
        harden_connection_sync(conn, CACHE, db_path=self.db_path)
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS background_jobs (
                    job_id TEXT PRIMARY KEY,
                    pid INTEGER,
                    session_id TEXT NOT NULL,
                    command TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at REAL NOT NULL,
                    completed_at REAL,
                    exit_code INTEGER,
                    error_category TEXT,
                    finish_processed INTEGER NOT NULL DEFAULT 0,
                    vault_log_ref TEXT,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_background_jobs_session ON background_jobs(session_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_background_jobs_status ON background_jobs(status)"
            )

    @staticmethod
    def new_job_id() -> str:
        return uuid4().hex

    def insert_running(
        self,
        *,
        job_id: str,
        pid: int,
        session_id: str,
        command: str,
        started_at: float,
    ) -> None:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO background_jobs (
                    job_id, pid, session_id, command, status, started_at,
                    finish_processed, updated_at
                ) VALUES (?, ?, ?, ?, 'running', ?, 0, ?)
                """,
                (job_id, pid, session_id, command, started_at, now),
            )

    def update_terminal(
        self,
        job_id: str,
        *,
        status: BackgroundJobStoreStatus,
        exit_code: int | None,
        error_category: str | None,
        completed_at: float | None,
        vault_log_ref: str | None = None,
    ) -> None:
        now = time.time()
        with self._connect() as conn:
            if vault_log_ref is not None:
                conn.execute(
                    """
                    UPDATE background_jobs
                    SET status = ?, exit_code = ?, error_category = ?,
                        completed_at = ?, vault_log_ref = COALESCE(?, vault_log_ref),
                        updated_at = ?
                    WHERE job_id = ?
                    """,
                    (status, exit_code, error_category, completed_at, vault_log_ref, now, job_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE background_jobs
                    SET status = ?, exit_code = ?, error_category = ?,
                        completed_at = ?, updated_at = ?
                    WHERE job_id = ?
                    """,
                    (status, exit_code, error_category, completed_at, now, job_id),
                )

    def set_vault_log_ref(self, job_id: str, vault_log_ref: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE background_jobs SET vault_log_ref = ?, updated_at = ? WHERE job_id = ?",
                (vault_log_ref, time.time(), job_id),
            )

    def try_claim_finish(self, job_id: str) -> bool:
        """Atomically mark finish processed; returns True only for the first claim."""
        now = time.time()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE background_jobs
                SET finish_processed = 1, updated_at = ?
                WHERE job_id = ? AND finish_processed = 0 AND status = 'exited'
                """,
                (now, job_id),
            )
            return cursor.rowcount == 1

    def try_claim_finish_by_session_pid(self, session_id: str, pid: int) -> bool:
        """Legacy dedupe path when job_id is unknown (pre-store rows)."""
        now = time.time()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE background_jobs
                SET finish_processed = 1, updated_at = ?
                WHERE session_id = ? AND pid = ? AND finish_processed = 0 AND status = 'exited'
                """,
                (now, session_id, pid),
            )
            return cursor.rowcount == 1

    def mark_orphaned(self, job_id: str) -> None:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE background_jobs
                SET status = 'orphaned', completed_at = COALESCE(completed_at, ?), updated_at = ?
                WHERE job_id = ? AND status = 'running'
                """,
                (now, now, job_id),
            )

    def reconcile_running_jobs(self, live_pids: frozenset[int]) -> int:
        records = self.list_recent(limit=500)
        running_ids = frozenset(r.job_id for r in records if r.status == "running")
        by_id = {r.job_id: r for r in records}
        to_orphan = reconcile_orphaned_job_ids(running_ids, live_pids, records_by_job_id=by_id)
        for job_id in to_orphan:
            self.mark_orphaned(job_id)
        if to_orphan:
            logger.info("Background job store reconciled %d orphaned job(s)", len(to_orphan))
        return len(to_orphan)

    def get_by_job_id(self, job_id: str) -> BackgroundJobRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM background_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def get_by_pid(self, pid: int) -> BackgroundJobRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM background_jobs WHERE pid = ? ORDER BY started_at DESC LIMIT 1",
                (pid,),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def list_recent(self, *, limit: int = 100, session_id: str | None = None) -> list[BackgroundJobRecord]:
        with self._connect() as conn:
            if session_id:
                rows = conn.execute(
                    """
                    SELECT * FROM background_jobs
                    WHERE session_id = ?
                    ORDER BY started_at DESC
                    LIMIT ?
                    """,
                    (session_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM background_jobs
                    ORDER BY started_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [self._row_to_record(row) for row in rows if row is not None]

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> BackgroundJobRecord:
        status_raw = str(row["status"])
        status: BackgroundJobStoreStatus
        if status_raw in ("running", "exited", "killed", "orphaned"):
            status = status_raw  # type: ignore[assignment]
        else:
            status = "exited"
        return BackgroundJobRecord(
            job_id=str(row["job_id"]),
            pid=int(row["pid"]) if row["pid"] is not None else None,
            session_id=str(row["session_id"]),
            command=str(row["command"]),
            status=status,
            started_at=float(row["started_at"]),
            completed_at=float(row["completed_at"]) if row["completed_at"] is not None else None,
            exit_code=int(row["exit_code"]) if row["exit_code"] is not None else None,
            error_category=str(row["error_category"]) if row["error_category"] is not None else None,
            finish_processed=bool(row["finish_processed"]),
            vault_log_ref=str(row["vault_log_ref"]) if row["vault_log_ref"] is not None else None,
        )


def configure_background_job_store(db_path: str | Path) -> BackgroundJobStore:
    """Configure the process-wide BackgroundJobStore (idempotent)."""
    global _STORE, _CONFIGURED_PATH
    resolved = Path(db_path).expanduser().resolve()
    if _STORE is not None and _CONFIGURED_PATH == resolved:
        return _STORE
    _CONFIGURED_PATH = resolved
    _STORE = BackgroundJobStore(resolved)
    return _STORE


def get_background_job_store() -> BackgroundJobStore | None:
    """Return configured store, or lazily bind from workspace storage root."""
    global _STORE
    if _STORE is not None:
        return _STORE
    if _CONFIGURED_PATH is not None:
        _STORE = BackgroundJobStore(_CONFIGURED_PATH)
        return _STORE
    try:
        from myrm_agent_harness.toolkits.code_execution.workspace.storage_root_bind import (
            workspace_storage_fs_root_strict,
        )

        root = workspace_storage_fs_root_strict()
        return configure_background_job_store(root / ".myrm" / "background_jobs.db")
    except RuntimeError:
        return None


def reset_background_job_store_for_tests() -> None:
    """Clear singleton (tests only)."""
    global _STORE, _CONFIGURED_PATH
    _STORE = None
    _CONFIGURED_PATH = None


__all__ = [
    "BackgroundJobStore",
    "configure_background_job_store",
    "get_background_job_store",
    "reset_background_job_store_for_tests",
]
