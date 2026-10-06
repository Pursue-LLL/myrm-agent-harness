# [POS] toolkits/memory/wiki_memory/derived_indexer.py
# [INPUT] sqlite3, pathlib.Path, time, types.WikiMemoryPage, types.WikiSearchMatch, types.WikiIndexRebuildResult, types.WikiLinkRef, types.WikiScopeLevel
# [OUTPUT] DerivedWikiSqliteIndexer

"""Derived SQLite indexer providing FTS5 full-text search and Obsidian backlink topology."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from .types import (
    WikiIndexRebuildResult,
    WikiLinkRef,
    WikiScopeLevel,
    WikiSearchMatch,
)


class DerivedWikiSqliteIndexer:
    """Maintains derived FTS5 and link graph indexes reconstructable from Markdown at any time."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        """Create a dedicated connection with foreign keys and WAL journal mode enabled."""
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_schema(self) -> None:
        """Initialize relational tables and FTS5 virtual full-text index."""
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS wiki_pages_derived (
                    page_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    profile_id TEXT,
                    tags_csv TEXT,
                    updated_at REAL NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS wiki_links (
                    source_page_id TEXT NOT NULL,
                    target_page_title TEXT NOT NULL,
                    link_text TEXT,
                    section TEXT,
                    PRIMARY KEY (source_page_id, target_page_title)
                );
                """
            )
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS wiki_fts USING fts5(
                    page_id UNINDEXED,
                    title,
                    content,
                    tags,
                    tokenize='porter unicode61'
                );
                """
            )

    def index_page(
        self,
        page_id: str,
        title: str,
        content: str,
        scope: WikiScopeLevel,
        profile_id: str | None,
        tags: list[str],
        links: list[WikiLinkRef],
        updated_at: float,
    ) -> None:
        """Upsert a page into derived relational tables and refresh FTS5 index."""
        tags_csv = ",".join(tags)
        with self._get_connection() as conn:
            # 1. Update metadata table
            conn.execute(
                """
                INSERT INTO wiki_pages_derived (page_id, title, content, scope, profile_id, tags_csv, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(page_id) DO UPDATE SET
                    title=excluded.title,
                    content=excluded.content,
                    scope=excluded.scope,
                    profile_id=excluded.profile_id,
                    tags_csv=excluded.tags_csv,
                    updated_at=excluded.updated_at;
                """,
                (page_id, title, content, scope.value, profile_id, tags_csv, updated_at),
            )

            # 2. Refresh FTS5 entries
            conn.execute("DELETE FROM wiki_fts WHERE page_id = ?;", (page_id,))
            conn.execute(
                "INSERT INTO wiki_fts (page_id, title, content, tags) VALUES (?, ?, ?, ?);",
                (page_id, title, content, tags_csv),
            )

            # 3. Update links table
            conn.execute("DELETE FROM wiki_links WHERE source_page_id = ?;", (page_id,))
            for link in links:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO wiki_links (source_page_id, target_page_title, link_text, section)
                    VALUES (?, ?, ?, ?);
                    """,
                    (page_id, link.target_page_title.lower(), link.link_text, link.section),
                )

    def remove_page(self, page_id: str) -> None:
        """Remove a page from derived tables and FTS index."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM wiki_pages_derived WHERE page_id = ?;", (page_id,))
            conn.execute("DELETE FROM wiki_fts WHERE page_id = ?;", (page_id,))
            conn.execute("DELETE FROM wiki_links WHERE source_page_id = ?;", (page_id,))

    def search(
        self,
        query: str,
        scope: WikiScopeLevel | None = None,
        profile_id: str | None = None,
        limit: int = 10,
    ) -> list[WikiSearchMatch]:
        """Execute BM25 ranked full-text query across FTS5 virtual table with scope filtering."""
        clean_q = query.replace('"', '""').strip()
        if not clean_q:
            return []

        # Sanitize query for FTS5 syntax
        fts_query = f'"{clean_q}"'

        with self._get_connection() as conn:
            # Join FTS5 matches with metadata table for scope isolation
            sql = """
                SELECT
                    p.page_id,
                    p.title,
                    p.scope,
                    p.profile_id,
                    p.tags_csv,
                    bm25(wiki_fts) as rank_score,
                    snippet(wiki_fts, 2, '<b>', '</b>', '...', 16) as match_snippet
                FROM wiki_fts f
                JOIN wiki_pages_derived p ON f.page_id = p.page_id
                WHERE wiki_fts MATCH ?
            """
            params: list[str | int] = [fts_query]

            if scope is not None:
                sql += " AND p.scope = ?"
                params.append(scope.value)

            if profile_id is not None:
                sql += " AND (p.scope = 'global' OR p.profile_id = ?)"
                params.append(profile_id)

            sql += " ORDER BY rank_score ASC LIMIT ?"
            params.append(limit)

            try:
                cursor = conn.execute(sql, params)
                rows = cursor.fetchall()
            except sqlite3.OperationalError:
                # Fallback to simple title/content LIKE match if FTS syntax fails
                return self._fallback_like_search(query, scope, profile_id, limit)

            results: list[WikiSearchMatch] = []
            for r in rows:
                tags = [t.strip() for t in r["tags_csv"].split(",") if t.strip()] if r["tags_csv"] else []
                results.append(
                    WikiSearchMatch(
                        page_id=r["page_id"],
                        title=r["title"],
                        snippet=r["match_snippet"],
                        scope=WikiScopeLevel(r["scope"]),
                        profile_id=r["profile_id"],
                        score=float(abs(r["rank_score"])),
                        tags=tags,
                    )
                )
            return results

    def _fallback_like_search(
        self,
        query: str,
        scope: WikiScopeLevel | None,
        profile_id: str | None,
        limit: int,
    ) -> list[WikiSearchMatch]:
        """Fallback substring search when FTS syntax encounter unexpected token error."""
        pattern = f"%{query}%"
        with self._get_connection() as conn:
            sql = """
                SELECT page_id, title, content, scope, profile_id, tags_csv
                FROM wiki_pages_derived
                WHERE (title LIKE ? OR content LIKE ?)
            """
            params: list[str | int] = [pattern, pattern]
            if scope is not None:
                sql += " AND scope = ?"
                params.append(scope.value)
            if profile_id is not None:
                sql += " AND (scope = 'global' OR profile_id = ?)"
                params.append(profile_id)

            sql += " LIMIT ?"
            params.append(limit)
            cursor = conn.execute(sql, params)

            matches: list[WikiSearchMatch] = []
            for r in cursor.fetchall():
                tags = [t.strip() for t in r["tags_csv"].split(",") if t.strip()] if r["tags_csv"] else []
                matches.append(
                    WikiSearchMatch(
                        page_id=r["page_id"],
                        title=r["title"],
                        snippet=r["content"][:120],
                        scope=WikiScopeLevel(r["scope"]),
                        profile_id=r["profile_id"],
                        score=0.5,
                        tags=tags,
                    )
                )
            return matches

    def get_backlinks(self, target_page_title: str) -> list[WikiLinkRef]:
        """Find all pages that link to the specified target title (Obsidian backlinks)."""
        target_norm = target_page_title.lower().strip()
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT source_page_id, target_page_title, link_text, section
                FROM wiki_links
                WHERE target_page_title = ?;
                """,
                (target_norm,),
            )
            return [
                WikiLinkRef(
                    source_page_id=r["source_page_id"],
                    target_page_title=r["target_page_title"],
                    link_text=r["link_text"] or "",
                    section=r["section"],
                )
                for r in cursor.fetchall()
            ]

    def rebuild_all_from_markdown(
        self,
        pages: list[tuple[str, str, str, WikiScopeLevel, str | None, list[str], list[WikiLinkRef], float]],
    ) -> WikiIndexRebuildResult:
        """Purge and recreate entire derived index from scratch (100% idempotent cold recovery)."""
        start = time.perf_counter()
        self._init_schema()
        with self._get_connection() as conn:
            conn.execute("DELETE FROM wiki_pages_derived;")
            conn.execute("DELETE FROM wiki_fts;")
            conn.execute("DELETE FROM wiki_links;")

        total_links = 0
        for p_id, title, content, scope, pid, tags, links, updated_at in pages:
            self.index_page(
                page_id=p_id,
                title=title,
                content=content,
                scope=scope,
                profile_id=pid,
                tags=tags,
                links=links,
                updated_at=updated_at,
            )
            total_links += len(links)

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return WikiIndexRebuildResult(
            rebuilt_pages=len(pages),
            rebuilt_links=total_links,
            duration_ms=elapsed_ms,
            status="success",
        )
