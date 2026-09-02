"""Four-tier decoupled durable session storage implementation (SQLite WAL and In-Memory).

[INPUT]
- .types::IntentRecord, TreeEntry, LaneState, OperationLogEntry, GlobalFactRecord, UsageRecord, IntentStatus, EffectType
- .protocols::DurableStorageProtocol

[OUTPUT]
- InMemoryDurableStorage: Ultra-fast lockless in-memory storage for test/transient runs.
- SqliteDurableStorage: Production-grade ACID SQLite WAL backend with separated 5-table schema.

[POS]
Storage implementations for four-tier decoupled session persistence.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from myrm_agent_harness.agent.durable.protocols import DurableStorageProtocol
from myrm_agent_harness.agent.durable.types import (
    EffectType,
    GlobalFactRecord,
    IntentRecord,
    IntentStatus,
    LaneState,
    OperationLogEntry,
    TreeEntry,
    UsageRecord,
)


def _compute_entry_checksum(parent_checksum: str | None, entry_type: str, content: str | dict[str, Any]) -> str:
    """Compute deterministic cumulative SHA-256 checksum for a tree node."""
    c_str = json.dumps(content, sort_keys=True, ensure_ascii=False) if isinstance(content, dict) else str(content)
    raw = f"{parent_checksum or 'ROOT'}:{entry_type}:{c_str}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class InMemoryDurableStorage(DurableStorageProtocol):
    """High-performance in-memory implementation of the four-tier storage protocol."""

    def __init__(self) -> None:
        self._tree_entries: dict[str, dict[str, TreeEntry]] = {}  # session_id -> {entry_id: TreeEntry}
        self._lanes: dict[str, dict[str, LaneState]] = {}  # session_id -> {lane_id: LaneState}
        self._intents: dict[str, dict[str, IntentRecord]] = {}  # session_id -> {intent_id: IntentRecord}
        self._op_logs: dict[str, list[OperationLogEntry]] = {}  # session_id -> list
        self._facts: dict[str, dict[str, Any]] = {}  # session_id -> {key: value}
        self._usages: dict[str, list[UsageRecord]] = {}  # session_id -> list
        self._lock = asyncio.Lock()

    async def append_tree_entry(self, entry: TreeEntry) -> None:
        async with self._lock:
            s_map = self._tree_entries.setdefault(entry.session_id, {})
            parent_checksum = None
            if entry.parent_id and entry.parent_id in s_map:
                parent_checksum = s_map[entry.parent_id].checksum_sha256
            entry.sequence = len(s_map) + 1
            entry.checksum_sha256 = _compute_entry_checksum(parent_checksum, entry.entry_type, entry.content)
            s_map[entry.entry_id] = entry

    async def get_tree_entry(self, session_id: str, entry_id: str) -> TreeEntry | None:
        async with self._lock:
            return self._tree_entries.get(session_id, {}).get(entry_id)

    async def get_tree_history(self, session_id: str, leaf_id: str | None = None) -> list[TreeEntry]:
        async with self._lock:
            s_map = self._tree_entries.get(session_id, {})
            if not s_map:
                return []
            if not leaf_id:
                return sorted(s_map.values(), key=lambda x: x.sequence)
            chain: list[TreeEntry] = []
            curr_id: str | None = leaf_id
            visited = set()
            while curr_id and curr_id in s_map and curr_id not in visited:
                visited.add(curr_id)
                node = s_map[curr_id]
                chain.append(node)
                curr_id = node.parent_id
            chain.reverse()
            return chain

    async def get_or_create_lane(self, session_id: str, lane_id: str, parent_lane_id: str | None = None) -> LaneState:
        async with self._lock:
            lanes = self._lanes.setdefault(session_id, {})
            if lane_id not in lanes:
                lanes[lane_id] = LaneState(
                    lane_id=lane_id,
                    session_id=session_id,
                    current_leaf_id=None,
                    parent_lane_id=parent_lane_id,
                )
            return lanes[lane_id]

    async def update_lane_state(self, lane: LaneState) -> None:
        async with self._lock:
            lane.updated_at_ms = int(time.time() * 1000)
            self._lanes.setdefault(lane.session_id, {})[lane.lane_id] = lane

    async def append_intent(self, intent: IntentRecord) -> None:
        async with self._lock:
            self._intents.setdefault(intent.session_id, {})[intent.intent_id] = intent

    async def update_intent(self, intent: IntentRecord) -> None:
        async with self._lock:
            self._intents.setdefault(intent.session_id, {})[intent.intent_id] = intent

    async def get_intent(self, session_id: str, intent_id: str) -> IntentRecord | None:
        async with self._lock:
            return self._intents.get(session_id, {}).get(intent_id)

    async def get_pending_intents(self, session_id: str, lane_id: str | None = None) -> list[IntentRecord]:
        async with self._lock:
            intents = list(self._intents.get(session_id, {}).values())
            pending = [i for i in intents if i.status == IntentStatus.PENDING]
            if lane_id:
                pending = [i for i in pending if i.lane_id == lane_id]
            return pending

    async def append_operation_log(self, op: OperationLogEntry) -> None:
        async with self._lock:
            logs = self._op_logs.setdefault(op.session_id, [])
            op.sequence = len(logs) + 1
            logs.append(op)

    async def get_operation_logs(self, session_id: str, lane_id: str | None = None) -> list[OperationLogEntry]:
        async with self._lock:
            logs = self._op_logs.get(session_id, [])
            if lane_id:
                return [l for l in logs if l.lane_id == lane_id]
            return list(logs)

    async def set_global_fact(self, session_id: str, key: str, value: Any) -> None:
        async with self._lock:
            self._facts.setdefault(session_id, {})[key] = value

    async def get_global_fact(self, session_id: str, key: str) -> Any | None:
        async with self._lock:
            return self._facts.get(session_id, {}).get(key)

    async def append_usage(self, usage: UsageRecord) -> None:
        async with self._lock:
            self._usages.setdefault(usage.session_id, []).append(usage)

    async def get_total_usage(self, session_id: str) -> list[UsageRecord]:
        async with self._lock:
            return list(self._usages.get(session_id, []))


class SqliteDurableStorage(DurableStorageProtocol):
    """Production-grade SQLite WAL durable storage backend."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._lock = asyncio.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._get_connection()
        try:
            with conn:
                conn.executescript("""
                CREATE TABLE IF NOT EXISTS durable_trees (
                    session_id TEXT NOT NULL,
                    entry_id TEXT NOT NULL,
                    parent_id TEXT,
                    entry_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    created_at_ms INTEGER NOT NULL,
                    checksum_sha256 TEXT,
                    PRIMARY KEY (session_id, entry_id)
                );
                CREATE INDEX IF NOT EXISTS idx_tree_seq ON durable_trees(session_id, sequence);

                CREATE TABLE IF NOT EXISTS durable_lanes (
                    session_id TEXT NOT NULL,
                    lane_id TEXT NOT NULL,
                    current_leaf_id TEXT,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    parent_lane_id TEXT,
                    created_at_ms INTEGER NOT NULL,
                    updated_at_ms INTEGER NOT NULL,
                    PRIMARY KEY (session_id, lane_id)
                );

                CREATE TABLE IF NOT EXISTS durable_intents (
                    session_id TEXT NOT NULL,
                    intent_id TEXT NOT NULL,
                    lane_id TEXT NOT NULL,
                    effect_type TEXT NOT NULL,
                    source_leaf_id TEXT,
                    provisioned_result_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at_ms INTEGER NOT NULL,
                    completed_at_ms INTEGER,
                    error_message TEXT,
                    PRIMARY KEY (session_id, intent_id)
                );
                CREATE INDEX IF NOT EXISTS idx_intent_status ON durable_intents(session_id, status);

                CREATE TABLE IF NOT EXISTS durable_op_logs (
                    session_id TEXT NOT NULL,
                    op_id TEXT NOT NULL,
                    lane_id TEXT NOT NULL,
                    op_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    created_at_ms INTEGER NOT NULL,
                    PRIMARY KEY (session_id, op_id)
                );

                CREATE TABLE IF NOT EXISTS durable_facts (
                    session_id TEXT NOT NULL,
                    fact_key TEXT NOT NULL,
                    fact_value TEXT NOT NULL,
                    updated_at_ms INTEGER NOT NULL,
                    PRIMARY KEY (session_id, fact_key)
                );

                CREATE TABLE IF NOT EXISTS durable_usages (
                    session_id TEXT NOT NULL,
                    usage_id TEXT NOT NULL,
                    lane_id TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL,
                    completion_tokens INTEGER NOT NULL,
                    total_tokens INTEGER NOT NULL,
                    cached_tokens INTEGER NOT NULL,
                    estimated_cost_usd REAL NOT NULL,
                    created_at_ms INTEGER NOT NULL,
                    PRIMARY KEY (session_id, usage_id)
                );
                """)
        finally:
            conn.close()

    async def append_tree_entry(self, entry: TreeEntry) -> None:
        async with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    row = conn.execute(
                        "SELECT checksum_sha256 FROM durable_trees WHERE session_id = ? AND entry_id = ?",
                        (entry.session_id, entry.parent_id),
                    ).fetchone()
                    parent_checksum = row["checksum_sha256"] if row else None
                    seq_row = conn.execute(
                        "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_seq FROM durable_trees WHERE session_id = ?",
                        (entry.session_id,),
                    ).fetchone()
                    entry.sequence = int(seq_row["next_seq"]) if seq_row else 1
                    entry.checksum_sha256 = _compute_entry_checksum(parent_checksum, entry.entry_type, entry.content)

                    conn.execute(
                        """
                        INSERT INTO durable_trees (
                            session_id, entry_id, parent_id, entry_type, content, metadata, sequence, created_at_ms, checksum_sha256
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            entry.session_id,
                            entry.entry_id,
                            entry.parent_id,
                            entry.entry_type,
                            json.dumps(entry.content, ensure_ascii=False) if isinstance(entry.content, dict) else str(entry.content),
                            json.dumps(entry.metadata, ensure_ascii=False),
                            entry.sequence,
                            entry.created_at_ms,
                            entry.checksum_sha256,
                        ),
                    )
            finally:
                conn.close()

    async def get_tree_entry(self, session_id: str, entry_id: str) -> TreeEntry | None:
        async with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT * FROM durable_trees WHERE session_id = ? AND entry_id = ?",
                    (session_id, entry_id),
                ).fetchone()
                if not row:
                    return None
                return self._row_to_tree_entry(row)
            finally:
                conn.close()

    def _row_to_tree_entry(self, row: sqlite3.Row) -> TreeEntry:
        raw_content = row["content"]
        try:
            content = json.loads(raw_content)
        except Exception:
            content = raw_content
        return TreeEntry(
            entry_id=row["entry_id"],
            session_id=row["session_id"],
            parent_id=row["parent_id"],
            entry_type=row["entry_type"],
            content=content,
            metadata=json.loads(row["metadata"]),
            sequence=row["sequence"],
            created_at_ms=row["created_at_ms"],
            checksum_sha256=row["checksum_sha256"],
        )

    async def get_tree_history(self, session_id: str, leaf_id: str | None = None) -> list[TreeEntry]:
        async with self._lock:
            conn = self._get_connection()
            try:
                if not leaf_id:
                    rows = conn.execute(
                        "SELECT * FROM durable_trees WHERE session_id = ? ORDER BY sequence ASC",
                        (session_id,),
                    ).fetchall()
                    return [self._row_to_tree_entry(r) for r in rows]

                chain: list[TreeEntry] = []
                curr_id: str | None = leaf_id
                visited = set()
                while curr_id and curr_id not in visited:
                    visited.add(curr_id)
                    row = conn.execute(
                        "SELECT * FROM durable_trees WHERE session_id = ? AND entry_id = ?",
                        (session_id, curr_id),
                    ).fetchone()
                    if not row:
                        break
                    node = self._row_to_tree_entry(row)
                    chain.append(node)
                    curr_id = node.parent_id
                chain.reverse()
                return chain
            finally:
                conn.close()

    async def get_or_create_lane(self, session_id: str, lane_id: str, parent_lane_id: str | None = None) -> LaneState:
        async with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    row = conn.execute(
                        "SELECT * FROM durable_lanes WHERE session_id = ? AND lane_id = ?",
                        (session_id, lane_id),
                    ).fetchone()
                    if row:
                        return LaneState(
                            lane_id=row["lane_id"],
                            session_id=row["session_id"],
                            current_leaf_id=row["current_leaf_id"],
                            status=row["status"],
                            attempt_count=row["attempt_count"],
                            parent_lane_id=row["parent_lane_id"],
                            created_at_ms=row["created_at_ms"],
                            updated_at_ms=row["updated_at_ms"],
                        )
                    now = int(time.time() * 1000)
                    lane = LaneState(
                        lane_id=lane_id,
                        session_id=session_id,
                        current_leaf_id=None,
                        parent_lane_id=parent_lane_id,
                        created_at_ms=now,
                        updated_at_ms=now,
                    )
                    conn.execute(
                        """
                        INSERT INTO durable_lanes (
                            session_id, lane_id, current_leaf_id, status, attempt_count, parent_lane_id, created_at_ms, updated_at_ms
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            lane.session_id,
                            lane.lane_id,
                            lane.current_leaf_id,
                            lane.status,
                            lane.attempt_count,
                            lane.parent_lane_id,
                            lane.created_at_ms,
                            lane.updated_at_ms,
                        ),
                    )
                    return lane
            finally:
                conn.close()

    async def update_lane_state(self, lane: LaneState) -> None:
        async with self._lock:
            lane.updated_at_ms = int(time.time() * 1000)
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO durable_lanes (
                            session_id, lane_id, current_leaf_id, status, attempt_count, parent_lane_id, created_at_ms, updated_at_ms
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(session_id, lane_id) DO UPDATE SET
                            current_leaf_id=excluded.current_leaf_id,
                            status=excluded.status,
                            attempt_count=excluded.attempt_count,
                            updated_at_ms=excluded.updated_at_ms
                        """,
                        (
                            lane.session_id,
                            lane.lane_id,
                            lane.current_leaf_id,
                            lane.status,
                            lane.attempt_count,
                            lane.parent_lane_id,
                            lane.created_at_ms,
                            lane.updated_at_ms,
                        ),
                    )
            finally:
                conn.close()

    async def append_intent(self, intent: IntentRecord) -> None:
        async with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO durable_intents (
                            session_id, intent_id, lane_id, effect_type, source_leaf_id, provisioned_result_id,
                            payload, status, created_at_ms, completed_at_ms, error_message
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            intent.session_id,
                            intent.intent_id,
                            intent.lane_id,
                            intent.effect_type.value,
                            intent.source_leaf_id,
                            intent.provisioned_result_id,
                            json.dumps(intent.payload, ensure_ascii=False),
                            intent.status.value,
                            intent.created_at_ms,
                            intent.completed_at_ms,
                            intent.error_message,
                        ),
                    )
            finally:
                conn.close()

    async def update_intent(self, intent: IntentRecord) -> None:
        async with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute(
                        """
                        UPDATE durable_intents SET
                            status = ?,
                            completed_at_ms = ?,
                            error_message = ?
                        WHERE session_id = ? AND intent_id = ?
                        """,
                        (
                            intent.status.value,
                            intent.completed_at_ms,
                            intent.error_message,
                            intent.session_id,
                            intent.intent_id,
                        ),
                    )
            finally:
                conn.close()

    async def get_intent(self, session_id: str, intent_id: str) -> IntentRecord | None:
        async with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT * FROM durable_intents WHERE session_id = ? AND intent_id = ?",
                    (session_id, intent_id),
                ).fetchone()
                if not row:
                    return None
                return self._row_to_intent(row)
            finally:
                conn.close()

    def _row_to_intent(self, row: sqlite3.Row) -> IntentRecord:
        return IntentRecord(
            intent_id=row["intent_id"],
            session_id=row["session_id"],
            lane_id=row["lane_id"],
            effect_type=EffectType(row["effect_type"]),
            source_leaf_id=row["source_leaf_id"],
            provisioned_result_id=row["provisioned_result_id"],
            payload=json.loads(row["payload"]),
            status=IntentStatus(row["status"]),
            created_at_ms=row["created_at_ms"],
            completed_at_ms=row["completed_at_ms"],
            error_message=row["error_message"],
        )

    async def get_pending_intents(self, session_id: str, lane_id: str | None = None) -> list[IntentRecord]:
        async with self._lock:
            conn = self._get_connection()
            try:
                if lane_id:
                    rows = conn.execute(
                        "SELECT * FROM durable_intents WHERE session_id = ? AND lane_id = ? AND status = ?",
                        (session_id, lane_id, IntentStatus.PENDING.value),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM durable_intents WHERE session_id = ? AND status = ?",
                        (session_id, IntentStatus.PENDING.value),
                    ).fetchall()
                return [self._row_to_intent(r) for r in rows]
            finally:
                conn.close()

    async def append_operation_log(self, op: OperationLogEntry) -> None:
        async with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    seq_row = conn.execute(
                        "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_seq FROM durable_op_logs WHERE session_id = ?",
                        (op.session_id,),
                    ).fetchone()
                    op.sequence = int(seq_row["next_seq"]) if seq_row else 1
                    conn.execute(
                        """
                        INSERT INTO durable_op_logs (
                            session_id, op_id, lane_id, op_type, payload, sequence, created_at_ms
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            op.session_id,
                            op.op_id,
                            op.lane_id,
                            op.op_type,
                            json.dumps(op.payload, ensure_ascii=False),
                            op.sequence,
                            op.created_at_ms,
                        ),
                    )
            finally:
                conn.close()

    async def get_operation_logs(self, session_id: str, lane_id: str | None = None) -> list[OperationLogEntry]:
        async with self._lock:
            conn = self._get_connection()
            try:
                if lane_id:
                    rows = conn.execute(
                        "SELECT * FROM durable_op_logs WHERE session_id = ? AND lane_id = ? ORDER BY sequence ASC",
                        (session_id, lane_id),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM durable_op_logs WHERE session_id = ? ORDER BY sequence ASC",
                        (session_id,),
                    ).fetchall()
                return [
                    OperationLogEntry(
                        op_id=r["op_id"],
                        session_id=r["session_id"],
                        lane_id=r["lane_id"],
                        op_type=r["op_type"],
                        payload=json.loads(r["payload"]),
                        sequence=r["sequence"],
                        created_at_ms=r["created_at_ms"],
                    )
                    for r in rows
                ]
            finally:
                conn.close()

    async def set_global_fact(self, session_id: str, key: str, value: Any) -> None:
        async with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO durable_facts (session_id, fact_key, fact_value, updated_at_ms)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(session_id, fact_key) DO UPDATE SET
                            fact_value=excluded.fact_value,
                            updated_at_ms=excluded.updated_at_ms
                        """,
                        (session_id, key, json.dumps(value, ensure_ascii=False), int(time.time() * 1000)),
                    )
            finally:
                conn.close()

    async def get_global_fact(self, session_id: str, key: str) -> Any | None:
        async with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT fact_value FROM durable_facts WHERE session_id = ? AND fact_key = ?",
                    (session_id, key),
                ).fetchone()
                if not row:
                    return None
                return json.loads(row["fact_value"])
            finally:
                conn.close()

    async def append_usage(self, usage: UsageRecord) -> None:
        async with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO durable_usages (
                            session_id, usage_id, lane_id, model_name, prompt_tokens, completion_tokens,
                            total_tokens, cached_tokens, estimated_cost_usd, created_at_ms
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            usage.session_id,
                            usage.usage_id,
                            usage.lane_id,
                            usage.model_name,
                            usage.prompt_tokens,
                            usage.completion_tokens,
                            usage.total_tokens,
                            usage.cached_tokens,
                            usage.estimated_cost_usd,
                            usage.created_at_ms,
                        ),
                    )
            finally:
                conn.close()

    async def get_total_usage(self, session_id: str) -> list[UsageRecord]:
        async with self._lock:
            conn = self._get_connection()
            try:
                rows = conn.execute(
                    "SELECT * FROM durable_usages WHERE session_id = ? ORDER BY created_at_ms ASC",
                    (session_id,),
                ).fetchall()
                return [
                    UsageRecord(
                        usage_id=r["usage_id"],
                        session_id=r["session_id"],
                        lane_id=r["lane_id"],
                        model_name=r["model_name"],
                        prompt_tokens=r["prompt_tokens"],
                        completion_tokens=r["completion_tokens"],
                        total_tokens=r["total_tokens"],
                        cached_tokens=r["cached_tokens"],
                        estimated_cost_usd=r["estimated_cost_usd"],
                        created_at_ms=r["created_at_ms"],
                    )
                    for r in rows
                ]
            finally:
                conn.close()
