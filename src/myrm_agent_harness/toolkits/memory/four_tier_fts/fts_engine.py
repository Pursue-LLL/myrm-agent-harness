"""[POS]: src/myrm_agent_harness/toolkits/memory/four_tier_fts/fts_engine.py
[INPUT]: SQLite connection, four-tier memory items, and search parameters.
[OUTPUT]: SqliteFts5MemoryEngine managing isolated project databases, FTS5 virtual tables, and BM25 ranked searches.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from .models import FourTierMemoryItem, FtsSearchResult, MemoryScope


class SqliteFts5MemoryEngine:
    """Manages project-isolated SQLite databases with FTS5 virtual tables for millisecond full-text recall."""

    def __init__(self, base_storage_dir: Path | str | None = None) -> None:
        self._base_dir = Path(base_storage_dir or "/tmp/myrm_four_tier_memory")
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        # project_hash -> sqlite3.Connection
        self._connections: dict[str, sqlite3.Connection] = {}
        # Track whether FTS5 is natively available
        self._has_fts5 = self._check_fts5_support()

    def _check_fts5_support(self) -> bool:
        """Probes whether sqlite3 FTS5 module is compiled and functional."""
        try:
            conn = sqlite3.connect(":memory:")
            conn.execute("CREATE VIRTUAL TABLE _test_fts USING fts5(content);")
            conn.close()
            return True
        except Exception:
            return False

    def _get_connection(self, project_hash: str) -> sqlite3.Connection:
        """Retrieves or initializes a SQLite connection for the specified project hash."""
        safe_hash = project_hash.strip().lower() or "default"
        if safe_hash not in self._connections:
            db_path = self._base_dir / f"{safe_hash}.db"
            conn = sqlite3.connect(str(db_path), check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=5000;")
            self._init_db_schema(conn)
            self._connections[safe_hash] = conn
        return self._connections[safe_hash]

    def _init_db_schema(self, conn: sqlite3.Connection) -> None:
        """Initializes relational and FTS tables."""
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS four_tier_records (
                item_id TEXT PRIMARY KEY,
                scope TEXT NOT NULL,
                project_hash TEXT NOT NULL,
                session_id TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                tags_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        if self._has_fts5:
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                    item_id UNINDEXED,
                    scope,
                    project_hash,
                    session_id,
                    title,
                    content,
                    tags,
                    tokenize='unicode61'
                );
                """
            )
        conn.commit()

    def save_item(self, item: FourTierMemoryItem) -> FourTierMemoryItem:
        """Saves or updates a four-tier memory record and synchronizes the FTS index."""
        with self._lock:
            conn = self._get_connection(item.project_hash)
            updated_iso = item.updated_at.isoformat() if item.updated_at else datetime.now(UTC).isoformat()
            tags_json = json.dumps(item.tags, ensure_ascii=False)
            tags_str = " ".join(item.tags)

            # Insert or replace in main table
            conn.execute(
                """
                INSERT OR REPLACE INTO four_tier_records
                (item_id, scope, project_hash, session_id, title, content, tags_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    item.item_id,
                    item.scope.value,
                    item.project_hash,
                    item.session_id,
                    item.title,
                    item.content,
                    tags_json,
                    item.created_at.isoformat(),
                    updated_iso,
                ),
            )

            # Sync to FTS table if enabled
            if self._has_fts5:
                conn.execute("DELETE FROM memory_fts WHERE item_id = ?;", (item.item_id,))
                conn.execute(
                    """
                    INSERT INTO memory_fts (item_id, scope, project_hash, session_id, title, content, tags)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        item.item_id,
                        item.scope.value,
                        item.project_hash,
                        item.session_id,
                        item.title,
                        item.content,
                        tags_str,
                    ),
                )

            conn.commit()
            item.updated_at = datetime.fromisoformat(updated_iso)
            return item

    def get_item(self, item_id: str, project_hash: str = "default") -> FourTierMemoryItem | None:
        """Retrieves a single memory item by ID."""
        with self._lock:
            conn = self._get_connection(project_hash)
            cursor = conn.execute(
                """
                SELECT item_id, scope, project_hash, session_id, title, content, tags_json, created_at, updated_at
                FROM four_tier_records WHERE item_id = ?;
                """,
                (item_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_item(row)

    def delete_item(self, item_id: str, project_hash: str = "default") -> bool:
        """Deletes a memory item and removes its FTS entry."""
        with self._lock:
            conn = self._get_connection(project_hash)
            cur = conn.execute("DELETE FROM four_tier_records WHERE item_id = ?;", (item_id,))
            if self._has_fts5:
                conn.execute("DELETE FROM memory_fts WHERE item_id = ?;", (item_id,))
            conn.commit()
            return cur.rowcount > 0

    def list_items(
        self,
        project_hash: str = "default",
        scope: MemoryScope | None = None,
        session_id: str | None = None,
    ) -> list[FourTierMemoryItem]:
        """Lists items for a project, optionally filtered by scope and session."""
        with self._lock:
            conn = self._get_connection(project_hash)
            query = "SELECT item_id, scope, project_hash, session_id, title, content, tags_json, created_at, updated_at FROM four_tier_records WHERE 1=1"
            params: list[str] = []

            if scope is not None:
                query += " AND scope = ?"
                params.append(scope.value)
            if session_id:
                query += " AND session_id = ?"
                params.append(session_id)

            query += " ORDER BY updated_at DESC;"
            cursor = conn.execute(query, params)
            return [self._row_to_item(row) for row in cursor.fetchall()]

    def search_fts(
        self,
        query_text: str,
        project_hash: str = "default",
        scope: MemoryScope | None = None,
        limit: int = 20,
    ) -> list[FtsSearchResult]:
        """Searches memory records using SQLite FTS5 with BM25 ranking, or LIKE fallback."""
        cleaned_query = query_text.strip()
        if not cleaned_query:
            return []

        with self._lock:
            conn = self._get_connection(project_hash)
            results: list[FtsSearchResult] = []

            if self._has_fts5:
                results = self._search_via_fts5(conn, cleaned_query, project_hash, scope, limit)
            else:
                results = self._search_via_like_fallback(conn, cleaned_query, project_hash, scope, limit)

            return results

    def _search_via_fts5(
        self,
        conn: sqlite3.Connection,
        query: str,
        project_hash: str,
        scope: MemoryScope | None,
        limit: int,
    ) -> list[FtsSearchResult]:
        """Performs search using native SQLite FTS5."""
        sanitized_query = "".join(c for c in query if c.isalnum() or c.isspace()).strip()
        if not sanitized_query:
            return []

        fts_sql = """
            SELECT m.item_id, m.scope, m.project_hash, m.title, m.content,
                   snippet(memory_fts, 5, '<b>', '</b>', '...', 16) AS snippet,
                   bm25(memory_fts) AS rank_score,
                   r.updated_at
            FROM memory_fts m
            JOIN four_tier_records r ON m.item_id = r.item_id
            WHERE memory_fts MATCH ?
        """
        params: list[str | int] = [sanitized_query]

        if scope is not None:
            fts_sql += " AND m.scope = ?"
            params.append(scope.value)

        fts_sql += " ORDER BY rank_score ASC LIMIT ?;"
        params.append(limit)

        try:
            cursor = conn.execute(fts_sql, params)
            hits: list[FtsSearchResult] = []
            for row in cursor.fetchall():
                hits.append(
                    FtsSearchResult(
                        item_id=row[0],
                        scope=MemoryScope(row[1]),
                        project_hash=row[2],
                        title=row[3],
                        content=row[4],
                        snippet=row[5] or row[4][:120],
                        bm25_rank=round(float(row[6]), 3),
                        updated_at=datetime.fromisoformat(row[7]),
                    )
                )
            return hits
        except sqlite3.OperationalError:
            return self._search_via_like_fallback(conn, query, project_hash, scope, limit)

    def _search_via_like_fallback(
        self,
        conn: sqlite3.Connection,
        query: str,
        project_hash: str,
        scope: MemoryScope | None,
        limit: int,
    ) -> list[FtsSearchResult]:
        """Fallback search using SQL LIKE matching."""
        sql = """
            SELECT item_id, scope, project_hash, title, content, updated_at
            FROM four_tier_records
            WHERE (title LIKE ? OR content LIKE ? OR tags_json LIKE ?)
        """
        pattern = f"%{query}%"
        params: list[str | int] = [pattern, pattern, pattern]

        if scope is not None:
            sql += " AND scope = ?"
            params.append(scope.value)

        sql += " ORDER BY updated_at DESC LIMIT ?;"
        params.append(limit)

        cursor = conn.execute(sql, params)
        hits: list[FtsSearchResult] = []
        for idx, row in enumerate(cursor.fetchall()):
            content = row[4]
            snippet = content[:120] + "..." if len(content) > 120 else content
            hits.append(
                FtsSearchResult(
                    item_id=row[0],
                    scope=MemoryScope(row[1]),
                    project_hash=row[2],
                    title=row[3],
                    content=content,
                    snippet=snippet,
                    bm25_rank=float(idx),
                    updated_at=datetime.fromisoformat(row[5]),
                )
            )
        return hits

    def _row_to_item(self, row: tuple[str, ...]) -> FourTierMemoryItem:
        """Converts database row tuple to FourTierMemoryItem."""
        return FourTierMemoryItem(
            item_id=row[0],
            scope=MemoryScope(row[1]),
            project_hash=row[2],
            session_id=row[3],
            title=row[4],
            content=row[5],
            tags=json.loads(row[6]),
            created_at=datetime.fromisoformat(row[7]),
            updated_at=datetime.fromisoformat(row[8]),
        )
