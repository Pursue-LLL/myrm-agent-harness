"""Persistent compile circuit state (running/paused) per wiki vault.

[INPUT]
.types::CompileRunSnapshot, CompileCircuitState (POS: compile circuit DTO)
utils.db.sqlite::harden_connection_sync (POS: hardened SQLite connections)

[OUTPUT]
CompileCircuitStore: pause/resume/is_paused/get_snapshot for compile worker

[POS]
Wiki compile circuit store. Persists running/paused state beside the ingestion queue database.
"""

from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path

from .types import CompileCircuitState, CompilePhase, CompileRunSnapshot


class CompileCircuitStore:
    """SQLite-backed compile pause/resume state stored alongside the ingestion queue."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._ensure_table()

    @contextlib.contextmanager
    def _conn(self):
        from myrm_agent_harness.utils.db.sqlite import DEFAULT, harden_connection_sync

        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        harden_connection_sync(conn, DEFAULT, db_path=self._db_path)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _ensure_table(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS compile_circuit (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    state TEXT NOT NULL DEFAULT 'running',
                    pause_reason TEXT NOT NULL DEFAULT '',
                    primary_error_kind TEXT NOT NULL DEFAULT '',
                    phase TEXT NOT NULL DEFAULT 'idle',
                    facet_count INTEGER NOT NULL DEFAULT 0,
                    warning_count INTEGER NOT NULL DEFAULT 0,
                    survey_skipped INTEGER NOT NULL DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute(
                """
                INSERT OR IGNORE INTO compile_circuit (id, state)
                VALUES (1, 'running')
                """
            )
            self._migrate_schema(conn)

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(compile_circuit)").fetchall()}
        if "phase" not in columns:
            conn.execute("ALTER TABLE compile_circuit ADD COLUMN phase TEXT NOT NULL DEFAULT 'idle'")
        if "facet_count" not in columns:
            conn.execute("ALTER TABLE compile_circuit ADD COLUMN facet_count INTEGER NOT NULL DEFAULT 0")
        if "warning_count" not in columns:
            conn.execute("ALTER TABLE compile_circuit ADD COLUMN warning_count INTEGER NOT NULL DEFAULT 0")
        if "survey_skipped" not in columns:
            conn.execute("ALTER TABLE compile_circuit ADD COLUMN survey_skipped INTEGER NOT NULL DEFAULT 0")

    def get_snapshot(self) -> CompileRunSnapshot:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT state, pause_reason, primary_error_kind, phase, facet_count, warning_count, survey_skipped
                FROM compile_circuit
                WHERE id = 1
                """
            ).fetchone()
            if row is None:
                return CompileRunSnapshot(state="running")
            state: CompileCircuitState = "paused" if row["state"] == "paused" else "running"
            phase_value = row["phase"] or "idle"
            phase: CompilePhase
            if phase_value in {"idle", "structure_survey", "semantic_compile", "postprocess"}:
                phase = phase_value  # type: ignore[assignment]
            else:
                phase = "idle"
            return CompileRunSnapshot(
                state=state,
                pause_reason=row["pause_reason"] or "",
                primary_error_kind=row["primary_error_kind"] or "",
                phase=phase,
                facet_count=int(row["facet_count"] or 0),
                warning_count=int(row["warning_count"] or 0),
                survey_skipped=bool(row["survey_skipped"]),
            )

    def is_paused(self) -> bool:
        return self.get_snapshot().state == "paused"

    def pause(self, reason: str, primary_error_kind: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE compile_circuit
                SET state = 'paused',
                    pause_reason = ?,
                    primary_error_kind = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
                """,
                (reason, primary_error_kind),
            )

    def resume(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE compile_circuit
                SET state = 'running',
                    pause_reason = '',
                    primary_error_kind = '',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
                """,
            )

    def set_phase(
        self,
        phase: CompilePhase,
        *,
        facet_count: int = 0,
        warning_count: int = 0,
        survey_skipped: bool = False,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE compile_circuit
                SET phase = ?,
                    facet_count = ?,
                    warning_count = ?,
                    survey_skipped = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
                """,
                (phase, facet_count, warning_count, 1 if survey_skipped else 0),
            )
