"""SQLite storage adapter and schema manager for safe episodic forget.

[INPUT]
- SQLite connection, database path, episodic and cross-tier memory tables.

[OUTPUT]
- SqliteEpisodicMemoryStore providing atomic schema management and immediate write locks.

[POS]
- Storage adapter ensuring schema fidelity and multi-tier parent-child persistence.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class SqliteEpisodicMemoryStore:
    """Manages SQLite schema and immediate write locks for memory tiers."""

    SCHEMA_STATEMENTS: tuple[str, ...] = (
        """
        CREATE TABLE IF NOT EXISTS episodic_memory (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            scope TEXT NOT NULL DEFAULT 'session',
            content TEXT NOT NULL,
            timestamp REAL NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS working_memory (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp REAL NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS annotations (
            id TEXT PRIMARY KEY,
            memory_id TEXT NOT NULL,
            note TEXT NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS memory_embeddings (
            id TEXT PRIMARY KEY,
            memory_id TEXT NOT NULL,
            embedding_json TEXT NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS gists (
            id TEXT PRIMARY KEY,
            memory_id TEXT NOT NULL,
            gist TEXT NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS vec_episodes (
            id TEXT PRIMARY KEY,
            memory_id TEXT NOT NULL,
            embedding BLOB NOT NULL
        );
        """,
    )

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None
        self._ensure_initialized()

    def _ensure_initialized(self) -> None:
        conn = self.get_connection()
        cur = conn.cursor()
        for stmt in self.SCHEMA_STATEMENTS:
            cur.execute(stmt)
        conn.commit()

    def get_connection(self) -> sqlite3.Connection:
        """Return the managed SQLite connection instance with row factory configured."""
        if self._conn is None:
            self._conn = sqlite3.connect(
                self._db_path,
                check_same_thread=False,
                isolation_level=None,
            )
            self._conn.row_factory = sqlite3.Row
        return self._conn

    @contextmanager
    def immediate_transaction(self) -> Iterator[sqlite3.Connection]:
        """Execute a block under BEGIN IMMEDIATE lock, rolling back on error."""
        conn = self.get_connection()
        in_tx = conn.in_transaction
        if not in_tx:
            conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            if not in_tx:
                conn.commit()
        except Exception:
            if not in_tx:
                conn.rollback()
            raise

    def close(self) -> None:
        """Close the underlying connection."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
