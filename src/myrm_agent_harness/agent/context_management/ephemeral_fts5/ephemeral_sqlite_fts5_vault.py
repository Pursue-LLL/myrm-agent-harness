"""Ephemeral SQLite FTS5 session-isolated knowledge vault managing dual virtual tables.

[INPUT]
- DocumentChunk, EphemeralFts5Config, IndexReceipt: Domain definitions.

[OUTPUT]
- EphemeralSqliteFts5Vault: SQLite engine maintaining dual Porter and Trigram FTS5 indexes.

[POS]
Storage and inverted index management layer for ephemeral session FTS5 vault.
"""

from __future__ import annotations

import os
import sqlite3
from typing import Mapping, Sequence

from .ephemeral_fts5_types import DocumentChunk, EphemeralFts5Config, IndexReceipt


class EphemeralSqliteFts5Vault:
    """Manages ephemeral SQLite connection, metadata tables, and dual Porter/Trigram FTS5 virtual tables."""

    def __init__(
        self,
        session_id: str,
        config: EphemeralFts5Config | None = None,
        db_path: str | None = None,
    ) -> None:
        self._session_id = session_id
        self._config = config or EphemeralFts5Config()
        self._db_path = db_path or self._config.db_path_template

        # Ensure parent directory exists if using disk path
        if self._db_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(self._db_path)), exist_ok=True)

        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def db_path(self) -> str:
        return self._db_path

    def _init_schema(self) -> None:
        """Sets up physical metadata table and dual FTS5 virtual tables."""
        cursor = self._conn.cursor()
        cursor.executescript(
            """
            CREATE TABLE IF NOT EXISTS document_chunks (
                chunk_id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                heading_path TEXT NOT NULL,
                content TEXT NOT NULL,
                has_code_block INTEGER NOT NULL,
                char_count INTEGER NOT NULL,
                token_estimate INTEGER NOT NULL,
                content_hash TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_doc_session
            ON document_chunks (session_id, document_id);

            -- 1. Dual FTS5: Porter stemmer table
            CREATE VIRTUAL TABLE IF NOT EXISTS fts_porter USING fts5(
                chunk_id UNINDEXED,
                heading_path,
                content,
                tokenize = 'porter'
            );

            -- 2. Dual FTS5: Trigram substring table
            CREATE VIRTUAL TABLE IF NOT EXISTS fts_trigram USING fts5(
                chunk_id UNINDEXED,
                heading_path,
                content,
                tokenize = 'trigram'
            );
            """
        )
        self._conn.commit()

    def index_chunks(
        self,
        document_id: str,
        chunks: Sequence[DocumentChunk],
    ) -> IndexReceipt:
        """Idempotently writes document chunks into metadata and dual FTS5 tables."""
        if not chunks:
            return IndexReceipt(
                session_id=self._session_id,
                document_id=document_id,
                total_chunks=0,
                total_chars=0,
                total_tokens_estimated=0,
                db_path=self._db_path,
            )

        cursor = self._conn.cursor()
        # Delete existing chunks for this document to ensure idempotency
        self._delete_document_internal(cursor, document_id)

        meta_rows: list[tuple[str, str, str, str, str, int, int, int, str]] = []
        fts_rows: list[tuple[str, str, str]] = []

        total_chars = 0
        total_tokens = 0

        for ch in chunks:
            meta_rows.append(
                (
                    ch.chunk_id,
                    ch.document_id,
                    ch.session_id,
                    ch.heading_path,
                    ch.content,
                    1 if ch.has_code_block else 0,
                    ch.char_count,
                    ch.token_estimate,
                    ch.content_hash,
                )
            )
            fts_rows.append((ch.chunk_id, ch.heading_path, ch.content))
            total_chars += ch.char_count
            total_tokens += ch.token_estimate

        cursor.executemany(
            """
            INSERT OR REPLACE INTO document_chunks (
                chunk_id, document_id, session_id, heading_path,
                content, has_code_block, char_count, token_estimate, content_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            meta_rows,
        )

        cursor.executemany(
            "INSERT INTO fts_porter (chunk_id, heading_path, content) VALUES (?, ?, ?);",
            fts_rows,
        )
        cursor.executemany(
            "INSERT INTO fts_trigram (chunk_id, heading_path, content) VALUES (?, ?, ?);",
            fts_rows,
        )

        self._conn.commit()

        return IndexReceipt(
            session_id=self._session_id,
            document_id=document_id,
            total_chunks=len(chunks),
            total_chars=total_chars,
            total_tokens_estimated=total_tokens,
            db_path=self._db_path,
            status="success",
        )

    def delete_document(self, document_id: str) -> int:
        """Removes a document and its indexes from the vault."""
        cursor = self._conn.cursor()
        deleted = self._delete_document_internal(cursor, document_id)
        self._conn.commit()
        return deleted

    def _delete_document_internal(self, cursor: sqlite3.Cursor, document_id: str) -> int:
        cursor.execute(
            "SELECT chunk_id FROM document_chunks WHERE session_id = ? AND document_id = ?;",
            (self._session_id, document_id),
        )
        chunk_ids = [row[0] for row in cursor.fetchall()]
        if not chunk_ids:
            return 0

        cursor.execute(
            "DELETE FROM document_chunks WHERE session_id = ? AND document_id = ?;",
            (self._session_id, document_id),
        )
        # Clean from FTS virtual tables
        cursor.executemany(
            "DELETE FROM fts_porter WHERE chunk_id = ?;",
            [(cid,) for cid in chunk_ids],
        )
        cursor.executemany(
            "DELETE FROM fts_trigram WHERE chunk_id = ?;",
            [(cid,) for cid in chunk_ids],
        )
        return len(chunk_ids)

    def search_porter_raw(self, query: str, limit: int = 50) -> Sequence[tuple[str, int]]:
        """Queries the Porter FTS5 table returning ranked (chunk_id, rank) tuples."""
        sanitized = self._sanitize_fts_query(query)
        if not sanitized:
            return ()

        cursor = self._conn.cursor()
        try:
            cursor.execute(
                """
                SELECT chunk_id, rank
                FROM fts_porter
                WHERE fts_porter MATCH ?
                ORDER BY rank
                LIMIT ?;
                """,
                (sanitized, limit),
            )
            return [(row[0], idx + 1) for idx, row in enumerate(cursor.fetchall())]
        except sqlite3.OperationalError:
            return ()

    def search_trigram_raw(self, query: str, limit: int = 50) -> Sequence[tuple[str, int]]:
        """Queries the Trigram FTS5 table returning ranked (chunk_id, rank) tuples."""
        sanitized = self._sanitize_fts_query(query)
        if not sanitized:
            return ()

        cursor = self._conn.cursor()
        try:
            cursor.execute(
                """
                SELECT chunk_id, rank
                FROM fts_trigram
                WHERE fts_trigram MATCH ?
                ORDER BY rank
                LIMIT ?;
                """,
                (sanitized, limit),
            )
            return [(row[0], idx + 1) for idx, row in enumerate(cursor.fetchall())]
        except sqlite3.OperationalError:
            return ()

    def get_chunk_metadata_batch(self, chunk_ids: Sequence[str]) -> Mapping[str, DocumentChunk]:
        """Fetches full chunk metadata for requested chunk_ids in a single batch."""
        if not chunk_ids:
            return {}

        placeholders = ",".join("?" for _ in chunk_ids)
        cursor = self._conn.cursor()
        cursor.execute(
            f"""
            SELECT chunk_id, document_id, session_id, heading_path,
                   content, has_code_block, char_count, token_estimate, content_hash
            FROM document_chunks
            WHERE chunk_id IN ({placeholders});
            """,
            tuple(chunk_ids),
        )

        mapping: dict[str, DocumentChunk] = {}
        for row in cursor.fetchall():
            ch = DocumentChunk(
                chunk_id=row["chunk_id"],
                document_id=row["document_id"],
                session_id=row["session_id"],
                heading_path=row["heading_path"],
                content=row["content"],
                has_code_block=bool(row["has_code_block"]),
                char_count=row["char_count"],
                token_estimate=row["token_estimate"],
                content_hash=row["content_hash"],
            )
            mapping[ch.chunk_id] = ch
        return mapping

    def get_stats(self) -> dict[str, int]:
        """Returns statistics on the current ephemeral vault."""
        cursor = self._conn.cursor()
        cursor.execute(
            """
            SELECT COUNT(DISTINCT document_id) as doc_count,
                   COUNT(chunk_id) as chunk_count,
                   COALESCE(SUM(token_estimate), 0) as total_tokens
            FROM document_chunks
            WHERE session_id = ?;
            """,
            (self._session_id,),
        )
        row = cursor.fetchone()
        return {
            "document_count": row["doc_count"] if row else 0,
            "chunk_count": row["chunk_count"] if row else 0,
            "total_tokens": row["total_tokens"] if row else 0,
        }

    def close(self) -> None:
        """Closes the underlying SQLite connection."""
        self._conn.close()

    def destroy(self) -> None:
        """Closes connection and deletes physical file if not in-memory."""
        self.close()
        if self._db_path != ":memory:" and os.path.exists(self._db_path):
            try:
                os.remove(self._db_path)
            except OSError:
                pass

    @staticmethod
    def _sanitize_fts_query(query: str) -> str:
        """Sanitizes user queries removing syntax characters that break FTS5 parser."""
        # Replace problematic punctuation while preserving alphanumeric words
        clean_words = [w for w in query.replace('"', "").replace("'", "").replace("*", "").split() if w]
        if not clean_words:
            return ""
        return " OR ".join(f'"{w}"' for w in clean_words)
