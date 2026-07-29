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

from .types import CompileCircuitState, CompileRunSnapshot


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
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute(
                """
                INSERT OR IGNORE INTO compile_circuit (id, state)
                VALUES (1, 'running')
                """
            )

    def get_snapshot(self) -> CompileRunSnapshot:
        with self._conn() as conn:
            row = conn.execute("SELECT state, pause_reason, primary_error_kind FROM compile_circuit WHERE id = 1").fetchone()
            if row is None:
                return CompileRunSnapshot(state="running")
            state: CompileCircuitState = "paused" if row["state"] == "paused" else "running"
            return CompileRunSnapshot(
                state=state,
                pause_reason=row["pause_reason"] or "",
                primary_error_kind=row["primary_error_kind"] or "",
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
                """
            )
