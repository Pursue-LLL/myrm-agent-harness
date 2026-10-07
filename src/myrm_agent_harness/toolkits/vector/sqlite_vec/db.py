"""Database connection and low-level SQL operations for SQLite vector store.

[POS]
Encapsulates SQLite schema migration, PRAGMA configuration, connection management,
and thread-safe synchronous database CRUD execution.

[INPUT]
- sqlite3, json, datetime, pathlib
- myrm_agent_harness.toolkits.vector.base (CollectionInfo, FilterDict, SearchResult, VectorDocument)
- myrm_agent_harness.toolkits.vector.sqlite_vec.models (SqliteVecConfig, SqliteVecEngineMode)
- myrm_agent_harness.toolkits.vector.sqlite_vec.utils (cosine_similarity, match_filter, pack_vector, unpack_vector)

[OUTPUT]
- SqliteVecDatabase: Low-level database operations manager
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from myrm_agent_harness.toolkits.vector.base import (
    CollectionInfo,
    FilterDict,
    SearchResult,
    VectorDocument,
)
from myrm_agent_harness.toolkits.vector.sqlite_vec.models import (
    SqliteVecConfig,
    SqliteVecEngineMode,
)
from myrm_agent_harness.toolkits.vector.sqlite_vec.utils import (
    cosine_similarity,
    match_filter,
    pack_vector,
    unpack_vector,
)


class SqliteVecDatabase:
    """Synchronous SQLite database executor and schema custodian."""

    def __init__(self, config: SqliteVecConfig) -> None:
        """Initialize database executor."""
        self.config: SqliteVecConfig = config
        self.db_path: Path = config.resolved_path()
        self.engine_mode: SqliteVecEngineMode = SqliteVecEngineMode.PROCESS_BLOB
        self._init_db()

    def open_connection(self) -> sqlite3.Connection:
        """Create a fresh configured SQLite connection."""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=self.config.busy_timeout_ms / 1000.0,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        if self.config.wal_mode:
            conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA synchronous={self.config.synchronous}")
        conn.execute(f"PRAGMA busy_timeout={self.config.busy_timeout_ms}")
        return conn

    def _init_db(self) -> None:
        """Initialize tables and probe native extension track."""
        conn = self.open_connection()
        try:
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS myrm_vec_collections (
                        name TEXT PRIMARY KEY,
                        dimension INTEGER NOT NULL,
                        distance TEXT NOT NULL,
                        created_at REAL NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS myrm_vec_documents (
                        id TEXT NOT NULL,
                        collection TEXT NOT NULL,
                        content TEXT NOT NULL,
                        vector_blob BLOB,
                        metadata TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL,
                        importance_weight REAL NOT NULL,
                        PRIMARY KEY (collection, id)
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_doc_collection
                    ON myrm_vec_documents(collection)
                """)

            if self.config.enable_vec_extension:
                try:
                    conn.enable_load_extension(True)
                    if self.config.vec_extension_path:
                        conn.load_extension(self.config.vec_extension_path)
                    else:
                        import sqlite_vec

                        sqlite_vec.load(conn)
                    self.engine_mode = SqliteVecEngineMode.NATIVE_VEC0
                except Exception:
                    self.engine_mode = SqliteVecEngineMode.PROCESS_BLOB
        finally:
            conn.close()

    def create_collection(
        self, name: str, dimension: int, distance: str = "cosine"
    ) -> bool:
        """Create collection metadata record."""
        conn = self.open_connection()
        try:
            now = datetime.now(UTC).timestamp()
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO myrm_vec_collections "
                    "(name, dimension, distance, created_at) VALUES (?, ?, ?, ?)",
                    (name, dimension, distance, now),
                )
            return True
        finally:
            conn.close()

    def delete_collection(self, name: str) -> bool:
        """Delete collection metadata and associated documents."""
        conn = self.open_connection()
        try:
            with conn:
                conn.execute("DELETE FROM myrm_vec_documents WHERE collection = ?", (name,))
                conn.execute("DELETE FROM myrm_vec_collections WHERE name = ?", (name,))
            return True
        finally:
            conn.close()

    def list_collections(self) -> list[str]:
        """List names of all registered collections."""
        conn = self.open_connection()
        try:
            cursor = conn.execute("SELECT name FROM myrm_vec_collections ORDER BY name ASC")
            return [row["name"] for row in cursor.fetchall()]
        finally:
            conn.close()

    def collection_exists(self, name: str) -> bool:
        """Check whether collection exists."""
        conn = self.open_connection()
        try:
            row = conn.execute(
                "SELECT 1 FROM myrm_vec_collections WHERE name = ?", (name,)
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def get_collection_info(self, name: str) -> CollectionInfo | None:
        """Retrieve collection metadata and total document count."""
        conn = self.open_connection()
        try:
            row = conn.execute(
                "SELECT dimension, distance FROM myrm_vec_collections WHERE name = ?", (name,)
            ).fetchone()
            if not row:
                return None
            cnt = conn.execute(
                "SELECT COUNT(*) FROM myrm_vec_documents WHERE collection = ?", (name,)
            ).fetchone()[0]
            return CollectionInfo(
                name=name,
                dimension=row["dimension"],
                distance=row["distance"],
                count=cnt,
            )
        finally:
            conn.close()

    def upsert_documents(
        self, collection: str, documents: list[VectorDocument]
    ) -> list[str]:
        """Insert or update batch of vector documents."""
        conn = self.open_connection()
        try:
            now_ts = datetime.now(UTC).timestamp()
            upserted_ids: list[str] = []
            with conn:
                for doc in documents:
                    blob = pack_vector(doc.vector) if doc.vector else None
                    meta_str = json.dumps(doc.metadata)
                    c_ts = doc.created_at.timestamp() if doc.created_at else now_ts
                    u_ts = doc.updated_at.timestamp() if doc.updated_at else now_ts
                    raw_w = doc.metadata.get("importance_weight", 1.0)
                    imp_weight = float(raw_w) if isinstance(raw_w, (int, float, str)) else 1.0
                    conn.execute(
                        """
                        INSERT INTO myrm_vec_documents
                        (id, collection, content, vector_blob, metadata, created_at, updated_at, importance_weight)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(collection, id) DO UPDATE SET
                            content=excluded.content,
                            vector_blob=excluded.vector_blob,
                            metadata=excluded.metadata,
                            updated_at=excluded.updated_at,
                            importance_weight=excluded.importance_weight
                        """,
                        (
                            doc.id,
                            collection,
                            doc.content,
                            blob,
                            meta_str,
                            c_ts,
                            u_ts,
                            imp_weight,
                        ),
                    )
                    upserted_ids.append(doc.id)
            return upserted_ids
        finally:
            conn.close()

    def get_documents(self, collection: str, ids: list[str]) -> list[VectorDocument]:
        """Fetch documents by ID list."""
        conn = self.open_connection()
        try:
            placeholders = ",".join("?" for _ in ids)
            cursor = conn.execute(
                f"SELECT * FROM myrm_vec_documents WHERE collection = ? AND id IN ({placeholders})",
                [collection, *ids],
            )
            results: list[VectorDocument] = []
            for row in cursor.fetchall():
                vec = unpack_vector(row["vector_blob"]) if row["vector_blob"] else None
                meta = json.loads(row["metadata"])
                c_dt = datetime.fromtimestamp(row["created_at"], tz=UTC)
                u_dt = datetime.fromtimestamp(row["updated_at"], tz=UTC)
                results.append(
                    VectorDocument(
                        id=row["id"],
                        content=row["content"],
                        vector=vec,
                        metadata=meta,
                        created_at=c_dt,
                        updated_at=u_dt,
                    )
                )
            return results
        finally:
            conn.close()

    def search_documents(
        self,
        collection: str,
        query_vector: list[float],
        limit: int = 10,
        filters: FilterDict | None = None,
        score_threshold: float | None = None,
    ) -> list[SearchResult]:
        """Search documents by cosine similarity."""
        conn = self.open_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM myrm_vec_documents WHERE collection = ? AND vector_blob IS NOT NULL",
                (collection,),
            )
            candidates: list[SearchResult] = []
            for row in cursor.fetchall():
                meta = json.loads(row["metadata"])
                if not match_filter(meta, filters):
                    continue
                doc_vec = unpack_vector(row["vector_blob"])
                sim = cosine_similarity(query_vector, doc_vec)
                if score_threshold is not None and sim < score_threshold:
                    continue
                c_dt = datetime.fromtimestamp(row["created_at"], tz=UTC)
                u_dt = datetime.fromtimestamp(row["updated_at"], tz=UTC)
                doc = VectorDocument(
                    id=row["id"],
                    content=row["content"],
                    vector=doc_vec,
                    metadata=meta,
                    created_at=c_dt,
                    updated_at=u_dt,
                )
                candidates.append(SearchResult(document=doc, score=sim))
            candidates.sort(key=lambda x: x.score, reverse=True)
            return candidates[:limit]
        finally:
            conn.close()

    def delete_documents(self, collection: str, ids: list[str]) -> int:
        """Delete documents by ID list."""
        conn = self.open_connection()
        try:
            placeholders = ",".join("?" for _ in ids)
            with conn:
                cursor = conn.execute(
                    f"DELETE FROM myrm_vec_documents WHERE collection = ? AND id IN ({placeholders})",
                    [collection, *ids],
                )
                return cursor.rowcount
        finally:
            conn.close()

    def scroll_documents(
        self,
        collection: str,
        limit: int = 100,
        offset: str | None = None,
        filters: FilterDict | None = None,
    ) -> tuple[list[VectorDocument], str | None]:
        """Scroll documents with cursor pagination."""
        conn = self.open_connection()
        try:
            query = "SELECT * FROM myrm_vec_documents WHERE collection = ?"
            params: list[str] = [collection]
            if offset:
                query += " AND id > ?"
                params.append(offset)
            query += " ORDER BY id ASC LIMIT ?"
            params.append(str(limit + 1))

            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            docs: list[VectorDocument] = []
            for row in rows:
                meta = json.loads(row["metadata"])
                if not match_filter(meta, filters):
                    continue
                vec = unpack_vector(row["vector_blob"]) if row["vector_blob"] else None
                c_dt = datetime.fromtimestamp(row["created_at"], tz=UTC)
                u_dt = datetime.fromtimestamp(row["updated_at"], tz=UTC)
                docs.append(
                    VectorDocument(
                        id=row["id"],
                        content=row["content"],
                        vector=vec,
                        metadata=meta,
                        created_at=c_dt,
                        updated_at=u_dt,
                    )
                )
            next_offset = None
            if len(docs) > limit:
                next_offset = docs[limit - 1].id
                docs = docs[:limit]
            return docs, next_offset
        finally:
            conn.close()

    def count_documents(self, collection: str) -> int:
        """Count total documents in collection."""
        conn = self.open_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM myrm_vec_documents WHERE collection = ?", (collection,)
            ).fetchone()
            return cast(int, row[0]) if row else 0
        finally:
            conn.close()
