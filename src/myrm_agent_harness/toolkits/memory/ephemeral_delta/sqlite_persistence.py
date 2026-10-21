"""SQLite persistence for ephemeral session deltas (Volume-backed crash recovery).

[INPUT]
- toolkits.memory.ephemeral_delta.models::DeltaActionKind, EphemeralDeltaItem

[OUTPUT]
- EphemeralDeltaSqlitePersistence: append/load/clear session deltas in memory.db

[POS]
Same DB file as relational memory store; survives process restart within a chat session.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

from myrm_agent_harness.toolkits.memory.ephemeral_delta.models import (
    DeltaActionKind,
    EphemeralDeltaItem,
)

logger = logging.getLogger(__name__)

_TABLE = "ephemeral_session_deltas"


class EphemeralDeltaSqlitePersistence:
    """Persist raw ephemeral deltas for session-scoped tail injection recovery."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path).expanduser().resolve()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {_TABLE} (
                    delta_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    target_key TEXT NOT NULL,
                    content TEXT NOT NULL,
                    action TEXT NOT NULL,
                    turn_index INTEGER NOT NULL DEFAULT 0,
                    timestamp TEXT NOT NULL,
                    source TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    seq INTEGER NOT NULL
                )
                """
            )
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{_TABLE}_session_seq ON {_TABLE}(session_id, seq)")
            conn.commit()

    def append_delta(self, session_id: str, delta: EphemeralDeltaItem) -> None:
        normalized_session = session_id.strip()
        if not normalized_session:
            return
        with self._lock, self._connect() as conn:
            max_seq_row = conn.execute(
                f"SELECT COALESCE(MAX(seq), 0) FROM {_TABLE} WHERE session_id = ?",
                (normalized_session,),
            ).fetchone()
            max_seq = int(max_seq_row[0]) if max_seq_row else 0
            conn.execute(
                f"""
                INSERT OR REPLACE INTO {_TABLE} (
                    delta_id, session_id, target_key, content, action,
                    turn_index, timestamp, source, confidence, seq
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    delta.delta_id,
                    normalized_session,
                    delta.target_key,
                    delta.content,
                    delta.action.value,
                    delta.turn_index,
                    delta.timestamp,
                    delta.source,
                    delta.confidence,
                    max_seq + 1,
                ),
            )
            conn.commit()

    def load_raw_deltas(self, session_id: str) -> list[EphemeralDeltaItem]:
        normalized_session = session_id.strip()
        if not normalized_session:
            return []
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT delta_id, target_key, content, action, turn_index,
                       timestamp, source, confidence
                FROM {_TABLE}
                WHERE session_id = ?
                ORDER BY seq ASC
                """,
                (normalized_session,),
            ).fetchall()
        items: list[EphemeralDeltaItem] = []
        for row in rows:
            action_raw = str(row[3]).strip().lower()
            if action_raw == "retract":
                action = DeltaActionKind.RETRACT
            elif action_raw in {"add_fact", "add"}:
                action = DeltaActionKind.ADD_FACT
            else:
                action = DeltaActionKind.OVERRIDE
            items.append(
                EphemeralDeltaItem(
                    delta_id=str(row[0]),
                    target_key=str(row[1]),
                    content=str(row[2]),
                    action=action,
                    turn_index=int(row[4]),
                    timestamp=str(row[5]),
                    source=str(row[6]),
                    confidence=float(row[7]),
                )
            )
        return items

    def clear_session(self, session_id: str) -> None:
        normalized_session = session_id.strip()
        if not normalized_session:
            return
        with self._lock, self._connect() as conn:
            conn.execute(
                f"DELETE FROM {_TABLE} WHERE session_id = ?",
                (normalized_session,),
            )
            conn.commit()
