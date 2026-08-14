"""Web Corpus Store — SQLite FTS5 two-tier persistent index.

Tier 1 (index): Lightweight metadata in SQLite FTS5 (URL, title, snippet, date).
Tier 2 (content): Full-text stored as files on disk, loaded on demand.

[INPUT]
- toolkits.web_fetch.url_normalizer::normalize_url (POS: URL dedup)
- utils.db.fts5::sanitize_fts5_query, fts5_auto_heal (POS: FTS5 safety)

[OUTPUT]
- WebCorpusStore: Persistent two-tier web corpus index with FTS5 search.

[POS]
Persistent web corpus index engine. Generic infrastructure toolkit, no agent/ imports.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from myrm_agent_harness.toolkits.web_fetch.url_normalizer import normalize_url
from myrm_agent_harness.utils.db.fts5 import fts5_auto_heal, sanitize_fts5_query

from .types import CorpusStats, WebCorpusEntry

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1


class WebCorpusStore:
    """Persistent two-tier web corpus index.

    Tier 1: SQLite FTS5 for lightweight metadata search (title, snippet, URL).
    Tier 2: File system for full-text content, loaded on demand via
    ``get_content()``.
    """

    def __init__(self, data_dir: str | Path) -> None:
        self._data_dir = Path(data_dir)
        self._db_path = self._data_dir / "web_corpus.db"
        self._content_dir = self._data_dir / "web_corpus_content"
        self._content_dir.mkdir(parents=True, exist_ok=True)

        self._conn = self._open_db()
        self._ensure_schema()

        self._hit_count = 0
        self._miss_count = 0

    def _open_db(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._conn:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS web_corpus_meta (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    normalized_url TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL DEFAULT '',
                    snippet TEXT NOT NULL DEFAULT '',
                    date TEXT,
                    source TEXT NOT NULL DEFAULT 'fetch',
                    agent_id TEXT,
                    access_count INTEGER NOT NULL DEFAULT 1,
                    content_hash TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    last_accessed TEXT NOT NULL
                )
            """)
            self._conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS web_corpus_fts USING fts5(
                    title, snippet, url,
                    content='web_corpus_meta',
                    content_rowid='id',
                    tokenize='unicode61'
                )
            """)
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_web_corpus_normalized
                ON web_corpus_meta(normalized_url)
            """)
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_web_corpus_agent
                ON web_corpus_meta(agent_id)
            """)
            self._conn.execute("""
                CREATE TRIGGER IF NOT EXISTS web_corpus_ai AFTER INSERT ON web_corpus_meta BEGIN
                    INSERT INTO web_corpus_fts(rowid, title, snippet, url)
                    VALUES (new.id, new.title, new.snippet, new.url);
                END
            """)
            self._conn.execute("""
                CREATE TRIGGER IF NOT EXISTS web_corpus_au AFTER UPDATE ON web_corpus_meta BEGIN
                    INSERT INTO web_corpus_fts(web_corpus_fts, rowid, title, snippet, url)
                    VALUES ('delete', old.id, old.title, old.snippet, old.url);
                    INSERT INTO web_corpus_fts(rowid, title, snippet, url)
                    VALUES (new.id, new.title, new.snippet, new.url);
                END
            """)
            self._conn.execute("""
                CREATE TRIGGER IF NOT EXISTS web_corpus_ad AFTER DELETE ON web_corpus_meta BEGIN
                    INSERT INTO web_corpus_fts(web_corpus_fts, rowid, title, snippet, url)
                    VALUES ('delete', old.id, old.title, old.snippet, old.url);
                END
            """)

    def upsert(
        self,
        url: str,
        title: str,
        snippet: str,
        content: str | None = None,
        date: str | None = None,
        source: str = "fetch",
        agent_id: str | None = None,
    ) -> None:
        """Insert or update a web page entry (UPSERT semantics on normalized URL)."""
        norm_url = normalize_url(url)
        now = datetime.now(UTC).isoformat()
        content_hash = ""

        if content:
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
            self._write_content(norm_url, content)

        with self._conn:
            existing = self._conn.execute(
                "SELECT id FROM web_corpus_meta WHERE normalized_url = ?",
                (norm_url,),
            ).fetchone()

            if existing:
                update_fields = {
                    "title": title,
                    "snippet": snippet,
                    "date": date,
                    "source": source,
                    "content_hash": content_hash,
                    "last_accessed": now,
                    "access_count": "access_count + 1",
                }
                if agent_id is not None:
                    update_fields["agent_id"] = agent_id

                set_parts: list[str] = []
                params: list[str | None] = []
                for k, v in update_fields.items():
                    if k == "access_count":
                        set_parts.append(f"{k} = {v}")
                    else:
                        set_parts.append(f"{k} = ?")
                        params.append(v)
                params.append(str(existing["id"]))

                self._conn.execute(
                    f"UPDATE web_corpus_meta SET {', '.join(set_parts)} WHERE id = ?",
                    params,
                )
            else:
                self._conn.execute(
                    """INSERT INTO web_corpus_meta
                       (url, normalized_url, title, snippet, date, source,
                        agent_id, content_hash, created_at, last_accessed)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (url, norm_url, title, snippet, date, source, agent_id, content_hash, now, now),
                )

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        agent_id: str | None = None,
    ) -> list[WebCorpusEntry]:
        """Search the corpus using FTS5 full-text search."""
        safe_query = sanitize_fts5_query(query)
        if not safe_query.strip():
            return []

        def _do_search() -> list[sqlite3.Row]:
            sql = """
                SELECT m.*, rank
                FROM web_corpus_fts f
                JOIN web_corpus_meta m ON f.rowid = m.id
                WHERE web_corpus_fts MATCH ?
            """
            params: list[str | None] = [safe_query]
            if agent_id is not None:
                sql += " AND m.agent_id = ?"
                params.append(agent_id)
            sql += " ORDER BY rank LIMIT ?"
            params.append(str(limit))
            return self._conn.execute(sql, params).fetchall()

        try:
            rows = _do_search()
        except sqlite3.OperationalError:
            fts5_auto_heal(self._conn, "web_corpus_fts")
            rows = _do_search()

        if rows:
            self._hit_count += 1
        else:
            self._miss_count += 1

        now = datetime.now(UTC).isoformat()
        row_ids = [str(r["id"]) for r in rows]
        if row_ids:
            placeholders = ",".join("?" for _ in row_ids)
            with self._conn:
                self._conn.execute(
                    f"UPDATE web_corpus_meta SET last_accessed = ? WHERE id IN ({placeholders})",
                    [now, *row_ids],
                )

        return [self._row_to_entry(r) for r in rows]

    def get_content(self, normalized_url: str) -> str | None:
        """Load full-text content from disk for a given normalized URL."""
        content_file = self._content_path_for(normalized_url)
        if content_file.exists():
            return content_file.read_text(encoding="utf-8")
        return None

    def get_stats(self) -> CorpusStats:
        """Return aggregate corpus statistics."""
        row = self._conn.execute("""
            SELECT COUNT(*) as cnt,
                   MIN(created_at) as oldest,
                   MAX(created_at) as newest
            FROM web_corpus_meta
        """).fetchone()

        disk_bytes = sum(f.stat().st_size for f in self._content_dir.rglob("*") if f.is_file())
        disk_bytes += self._db_path.stat().st_size if self._db_path.exists() else 0

        oldest = None
        newest = None
        if row and row["oldest"]:
            oldest = datetime.fromisoformat(row["oldest"])
        if row and row["newest"]:
            newest = datetime.fromisoformat(row["newest"])

        return CorpusStats(
            total_entries=row["cnt"] if row else 0,
            disk_bytes=disk_bytes,
            oldest_entry=oldest,
            newest_entry=newest,
            hit_count=self._hit_count,
            miss_count=self._miss_count,
        )

    def delete_by_normalized_url(self, normalized_url: str) -> bool:
        """Remove a single entry by its normalized URL."""
        content_file = self._content_path_for(normalized_url)
        if content_file.exists():
            content_file.unlink()

        with self._conn:
            cursor = self._conn.execute(
                "DELETE FROM web_corpus_meta WHERE normalized_url = ?",
                (normalized_url,),
            )
        return cursor.rowcount > 0

    def clear(self) -> int:
        """Remove all entries. Returns number of deleted rows."""
        with self._conn:
            cursor = self._conn.execute("DELETE FROM web_corpus_meta")
        for f in self._content_dir.rglob("*"):
            if f.is_file():
                f.unlink()
        return cursor.rowcount

    def list_stale(self, before_iso: str) -> list[str]:
        """Return normalized URLs of entries last accessed before the given ISO timestamp."""
        rows = self._conn.execute(
            "SELECT normalized_url FROM web_corpus_meta WHERE last_accessed < ? ORDER BY last_accessed ASC",
            (before_iso,),
        ).fetchall()
        return [r["normalized_url"] for r in rows]

    def list_lru(self) -> list[str]:
        """Return all normalized URLs ordered by least-recently-accessed first."""
        rows = self._conn.execute(
            "SELECT normalized_url FROM web_corpus_meta ORDER BY last_accessed ASC",
        ).fetchall()
        return [r["normalized_url"] for r in rows]

    def close(self) -> None:
        """Close the SQLite connection."""
        self._conn.close()

    def _write_content(self, normalized_url: str, content: str) -> str:
        path = self._content_path_for(normalized_url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return str(path)

    def _content_path_for(self, normalized_url: str) -> Path:
        url_hash = hashlib.sha256(normalized_url.encode()).hexdigest()
        return self._content_dir / url_hash[:2] / f"{url_hash}.txt"

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> WebCorpusEntry:
        return WebCorpusEntry(
            url=row["url"],
            normalized_url=row["normalized_url"],
            title=row["title"],
            snippet=row["snippet"],
            date=row["date"],
            source=row["source"],
            agent_id=row["agent_id"],
            access_count=row["access_count"],
            content_hash=row["content_hash"],
            created_at=datetime.fromisoformat(row["created_at"]),
            last_accessed=datetime.fromisoformat(row["last_accessed"]),
        )
