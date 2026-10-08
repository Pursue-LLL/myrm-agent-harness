# [INPUT]: CommitWrite, ConversationRecord, DocumentRecord, DurableStorageProtocol, EntryRecord, StorageBackendKind, StorageWriteKind, TaskRecord
# [OUTPUT]: SqliteDurableStorage
# [POS]: agent/context_management/durable_storage/sqlite_durable_storage.py

"""SQLite relational durable storage backend with WAL mode and indexed query paths.

[INPUT]
- CommitWrite, ConversationRecord, DocumentRecord, EntryRecord, StorageBackendKind, StorageWriteKind, TaskRecord:
  Domain types from durable_storage_types.
- DurableStorageProtocol: Base storage contract.

[OUTPUT]
- SqliteDurableStorage: ACID relational storage engine with WAL journaling and indexed scans.

[POS]
Relational durable storage backend optimized for local CLI and desktop environments.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Sequence

from .durable_storage_protocol import DurableStorageProtocol
from .durable_storage_types import (
    CommitWrite,
    ConversationRecord,
    DocumentRecord,
    EntryRecord,
    StorageBackendKind,
    StorageWriteKind,
    TaskRecord,
)


class SqliteDurableStorage(DurableStorageProtocol):
    """ACID SQLite implementation supporting WAL journaling and indexed queries."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        if db_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._init_schema()

    @property
    def backend_kind(self) -> StorageBackendKind:
        return StorageBackendKind.SQLITE

    def _init_schema(self) -> None:
        """Initialize schema and configure WAL performance pragmas."""
        cur = self._conn.cursor()
        cur.execute("PRAGMA journal_mode = WAL")
        cur.execute("PRAGMA synchronous = NORMAL")
        cur.execute("PRAGMA foreign_keys = ON")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                owner_task_id TEXT,
                title TEXT,
                metadata TEXT,
                created_at REAL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS entries (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                kind TEXT NOT NULL,
                payload TEXT,
                created_at REAL
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_entries_conv_seq
            ON entries (conversation_id, seq)
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                checkpoint TEXT,
                abort_requested INTEGER NOT NULL,
                updated_at REAL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                content TEXT,
                updated_at REAL
            )
            """
        )
        self._conn.commit()

    def commit(self, writes: Sequence[CommitWrite]) -> int:
        """Atomically persist write batch inside a single SQLite transaction."""
        cur = self._conn.cursor()
        # Retrieve current sequence
        cur.execute("SELECT value FROM meta WHERE key = 'current_seq'")
        row = cur.fetchone()
        current_seq = int(row[0]) if row else 0
        new_seq = current_seq + 1

        for w in writes:
            now = time.time()
            if w.kind == StorageWriteKind.CONVERSATION:
                owner_id = str(w.payload.get("owner_task_id", "")) or None
                title = str(w.payload.get("title", ""))
                metadata = {
                    str(k): str(v)
                    for k, v in w.payload.items()
                    if k not in ("owner_task_id", "title") and v is not None
                }
                cur.execute(
                    """
                    INSERT OR REPLACE INTO conversations (id, owner_task_id, title, metadata, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (w.id, owner_id, title, json.dumps(metadata, sort_keys=True), now),
                )

            elif w.kind == StorageWriteKind.ENTRY:
                conv_id = str(w.payload.get("conversation_id", ""))
                kind = str(w.payload.get("kind", "message"))
                payload_data = dict(w.payload)
                payload_data.pop("conversation_id", None)
                payload_data.pop("kind", None)
                cur.execute(
                    """
                    INSERT OR REPLACE INTO entries (id, conversation_id, seq, kind, payload, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (w.id, conv_id, new_seq, kind, json.dumps(payload_data, sort_keys=True), now),
                )

            elif w.kind == StorageWriteKind.TASK:
                conv_id = str(w.payload.get("conversation_id", ""))
                kind = str(w.payload.get("kind", "task"))
                status = str(w.payload.get("status", "pending"))
                abort_req = 1 if bool(w.payload.get("abort_requested", False)) else 0
                checkpoint = dict(w.payload)
                for k in ("conversation_id", "kind", "status", "abort_requested"):
                    checkpoint.pop(k, None)
                cur.execute(
                    """
                    INSERT OR REPLACE INTO tasks (id, conversation_id, kind, status, checkpoint, abort_requested, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (w.id, conv_id, kind, status, json.dumps(checkpoint, sort_keys=True), abort_req, now),
                )

            elif w.kind == StorageWriteKind.DOCUMENT:
                version = int(w.payload.get("version", 1))
                content = dict(w.payload)
                content.pop("version", None)
                cur.execute(
                    """
                    INSERT OR REPLACE INTO documents (id, version, content, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (w.id, version, json.dumps(content, sort_keys=True), now),
                )

        cur.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('current_seq', ?)",
            (str(new_seq),),
        )
        self._conn.commit()
        return new_seq

    def get_conversation(self, conversation_id: str) -> ConversationRecord | None:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT id, owner_task_id, title, metadata, created_at FROM conversations WHERE id = ?",
            (conversation_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        meta_dict = json.loads(row[3]) if row[3] else {}
        return ConversationRecord(
            id=row[0],
            owner_task_id=row[1],
            title=row[2] or "",
            metadata=meta_dict,
            created_at=row[4],
        )

    def get_entry(self, entry_id: str) -> EntryRecord | None:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT id, conversation_id, seq, kind, payload, created_at FROM entries WHERE id = ?",
            (entry_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        payload_dict = json.loads(row[4]) if row[4] else {}
        return EntryRecord(
            id=row[0],
            conversation_id=row[1],
            seq=row[2],
            kind=row[3],
            payload=payload_dict,
            created_at=row[5],
        )

    def list_entries(
        self,
        conversation_id: str,
        limit: int = 100,
        after_seq: int = 0,
    ) -> Sequence[EntryRecord]:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT id, conversation_id, seq, kind, payload, created_at
            FROM entries
            WHERE conversation_id = ? AND seq > ?
            ORDER BY seq ASC
            LIMIT ?
            """,
            (conversation_id, after_seq, limit),
        )
        rows = cur.fetchall()
        entries: list[EntryRecord] = []
        for r in rows:
            payload_dict = json.loads(r[4]) if r[4] else {}
            entries.append(
                EntryRecord(
                    id=r[0],
                    conversation_id=r[1],
                    seq=r[2],
                    kind=r[3],
                    payload=payload_dict,
                    created_at=r[5],
                )
            )
        return entries

    def get_task(self, task_id: str) -> TaskRecord | None:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT id, conversation_id, kind, status, checkpoint, abort_requested, updated_at FROM tasks WHERE id = ?",
            (task_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        cp_dict = json.loads(row[4]) if row[4] else {}
        return TaskRecord(
            id=row[0],
            conversation_id=row[1],
            kind=row[2],
            status=row[3],
            checkpoint=cp_dict,
            abort_requested=bool(row[5]),
            updated_at=row[6],
        )

    def get_document(self, document_id: str) -> DocumentRecord | None:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT id, version, content, updated_at FROM documents WHERE id = ?",
            (document_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        content_dict = json.loads(row[2]) if row[2] else {}
        return DocumentRecord(
            id=row[0],
            version=row[1],
            content=content_dict,
            updated_at=row[3],
        )

    def get_current_seq(self) -> int:
        cur = self._conn.cursor()
        cur.execute("SELECT value FROM meta WHERE key = 'current_seq'")
        row = cur.fetchone()
        return int(row[0]) if row else 0

    def reopen(self) -> None:
        """Close connection and reopen to verify on-disk consistency."""
        self._conn.close()
        self._conn = sqlite3.connect(self._db_path)
        self._init_schema()

    def close(self) -> None:
        """Execute WAL checkpoint truncate and close connection."""
        try:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._conn.close()
        except Exception:
            pass
