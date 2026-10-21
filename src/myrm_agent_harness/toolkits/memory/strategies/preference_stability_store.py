"""Preference facet store — Protocol and SQLite implementation.

Provides persistent storage for PreferenceFacet metadata records.
Separate from the main RelationalStore to maintain single-responsibility:
RelationalStore handles Profile/Procedural/Pending, this handles preference facets.


[INPUT]
- memory.strategies.preference_stability::{PreferenceFacet, PreferenceCategory, PreferenceLifecycle, CueFamily} (POS: preference data models)

[OUTPUT]
- PreferenceFacetStoreProtocol: Storage protocol for preference facets (upsert, find_by_id, find_by_key_value, lifecycle queries)
- SQLitePreferenceFacetStore: aiosqlite-backed implementation with WAL mode and indexed lookups

[POS]
Preference facet persistence layer. Stores preference metadata (key, value, category,
lifecycle, stability, evidence_count) in a lightweight SQLite table. Links to
SemanticMemory via memory_ids for content retrieval.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

import aiosqlite

from myrm_agent_harness.toolkits.memory.strategies.preference_stability import (
    CueFamily,
    PreferenceCategory,
    PreferenceFacet,
    PreferenceLifecycle,
)

logger = logging.getLogger(__name__)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS preference_facets (
    id TEXT PRIMARY KEY,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'style',
    cue TEXT NOT NULL DEFAULT 'implicit',
    lifecycle TEXT NOT NULL DEFAULT 'candidate',
    stability REAL NOT NULL DEFAULT 0.0,
    evidence_count INTEGER NOT NULL DEFAULT 1,
    memory_ids TEXT NOT NULL DEFAULT '[]',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    user_pinned INTEGER NOT NULL DEFAULT 0,
    user_forgotten INTEGER NOT NULL DEFAULT 0
)
"""

_CREATE_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_pf_lifecycle ON preference_facets(lifecycle)",
    "CREATE INDEX IF NOT EXISTS idx_pf_key_value ON preference_facets(key, value)",
    "CREATE INDEX IF NOT EXISTS idx_pf_category ON preference_facets(category)",
]


# ── Protocol ────────────────────────────────────────────────────────


@runtime_checkable
class PreferenceFacetStoreProtocol(Protocol):
    """Storage protocol for preference facets."""

    async def upsert(self, facet: PreferenceFacet) -> None: ...

    async def find_by_id(self, facet_id: str) -> PreferenceFacet | None: ...

    async def find_by_key_value(self, key: str, value: str) -> PreferenceFacet | None: ...

    async def find_by_key(self, key: str) -> list[PreferenceFacet]: ...

    async def list_by_lifecycle(self, lifecycle: PreferenceLifecycle) -> list[PreferenceFacet]: ...

    async def list_all(self) -> list[PreferenceFacet]: ...

    async def cleanup_dropped(self, max_age_days: int = 30) -> int: ...

    async def delete(self, facet_id: str) -> None: ...

    async def close(self) -> None: ...


# ── SQLite implementation ───────────────────────────────────────────


def _facet_from_row(row: aiosqlite.Row) -> PreferenceFacet:
    memory_ids_raw = row[8]
    memory_ids: list[str] = json.loads(memory_ids_raw) if memory_ids_raw else []

    return PreferenceFacet(
        id=row[0],
        key=row[1],
        value=row[2],
        category=PreferenceCategory(row[3]),
        cue=CueFamily(row[4]),
        lifecycle=PreferenceLifecycle(row[5]),
        stability=float(row[6]),
        evidence_count=int(row[7]),
        memory_ids=memory_ids,
        first_seen=datetime.fromisoformat(row[9]),
        last_seen=datetime.fromisoformat(row[10]),
        user_pinned=bool(row[11]),
        user_forgotten=bool(row[12]),
    )


