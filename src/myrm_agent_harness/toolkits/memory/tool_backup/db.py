"""[POS]: src/myrm_agent_harness/toolkits/memory/tool_backup/db.py
[INPUT]: SQLite connection or file path parameters for durable tool use index.
[OUTPUT]: ToolUseDatabase schema manager ensuring tables, indexes, and connection options.
"""

import contextlib
import sqlite3
from pathlib import Path


class ToolUseDatabase:
    """Manages SQLite schema and connection configuration for durable tool use index."""

    def __init__(self, db_path: Path | str = ":memory:") -> None:
        self.db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None

    def get_connection(self) -> sqlite3.Connection:
        """Return initialized connection configured with WAL and busy timeout."""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            if self.db_path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._init_schema(self._conn)
        return self._conn

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        """Initialize SQLite tables and high-performance audit query indexes."""
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS myrm_tool_uses (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                tool_call_id TEXT DEFAULT '',
                raw_input TEXT NOT NULL,
                raw_output TEXT NOT NULL,
                status TEXT NOT NULL,
                duration_ms REAL DEFAULT 0.0,
                created_at_epoch REAL NOT NULL,
                is_truncated INTEGER DEFAULT 0,
                original_output_bytes INTEGER DEFAULT 0,
                metadata_json TEXT DEFAULT '{}'
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tool_uses_session
            ON myrm_tool_uses(session_id, created_at_epoch DESC)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tool_uses_name
            ON myrm_tool_uses(tool_name, created_at_epoch DESC)
            """
        )
        conn.commit()

    def close(self) -> None:
        """Close connection if open."""
        if self._conn is not None:
            with contextlib.suppress(sqlite3.DatabaseError):
                self._conn.close()
            self._conn = None
