"""SQLite incremental state projector for fine-grained multi-part event streams.

Projects streaming PartEvents atomically into relational SQLite tables, providing
resilient crash-recovery facts and real-time structured session storage.

[OUTPUT]
- SQLitePartProjector: Relational state projector consuming PartEvents.

[INPUT]
- __future__
- asyncio
- json
- sqlite3
- time
- typing

[OUTPUT]
- SQLitePartProjector

[POS]
SQLite incremental state projector for fine-grained multi-part event streams.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from typing import cast

from myrm_agent_harness.agent.event_stream.part_types import (
    EventKind,
    PartEvent,
    PartStatus,
)


class SQLitePartProjector:
    """Async relational projector translating granular PartEvents into SQLite state."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path: str = db_path
        self._conn: sqlite3.Connection = sqlite3.connect(
            self.db_path, check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        self._lock: asyncio.Lock = asyncio.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                );

                CREATE TABLE IF NOT EXISTS parts (
                    part_id TEXT PRIMARY KEY,
                    message_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    part_kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    duration_ms REAL NOT NULL DEFAULT 0.0,
                    sequence_number INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY(message_id) REFERENCES messages(message_id)
                );

                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    part_id TEXT NOT NULL,
                    part_kind TEXT NOT NULL,
                    event_kind TEXT NOT NULL,
                    sequence_number INTEGER NOT NULL,
                    delta TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    timestamp REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_parts_msg ON parts(message_id);
                CREATE INDEX IF NOT EXISTS idx_parts_session ON parts(session_id);
                CREATE INDEX IF NOT EXISTS idx_events_seq ON events(sequence_number);
                """
            )

    async def project_event(self, event: PartEvent) -> None:
        """Atomically project an inbound PartEvent into SQLite tables."""
        async with self._lock:
            now = time.time()
            payload_str = json.dumps(event.payload, ensure_ascii=False)

            with self._conn:
                # 1. Upsert session
                self._conn.execute(
                    """
                    INSERT INTO sessions (session_id, status, created_at, updated_at)
                    VALUES (?, 'active', ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET updated_at = ?
                    """,
                    (event.session_id, now, now, now),
                )

                # 2. Upsert message (default role assistant for parts)
                self._conn.execute(
                    """
                    INSERT INTO messages (message_id, session_id, role, created_at)
                    VALUES (?, ?, 'assistant', ?)
                    ON CONFLICT(message_id) DO NOTHING
                    """,
                    (event.message_id, event.session_id, now),
                )

                # 3. Insert event log
                self._conn.execute(
                    """
                    INSERT INTO events (
                        event_id, session_id, message_id, part_id,
                        part_kind, event_kind, sequence_number, delta,
                        payload_json, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.session_id,
                        event.message_id,
                        event.part_id,
                        event.part_kind.value,
                        event.event_kind.value,
                        event.sequence_number,
                        event.delta,
                        payload_str,
                        event.timestamp,
                    ),
                )

                # 4. Project state transitions based on event_kind
                if event.event_kind == EventKind.PART_APPEND:
                    initial_content = event.delta or str(event.payload.get("content", ""))
                    self._conn.execute(
                        """
                        INSERT INTO parts (
                            part_id, message_id, session_id, part_kind,
                            status, content, metadata_json, duration_ms,
                            sequence_number, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(part_id) DO UPDATE SET
                            content = content || excluded.content,
                            updated_at = excluded.updated_at
                        """,
                        (
                            event.part_id,
                            event.message_id,
                            event.session_id,
                            event.part_kind.value,
                            PartStatus.IN_PROGRESS.value,
                            initial_content,
                            payload_str,
                            float(cast(float, event.payload.get("duration_ms", 0.0))),
                            event.sequence_number,
                            now,
                            now,
                        ),
                    )

                elif event.event_kind == EventKind.PART_DELTA:
                    self._conn.execute(
                        """
                        UPDATE parts
                        SET content = content || ?,
                            updated_at = ?
                        WHERE part_id = ?
                        """,
                        (event.delta, now, event.part_id),
                    )

                elif event.event_kind == EventKind.PART_COMPLETE:
                    final_status = str(
                        event.payload.get("status", PartStatus.COMPLETED.value)
                    )
                    duration_ms = float(cast(float, event.payload.get("duration_ms", 0.0)))
                    self._conn.execute(
                        """
                        UPDATE parts
                        SET status = ?,
                            duration_ms = CASE WHEN ? > 0.0 THEN ? ELSE duration_ms END,
                            metadata_json = ?,
                            updated_at = ?
                        WHERE part_id = ?
                        """,
                        (
                            final_status,
                            duration_ms,
                            duration_ms,
                            payload_str,
                            now,
                            event.part_id,
                        ),
                    )

    async def get_parts_for_message(
        self, message_id: str
    ) -> list[dict[str, str | float | int]]:
        """Retrieve all projected parts belonging to a message in topological order."""
        async with self._lock:
            cursor = self._conn.execute(
                """
                SELECT part_id, message_id, session_id, part_kind, status,
                       content, metadata_json, duration_ms, sequence_number
                FROM parts
                WHERE message_id = ?
                ORDER BY sequence_number ASC
                """,
                (message_id,),
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_session_parts(
        self, session_id: str
    ) -> list[dict[str, str | float | int]]:
        """Retrieve all projected parts in an entire session ordered by sequence number."""
        async with self._lock:
            cursor = self._conn.execute(
                """
                SELECT part_id, message_id, session_id, part_kind, status,
                       content, metadata_json, duration_ms, sequence_number
                FROM parts
                WHERE session_id = ?
                ORDER BY sequence_number ASC
                """,
                (session_id,),
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    async def close(self) -> None:
        """Close SQLite database connection."""
        async with self._lock:
            self._conn.close()
