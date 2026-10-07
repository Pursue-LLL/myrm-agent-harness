"""[POS]: src/myrm_agent_harness/toolkits/memory/cognitive_box/box.py
[INPUT]: SQLite database path, CognitiveMemoryEntry models, and CognitiveLayerKind filters.
[OUTPUT]: FourLayerCognitiveMemoryBox handling partitioned 4-layer storage, retrieval, and context formatting.
"""

import json
import sqlite3
import threading
import time
from pathlib import Path

from myrm_agent_harness.toolkits.memory.cognitive_box.models import (
    CognitiveBoxSnapshot,
    CognitiveLayerKind,
    CognitiveMemoryEntry,
)


class FourLayerCognitiveMemoryBox:
    """Manages segregated persistence and retrieval across the four cognitive layers."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            if self._db_path != ":memory:":
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA busy_timeout=5000")
            self._conn = conn
        return self._conn

    def _init_db(self) -> None:
        conn = self._get_connection()
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS myrm_cognitive_memory_box (
                    id TEXT PRIMARY KEY,
                    layer TEXT NOT NULL,
                    content TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    tags TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    source_session TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_cog_box_layer_updated
                ON myrm_cognitive_memory_box(layer, updated_at DESC)
                """
            )

    def write_entry(self, entry: CognitiveMemoryEntry) -> CognitiveMemoryEntry:
        """Insert or replace an entry in its respective cognitive layer."""
        now = time.time()
        created_at = entry.created_at if entry.created_at > 0 else now
        updated_at = entry.updated_at if entry.updated_at > 0 else now

        tags_json = json.dumps(entry.tags, ensure_ascii=False)
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO myrm_cognitive_memory_box (
                        id, layer, content, confidence, tags, created_at, updated_at, source_session
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry.id,
                        entry.layer.value,
                        entry.content,
                        entry.confidence,
                        tags_json,
                        created_at,
                        updated_at,
                        entry.source_session,
                    ),
                )

        return CognitiveMemoryEntry(
            id=entry.id,
            layer=entry.layer,
            content=entry.content,
            confidence=entry.confidence,
            tags=list(entry.tags),
            created_at=created_at,
            updated_at=updated_at,
            source_session=entry.source_session,
        )

    def get_entry(self, entry_id: str) -> CognitiveMemoryEntry | None:
        """Fetch a specific cognitive memory item by ID."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(
                """
                SELECT id, layer, content, confidence, tags, created_at, updated_at, source_session
                FROM myrm_cognitive_memory_box
                WHERE id = ?
                """,
                (entry_id,),
            )
            row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_entry(row)

    def list_entries(
        self,
        layer: CognitiveLayerKind | None = None,
        limit: int = 100,
    ) -> list[CognitiveMemoryEntry]:
        """List cognitive entries, optionally filtered by cognitive layer."""
        with self._lock:
            conn = self._get_connection()
            if layer is not None:
                cursor = conn.execute(
                    """
                    SELECT id, layer, content, confidence, tags, created_at, updated_at, source_session
                    FROM myrm_cognitive_memory_box
                    WHERE layer = ?
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (layer.value, limit),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT id, layer, content, confidence, tags, created_at, updated_at, source_session
                    FROM myrm_cognitive_memory_box
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            rows = cursor.fetchall()
        return [self._row_to_entry(row) for row in rows]

    def delete_entry(self, entry_id: str) -> bool:
        """Remove a cognitive memory item by ID."""
        with self._lock:
            conn = self._get_connection()
            with conn:
                cursor = conn.execute(
                    "DELETE FROM myrm_cognitive_memory_box WHERE id = ?",
                    (entry_id,),
                )
                return cursor.rowcount > 0

    def clear_layer(self, layer: CognitiveLayerKind) -> int:
        """Purge all entries belonging to a given cognitive layer."""
        with self._lock:
            conn = self._get_connection()
            with conn:
                cursor = conn.execute(
                    "DELETE FROM myrm_cognitive_memory_box WHERE layer = ?",
                    (layer.value,),
                )
                return cursor.rowcount

    def get_snapshot(self) -> CognitiveBoxSnapshot:
        """Produce an aggregated snapshot of the entire cognitive box."""
        entries = self.list_entries(limit=500)
        counts: dict[str, int] = {kind.value: 0 for kind in CognitiveLayerKind}
        for entry in entries:
            counts[entry.layer.value] = counts.get(entry.layer.value, 0) + 1

        return CognitiveBoxSnapshot(
            timestamp=time.time(),
            total_count=len(entries),
            counts_by_layer=counts,
            entries=entries,
        )

    def render_prompt_context(
        self,
        layers: list[CognitiveLayerKind] | None = None,
    ) -> str:
        """Format the active cognitive layers into a structured system prompt context block."""
        target_layers = layers or list(CognitiveLayerKind)
        sections: list[str] = []

        headers = {
            CognitiveLayerKind.IDENTITY: "Cognitive Layer 1: Identity & Boundaries",
            CognitiveLayerKind.USER_PROFILE: "Cognitive Layer 2: User Profile & Preferences",
            CognitiveLayerKind.ENVIRONMENT: "Cognitive Layer 3: Workspace & Environment",
            CognitiveLayerKind.LESSONS_RULES: "Cognitive Layer 4: Distilled Lessons & Rules",
        }

        for layer in target_layers:
            items = self.list_entries(layer=layer, limit=50)
            if not items:
                continue
            section_title = headers.get(layer, layer.value)
            lines = [f"### {section_title}"]
            for item in items:
                lines.append(f"- {item.content}")
            sections.append("\n".join(lines))

        return "\n\n".join(sections)

    def close(self) -> None:
        """Safely close database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _row_to_entry(self, row: sqlite3.Row) -> CognitiveMemoryEntry:
        tags_raw = row["tags"]
        try:
            tags = json.loads(tags_raw) if tags_raw else []
        except Exception:
            tags = []

        return CognitiveMemoryEntry(
            id=row["id"],
            layer=CognitiveLayerKind(row["layer"]),
            content=row["content"],
            confidence=float(row["confidence"]),
            tags=list(tags),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            source_session=row["source_session"],
        )
