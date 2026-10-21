"""Unit tests for FTS schema migration and truth retention in fts_search."""

import sqlite3
from pathlib import Path

from myrm_agent_harness.toolkits.wiki.retrieval.fts_search import migrate_wiki_fts_schema


def _legacy_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE VIRTUAL TABLE wiki_fts USING fts5(
            concept_name,
            truth_content,
            tokenize="unicode61 remove_diacritics 1"
        )
    """
    )
    conn.execute(
        "INSERT INTO wiki_fts (concept_name, truth_content) VALUES (?, ?)",
        ("Legacy Concept", "legacy searchable content"),
    )
    conn.commit()
    return conn


def _columns(conn: sqlite3.Connection) -> set[str]:
    return {str(row[1]) for row in conn.execute("PRAGMA table_info(wiki_fts)").fetchall()}


def test_migrates_legacy_schema_and_preserves_rows(tmp_path: Path) -> None:
    conn = _legacy_db(tmp_path / "legacy.db")
    try:
        assert _columns(conn) == {"concept_name", "truth_content"}

        migrate_wiki_fts_schema(conn)

        assert _columns(conn) == {"concept_name", "truth_content", "search_terms"}
        row = conn.execute(
            "SELECT truth_content, search_terms FROM wiki_fts WHERE concept_name = ?",
            ("Legacy Concept",),
        ).fetchone()
        assert row == ("legacy searchable content", "legacy searchable content")
    finally:
        conn.close()


def test_migration_is_idempotent_on_current_schema(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "current.db")
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE wiki_fts USING fts5(
                concept_name,
                truth_content,
                search_terms,
                tokenize="unicode61 remove_diacritics 1"
            )
        """
        )
        conn.execute(
            "INSERT INTO wiki_fts (concept_name, truth_content, search_terms) VALUES (?, ?, ?)",
            ("Current Concept", "Original Truth", "original truth tokens"),
        )
        conn.commit()

        migrate_wiki_fts_schema(conn)

        row = conn.execute(
            "SELECT truth_content, search_terms FROM wiki_fts WHERE concept_name = ?",
            ("Current Concept",),
        ).fetchone()
        assert row == ("Original Truth", "original truth tokens")
    finally:
        conn.close()