class SQLitePreferenceFacetStore:
    """aiosqlite-backed preference facet store.

    Shares the same database directory as the main relational store
    but uses a separate table for clean separation.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = str(Path(db_path).expanduser().resolve())
        self._conn: aiosqlite.Connection | None = None
        self._initialized = False

    async def _ensure_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            self._conn = await aiosqlite.connect(self._db_path)
            self._conn.row_factory = aiosqlite.Row
            from myrm_agent_harness.utils.db.sqlite import DEFAULT, harden_connection_async

            await harden_connection_async(self._conn, DEFAULT, db_path=Path(self._db_path))
        if not self._initialized:
            await self._conn.execute(_CREATE_TABLE_SQL)
            for idx_sql in _CREATE_INDEX_SQL:
                await self._conn.execute(idx_sql)
            await self._conn.commit()
            self._initialized = True
        return self._conn

    async def upsert(self, facet: PreferenceFacet) -> None:
        conn = await self._ensure_conn()
        memory_ids_json = json.dumps(facet.memory_ids)
        first_seen_iso = facet.first_seen.isoformat() if facet.first_seen else datetime.now(UTC).isoformat()
        last_seen_iso = facet.last_seen.isoformat() if facet.last_seen else datetime.now(UTC).isoformat()

        await conn.execute(
            """INSERT INTO preference_facets
               (id, key, value, category, cue, lifecycle, stability,
                evidence_count, memory_ids, first_seen, last_seen,
                user_pinned, user_forgotten)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 category=excluded.category,
                 cue=excluded.cue,
                 lifecycle=excluded.lifecycle,
                 stability=excluded.stability,
                 evidence_count=excluded.evidence_count,
                 memory_ids=excluded.memory_ids,
                 last_seen=excluded.last_seen,
                 user_pinned=excluded.user_pinned,
                 user_forgotten=excluded.user_forgotten""",
            (
                facet.id,
                facet.key,
                facet.value,
                facet.category.value,
                facet.cue.value,
                facet.lifecycle.value,
                facet.stability,
                facet.evidence_count,
                memory_ids_json,
                first_seen_iso,
                last_seen_iso,
                int(facet.user_pinned),
                int(facet.user_forgotten),
            ),
        )
        await conn.commit()

    async def find_by_id(self, facet_id: str) -> PreferenceFacet | None:
        conn = await self._ensure_conn()
        cursor = await conn.execute(
            "SELECT * FROM preference_facets WHERE id = ? LIMIT 1",
            (facet_id,),
        )
        row = await cursor.fetchone()
        return _facet_from_row(row) if row is not None else None

    async def find_by_key_value(self, key: str, value: str) -> PreferenceFacet | None:
        conn = await self._ensure_conn()
        cursor = await conn.execute(
            "SELECT * FROM preference_facets WHERE key = ? AND value = ? LIMIT 1",
            (key, value),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return _facet_from_row(row)

    async def find_by_key(self, key: str) -> list[PreferenceFacet]:
        conn = await self._ensure_conn()
        cursor = await conn.execute(
            "SELECT * FROM preference_facets WHERE key = ? ORDER BY stability DESC",
            (key,),
        )
        rows = await cursor.fetchall()
        return [_facet_from_row(r) for r in rows]

    async def list_by_lifecycle(self, lifecycle: PreferenceLifecycle) -> list[PreferenceFacet]:
        conn = await self._ensure_conn()
        cursor = await conn.execute(
            "SELECT * FROM preference_facets WHERE lifecycle = ? ORDER BY stability DESC",
            (lifecycle.value,),
        )
        rows = await cursor.fetchall()
        return [_facet_from_row(r) for r in rows]

    async def list_all(self) -> list[PreferenceFacet]:
        conn = await self._ensure_conn()
        cursor = await conn.execute("SELECT * FROM preference_facets ORDER BY stability DESC")
        rows = await cursor.fetchall()
        return [_facet_from_row(r) for r in rows]

    async def cleanup_dropped(self, max_age_days: int = 30) -> int:
        """Remove Dropped facets older than max_age_days."""
        conn = await self._ensure_conn()
        cutoff = datetime.now(UTC)
        cutoff_iso = cutoff.isoformat()
        cursor = await conn.execute(
            """DELETE FROM preference_facets
               WHERE lifecycle = ? AND last_seen < datetime(?, '-' || ? || ' days')""",
            (PreferenceLifecycle.DROPPED.value, cutoff_iso, max_age_days),
        )
        await conn.commit()
        return cursor.rowcount or 0

    async def delete(self, facet_id: str) -> None:
        conn = await self._ensure_conn()
        await conn.execute("DELETE FROM preference_facets WHERE id = ?", (facet_id,))
        await conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
            self._initialized = False
