"""SQLite storage and cold-start projection manager.

[INPUT]
- SQLite connection, database path, transcript entries, and live session messages.
- TranscriptAdoptionEngine for duplicate disambiguation and reconciliation.

[OUTPUT]
- SqliteTranscriptProjectionStore managing cold-start projection and idempotent bootstrapping.

[POS]
- Storage and projection lifecycle manager for Item 150 SqliteTranscriptProjectionSuite.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from .adoption_engine import TranscriptAdoptionEngine
from .models import (
    BootstrapContext,
    BootstrapResult,
    SessionMessage,
    TranscriptEntry,
)


class SqliteTranscriptProjectionStore:
    """Manages SQLite transcript SSOT tables and idempotent cold-start bootstrap projection."""

    SCHEMA_STATEMENTS: tuple[str, ...] = (
        """
        CREATE TABLE IF NOT EXISTS transcript_entries (
            entry_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at_ms INTEGER,
            parent_id TEXT
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS session_messages (
            message_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp_ms INTEGER,
            transcript_entry_id TEXT
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS session_projections (
            session_id TEXT PRIMARY KEY,
            bootstrapped_at REAL NOT NULL,
            imported_messages INTEGER NOT NULL
        );
        """,
    )

    def __init__(
        self,
        db_path: str | Path = ":memory:",
        adoption_engine: TranscriptAdoptionEngine | None = None,
    ) -> None:
        self._db_path = str(db_path)
        self._adoption_engine = adoption_engine or TranscriptAdoptionEngine()
        self._conn: sqlite3.Connection | None = None
        self._ensure_initialized()

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

    def _ensure_initialized(self) -> None:
        conn = self.get_connection()
        cur = conn.cursor()
        for stmt in self.SCHEMA_STATEMENTS:
            cur.execute(stmt)

    def append_transcript_entries(self, entries: list[TranscriptEntry]) -> None:
        """Append transcript entries to the SQLite SSOT table."""
        if not entries:
            return
        conn = self.get_connection()
        cur = conn.cursor()
        for e in entries:
            cur.execute(
                """
                INSERT OR REPLACE INTO transcript_entries
                (entry_id, session_id, seq, role, content, created_at_ms, parent_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (e.entry_id, e.session_id, e.seq, e.role, e.content, e.created_at_ms, e.parent_id),
            )

    def ingest_live_messages(self, messages: list[SessionMessage]) -> None:
        """Ingest live host session messages into the session memory store."""
        if not messages:
            return
        conn = self.get_connection()
        cur = conn.cursor()
        for m in messages:
            cur.execute(
                """
                INSERT OR REPLACE INTO session_messages
                (message_id, session_id, seq, role, content, timestamp_ms, transcript_entry_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (m.message_id, m.session_id, m.seq, m.role, m.content, m.timestamp_ms, m.transcript_entry_id),
            )

    def get_session_messages(self, session_id: str) -> list[SessionMessage]:
        """Fetch all stored session messages in sequence order."""
        conn = self.get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT message_id, session_id, seq, role, content, timestamp_ms, transcript_entry_id
            FROM session_messages
            WHERE session_id = ?
            ORDER BY seq ASC
            """,
            (session_id,),
        )
        rows = cur.fetchall()
        return [
            SessionMessage(
                message_id=str(r["message_id"]),
                session_id=str(r["session_id"]),
                seq=int(r["seq"]),
                role=str(r["role"]),
                content=str(r["content"]),
                timestamp_ms=int(r["timestamp_ms"]) if r["timestamp_ms"] is not None else None,
                transcript_entry_id=str(r["transcript_entry_id"]) if r["transcript_entry_id"] is not None else None,
            )
            for r in rows
        ]

    def get_transcript_entries(self, session_id: str) -> list[TranscriptEntry]:
        """Fetch all visible transcript entries for a given session."""
        conn = self.get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT entry_id, session_id, seq, role, content, created_at_ms, parent_id
            FROM transcript_entries
            WHERE session_id = ?
            ORDER BY seq ASC
            """,
            (session_id,),
        )
        rows = cur.fetchall()
        return [
            TranscriptEntry(
                entry_id=str(r["entry_id"]),
                session_id=str(r["session_id"]),
                seq=int(r["seq"]),
                role=str(r["role"]),
                content=str(r["content"]),
                created_at_ms=int(r["created_at_ms"]) if r["created_at_ms"] is not None else None,
                parent_id=str(r["parent_id"]) if r["parent_id"] is not None else None,
            )
            for r in rows
        ]

    def is_bootstrapped(self, session_id: str) -> bool:
        """Check if cold-start bootstrap has already run for this session."""
        conn = self.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM session_projections WHERE session_id = ?", (session_id,))
        return cur.fetchone() is not None

    def bootstrap_session(self, context: BootstrapContext) -> BootstrapResult:
        """Perform idempotent cold-start projection bootstrap from SQLite transcript SSOT."""
        conn = self.get_connection()
        cur = conn.cursor()

        # Check existing bootstrap status
        cur.execute(
            "SELECT imported_messages FROM session_projections WHERE session_id = ?",
            (context.session_id,),
        )
        existing_proj = cur.fetchone()
        already_bootstrapped = existing_proj is not None

        transcript_entries = self.get_transcript_entries(context.session_id)
        live_messages = self.get_session_messages(context.session_id)

        # If already bootstrapped and message count unchanged, return idempotent result immediately
        if already_bootstrapped and len(live_messages) >= len(transcript_entries):
            return BootstrapResult(
                session_id=context.session_id,
                bootstrapped=True,
                imported_messages=int(existing_proj["imported_messages"]),
                already_bootstrapped=True,
                decisions=(),
            )

        # Case A: Live messages exist -> reconcile and adopt transcript entries
        if live_messages:
            decisions = self._adoption_engine.reconcile(
                messages=live_messages,
                entries=transcript_entries,
                tolerance_ms=context.tolerance_ms,
            )
            # Update adopted transcript_entry_id values
            for dec in decisions:
                if dec.transcript_entry_id is not None:
                    cur.execute(
                        "UPDATE session_messages SET transcript_entry_id = ? WHERE message_id = ?",
                        (dec.transcript_entry_id, dec.message_id),
                    )

            if not already_bootstrapped:
                cur.execute(
                    """
                    INSERT INTO session_projections (session_id, bootstrapped_at, imported_messages)
                    VALUES (?, ?, ?)
                    """,
                    (context.session_id, time.time(), len(live_messages)),
                )

            return BootstrapResult(
                session_id=context.session_id,
                bootstrapped=True,
                imported_messages=len(live_messages),
                already_bootstrapped=already_bootstrapped,
                decisions=tuple(decisions),
            )

        # Case B: No session messages exist (pure cold-start projection from transcript)
        imported_count = 0
        for entry in transcript_entries:
            msg_id = f"msg_proj_{entry.entry_id}"
            cur.execute(
                """
                INSERT INTO session_messages
                (message_id, session_id, seq, role, content, timestamp_ms, transcript_entry_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    msg_id,
                    context.session_id,
                    entry.seq,
                    entry.role,
                    entry.content,
                    entry.created_at_ms,
                    entry.entry_id,
                ),
            )
            imported_count += 1

        cur.execute(
            """
            INSERT OR REPLACE INTO session_projections (session_id, bootstrapped_at, imported_messages)
            VALUES (?, ?, ?)
            """,
            (context.session_id, time.time(), imported_count),
        )

        return BootstrapResult(
            session_id=context.session_id,
            bootstrapped=True,
            imported_messages=imported_count,
            already_bootstrapped=already_bootstrapped,
            decisions=(),
        )

    def close(self) -> None:
        """Close connection."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
