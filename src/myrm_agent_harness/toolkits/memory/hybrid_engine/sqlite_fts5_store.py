"""Embedded SQLite FTS5 storage and retrieval engine.

[INPUT]
- toolkits.memory.hybrid_engine.models::HybridMemoryItem, HybridSearchResult (POS: Types and models for hybrid
  engine.)

[OUTPUT]
- SqliteFts5Engine: Embedded SQLite FTS5 storage and retrieval engine.

[POS]
Embedded SQLite FTS5 storage and retrieval engine.
"""

import datetime
import json
import sqlite3
from pathlib import Path

from myrm_agent_harness.toolkits.memory.hybrid_engine.models import (
    HybridMemoryItem,
    HybridSearchResult,
)


class SqliteFts5Engine:
    """Embedded SQLite FTS5 storage and retrieval engine.

    Employs native unicode61 tokenization, zero external service dependencies,
    and sub-millisecond BM25 ranking.
    """

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        """Create standard FTS5 virtual table and secondary metadata table."""
        with self._conn:
            self._conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS hybrid_memory_fts USING fts5(
                    item_id UNINDEXED,
                    title,
                    content,
                    tags,
                    metadata_json UNINDEXED,
                    created_at UNINDEXED,
                    tokenize = 'unicode61'
                );
                """
            )

    @property
    def db_path(self) -> str:
        return self._db_path

    def insert_or_replace_item(self, item: HybridMemoryItem) -> None:
        """Insert or replace an item in the FTS5 virtual table."""
        created_at = item.created_at or datetime.datetime.now(datetime.UTC).isoformat()
        tags_str = " ".join(item.tags)
        meta_str = json.dumps(item.metadata, ensure_ascii=False)

        with self._conn:
            # Delete any existing row with the same item_id first to maintain uniqueness
            self._conn.execute(
                "DELETE FROM hybrid_memory_fts WHERE item_id = ?",
                (item.item_id,),
            )
            self._conn.execute(
                """
                INSERT INTO hybrid_memory_fts(item_id, title, content, tags, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (item.item_id, item.title, item.content, tags_str, meta_str, created_at),
            )

    def delete_item(self, item_id: str) -> bool:
        """Remove an item from FTS5 virtual table by item_id."""
        with self._conn:
            cur = self._conn.execute(
                "DELETE FROM hybrid_memory_fts WHERE item_id = ?",
                (item_id,),
            )
            return cur.rowcount > 0

    def get_item(self, item_id: str) -> HybridMemoryItem | None:
        """Fetch item by item_id from the FTS5 table."""
        cur = self._conn.execute(
            """
            SELECT item_id, title, content, tags, metadata_json, created_at
            FROM hybrid_memory_fts
            WHERE item_id = ?
            LIMIT 1;
            """,
            (item_id,),
        )
        row = cur.fetchone()
        if not row:
            return None

        tags = [t for t in str(row["tags"]).split(" ") if t]
        raw_meta = str(row["metadata_json"])
        parsed_meta: dict[str, str | int | float | bool] = {}
        try:
            val = json.loads(raw_meta)
            if isinstance(val, dict):
                for k, v in val.items():
                    if isinstance(v, (str, int, float, bool)):
                        parsed_meta[str(k)] = v
        except Exception:
            pass

        return HybridMemoryItem(
            item_id=str(row["item_id"]),
            title=str(row["title"]),
            content=str(row["content"]),
            tags=tags,
            metadata=parsed_meta,
            created_at=str(row["created_at"]),
        )

    def search_fts(self, match_clause: str, limit: int = 10) -> list[HybridSearchResult]:
        """Perform sub-millisecond FTS5 search using native BM25 rank scoring."""
        if not match_clause.strip():
            return []

        try:
            # bm25(hybrid_memory_fts, title_weight, content_weight, tags_weight)
            # Smaller bm25() score indicates better match in SQLite FTS5 (negative ranking)
            cur = self._conn.execute(
                """
                SELECT item_id, title, content, bm25(hybrid_memory_fts, 5.0, 1.0, 2.0) AS score
                FROM hybrid_memory_fts
                WHERE hybrid_memory_fts MATCH ?
                ORDER BY score ASC
                LIMIT ?;
                """,
                (match_clause, limit),
            )
            rows = cur.fetchall()
            results: list[HybridSearchResult] = []
            for rank, row in enumerate(rows, start=1):
                raw_score = float(row["score"])
                # Invert negative FTS5 BM25 score into positive normalized score
                normalized_score = round(abs(raw_score) + 1.0, 4)
                results.append(
                    HybridSearchResult(
                        item_id=str(row["item_id"]),
                        title=str(row["title"]),
                        content=str(row["content"]),
                        score=normalized_score,
                        source_channel="fts",
                        rank=rank,
                        matched_terms=[],
                    )
                )
            return results
        except sqlite3.OperationalError:
            # Safe degradation if complex syntax fails
            return self._fallback_like_search(match_clause, limit)

    def _fallback_like_search(self, query: str, limit: int = 10) -> list[HybridSearchResult]:
        """Graceful fallback if FTS5 MATCH clause fails parsing."""
        clean = "".join(c for c in query if c.isalnum() or c in (" ", "\u4e00-\u9fff")).strip()
        if not clean:
            return []

        cur = self._conn.execute(
            """
            SELECT item_id, title, content
            FROM hybrid_memory_fts
            WHERE title LIKE ? OR content LIKE ?
            LIMIT ?;
            """,
            (f"%{clean}%", f"%{clean}%", limit),
        )
        rows = cur.fetchall()
        return [
            HybridSearchResult(
                item_id=str(row["item_id"]),
                title=str(row["title"]),
                content=str(row["content"]),
                score=0.5,
                source_channel="fts_like_fallback",
                rank=idx,
                matched_terms=[clean],
            )
            for idx, row in enumerate(rows, start=1)
        ]

    def count_items(self) -> int:
        """Return total row count in FTS table."""
        cur = self._conn.execute("SELECT count(*) AS total FROM hybrid_memory_fts;")
        row = cur.fetchone()
        return int(row["total"]) if row else 0

    def close(self) -> None:
        """Close SQLite database connection."""
        self._conn.close()
