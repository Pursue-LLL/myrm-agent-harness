"""[POS]: src/myrm_agent_harness/toolkits/memory/decisions/db.py
[INPUT]: Filepath to SQLite database and query parameters.
[OUTPUT]: Robust WAL connection, DDL migrations, and low-level record persistence operations.
"""

import asyncio
import sqlite3
from pathlib import Path

from .models import CandidateStatus, DecisionRecord, DecisionStatus, PendingDecisionCandidate


class DecisionDatabase:
    """Manages SQLite tables, WAL pragmas, and transactional queries for decisions."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self._lock = asyncio.Lock()
        self._ensure_tables()

    def _get_connection(self) -> sqlite3.Connection:
        """Create a sqlite3 connection configured with WAL and busy timeout."""
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _ensure_tables(self) -> None:
        """Initialize schema tables and indexes idempotently."""
        conn = self._get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS myrm_decisions (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        text TEXT NOT NULL,
                        rationale TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL DEFAULT 'active',
                        supersedes_id TEXT,
                        superseded_by TEXT,
                        scope TEXT NOT NULL DEFAULT 'project',
                        project_key TEXT NOT NULL DEFAULT 'default',
                        source_event TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS myrm_pending_candidates (
                        id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        text TEXT NOT NULL,
                        rationale TEXT NOT NULL DEFAULT '',
                        supersedes_id TEXT,
                        status TEXT NOT NULL DEFAULT 'pending',
                        project_key TEXT NOT NULL DEFAULT 'default',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_decisions_proj_status ON myrm_decisions(project_key, status);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_decisions_supersedes ON myrm_decisions(supersedes_id);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_candidates_sess_status ON myrm_pending_candidates(session_id, status);"
                )
        finally:
            conn.close()

    async def get_decision(self, decision_id: str) -> DecisionRecord | None:
        """Fetch a single decision record by ID."""
        async with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT * FROM myrm_decisions WHERE id = ?;", (decision_id,)
                ).fetchone()
                if not row:
                    return None
                return self._row_to_decision(row)
            finally:
                conn.close()

    async def save_decision(self, record: DecisionRecord) -> None:
        """Insert or replace a decision record."""
        async with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO myrm_decisions (
                            id, title, text, rationale, status, supersedes_id, superseded_by,
                            scope, project_key, source_event, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            record.id,
                            record.title,
                            record.text,
                            record.rationale,
                            str(record.status),
                            record.supersedes_id,
                            record.superseded_by,
                            record.scope,
                            record.project_key,
                            record.source_event,
                            record.created_at,
                            record.updated_at,
                        ),
                    )
            finally:
                conn.close()

    async def list_decisions(
        self,
        project_key: str = "default",
        status: DecisionStatus | None = None,
        limit: int = 100,
    ) -> list[DecisionRecord]:
        """List decisions for a project, optionally filtered by status."""
        async with self._lock:
            conn = self._get_connection()
            try:
                if status:
                    rows = conn.execute(
                        """
                        SELECT * FROM myrm_decisions
                        WHERE project_key = ? AND status = ?
                        ORDER BY updated_at DESC LIMIT ?;
                        """,
                        (project_key, str(status), limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT * FROM myrm_decisions
                        WHERE project_key = ?
                        ORDER BY updated_at DESC LIMIT ?;
                        """,
                        (project_key, limit),
                    ).fetchall()
                return [self._row_to_decision(r) for r in rows]
            finally:
                conn.close()

    async def save_candidate(self, candidate: PendingDecisionCandidate) -> None:
        """Insert or update a pending candidate."""
        async with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO myrm_pending_candidates (
                            id, session_id, title, text, rationale, supersedes_id,
                            status, project_key, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            candidate.id,
                            candidate.session_id,
                            candidate.title,
                            candidate.text,
                            candidate.rationale,
                            candidate.supersedes_id,
                            str(candidate.status),
                            candidate.project_key,
                            candidate.created_at,
                            candidate.updated_at,
                        ),
                    )
            finally:
                conn.close()

    async def get_candidate(self, candidate_id: str) -> PendingDecisionCandidate | None:
        """Fetch candidate by ID."""
        async with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT * FROM myrm_pending_candidates WHERE id = ?;", (candidate_id,)
                ).fetchone()
                if not row:
                    return None
                return self._row_to_candidate(row)
            finally:
                conn.close()

    async def list_pending_candidates(
        self,
        session_id: str,
        project_key: str = "default",
    ) -> list[PendingDecisionCandidate]:
        """List active pending candidates for a session."""
        async with self._lock:
            conn = self._get_connection()
            try:
                rows = conn.execute(
                    """
                    SELECT * FROM myrm_pending_candidates
                    WHERE session_id = ? AND project_key = ? AND status = 'pending'
                    ORDER BY created_at ASC;
                    """,
                    (session_id, project_key),
                ).fetchall()
                return [self._row_to_candidate(r) for r in rows]
            finally:
                conn.close()

    def _row_to_decision(self, row: sqlite3.Row) -> DecisionRecord:
        return DecisionRecord(
            id=row["id"],
            title=row["title"],
            text=row["text"],
            rationale=row["rationale"],
            status=DecisionStatus(row["status"]),
            supersedes_id=row["supersedes_id"],
            superseded_by=row["superseded_by"],
            scope=row["scope"],
            project_key=row["project_key"],
            source_event=row["source_event"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_candidate(self, row: sqlite3.Row) -> PendingDecisionCandidate:
        return PendingDecisionCandidate(
            id=row["id"],
            session_id=row["session_id"],
            title=row["title"],
            text=row["text"],
            rationale=row["rationale"],
            supersedes_id=row["supersedes_id"],
            status=CandidateStatus(row["status"]),
            project_key=row["project_key"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
