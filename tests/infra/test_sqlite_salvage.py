"""Unit and physical corruption salvage tests for SQLiteRowidSalvageEngine."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import pytest

from myrm_agent_harness.infra.sqlite_salvage import SQLiteRowidSalvageEngine


@contextmanager
def open_db(path: Path | str) -> Generator[sqlite3.Connection]:
    """Helper context manager that commits and always closes the connection."""
    conn = sqlite3.connect(str(path))
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def salvage_engine() -> SQLiteRowidSalvageEngine:
    return SQLiteRowidSalvageEngine(chunk_size=50)


def test_salvage_healthy_database(tmp_path: Path, salvage_engine: SQLiteRowidSalvageEngine) -> None:
    src_db = tmp_path / "healthy.db"
    dst_db = tmp_path / "recovered.db"

    with open_db(src_db) as conn:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT);")
        for i in range(1, 101):
            conn.execute("INSERT INTO users VALUES (?, ?, ?);", (i, f"user_{i}", f"user_{i}@example.com"))

    inspection = salvage_engine.inspect_database(src_db)
    assert inspection["readable"] is True
    assert inspection["quick_check"] == "ok"

    result = salvage_engine.salvage_database(src_db, dst_db)
    assert result.success is True
    assert result.total_recovered_rows == 100
    assert result.table_stats["users"].status == "ok"
    assert len(result.table_stats["users"].skipped_ranges) == 0

    with open_db(dst_db) as conn:
        count = conn.execute("SELECT count(*) FROM users;").fetchone()[0]
        assert count == 100
        check = conn.execute("PRAGMA quick_check;").fetchone()[0]
        assert check == "ok"


def test_salvage_corrupted_btree_page(tmp_path: Path, salvage_engine: SQLiteRowidSalvageEngine) -> None:
    src_db = tmp_path / "corrupted.db"
    dst_db = tmp_path / "recovered.db"

    # Create a database with 500 records
    with open_db(src_db) as conn:
        conn.execute("PRAGMA page_size = 4096;")
        conn.execute(
            "CREATE TABLE messages (id INTEGER PRIMARY KEY, chat_id TEXT, content TEXT, created_at TEXT);"
        )
        for i in range(1, 501):
            conn.execute(
                "INSERT INTO messages VALUES (?, ?, ?, ?);",
                (i, f"chat_{i % 10}", f"Message content payload for item {i}" * 10, "2026-09-03 10:00:00"),
            )

    # Corrupt a single 4KB page in the middle of the database file
    file_bytes = bytearray(src_db.read_bytes())
    assert len(file_bytes) > 12288
    corrupt_offset = 8192 + 100
    file_bytes[corrupt_offset : corrupt_offset + 256] = b"\xff\x00\xde\xad" * 64
    src_db.write_bytes(file_bytes)

    # Verify that standard SQLite access throws DatabaseError
    with pytest.raises(sqlite3.DatabaseError), open_db(src_db) as conn:
        conn.execute("SELECT * FROM messages;").fetchall()

    # Run the salvage engine
    result = salvage_engine.salvage_database(src_db, dst_db)
    assert result.success is True
    # Most records should be recovered (>80%) despite the corrupted page
    assert result.total_recovered_rows > 350
    assert result.table_stats["messages"].status == "partial"
    assert len(result.table_stats["messages"].skipped_ranges) > 0

    # Ensure the recovered database is 100% clean and valid
    with open_db(dst_db) as conn:
        check = conn.execute("PRAGMA quick_check;").fetchone()[0]
        assert check == "ok"
        rec_count = conn.execute("SELECT count(*) FROM messages;").fetchone()[0]
        assert rec_count == result.total_recovered_rows


def test_salvage_without_rowid_table(tmp_path: Path, salvage_engine: SQLiteRowidSalvageEngine) -> None:
    src_db = tmp_path / "without_rowid.db"
    dst_db = tmp_path / "recovered.db"

    with open_db(src_db) as conn:
        conn.execute(
            "CREATE TABLE kv_store (key TEXT PRIMARY KEY, val TEXT) WITHOUT ROWID;"
        )
        for i in range(1, 51):
            conn.execute("INSERT INTO kv_store VALUES (?, ?);", (f"k_{i}", f"val_{i}"))

    result = salvage_engine.salvage_database(src_db, dst_db)
    assert result.success is True
    assert result.total_recovered_rows == 50
    assert result.table_stats["kv_store"].recovered_rows == 50

    with open_db(dst_db) as conn:
        count = conn.execute("SELECT count(*) FROM kv_store;").fetchone()[0]
        assert count == 50


def test_salvage_orphan_session_reconstruction(tmp_path: Path, salvage_engine: SQLiteRowidSalvageEngine) -> None:
    src_db = tmp_path / "relational.db"
    dst_db = tmp_path / "recovered.db"

    with open_db(src_db) as conn:
        conn.execute(
            """
            CREATE TABLE chats (
                id TEXT PRIMARY KEY,
                title TEXT,
                created_at TEXT,
                updated_at TEXT,
                action_mode TEXT DEFAULT 'fast',
                source TEXT DEFAULT 'web',
                total_calls INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                total_usd REAL DEFAULT 0.0
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY,
                chat_id TEXT REFERENCES chats(id),
                content TEXT,
                created_at TEXT
            );
            """
        )
        # 1 normal chat
        conn.execute("INSERT INTO chats (id, title) VALUES ('chat-parent-1', 'Parent 1');")
        conn.execute("INSERT INTO messages (id, chat_id, content, created_at) VALUES (1, 'chat-parent-1', 'msg 1', '2026-09-03 10:00:00');")
        # 2 orphaned messages whose chat parent is missing (e.g. destroyed in corrupted page)
        conn.execute("INSERT INTO messages (id, chat_id, content, created_at) VALUES (2, 'chat-orphan-99', 'orphan msg A', '2026-09-03 10:05:00');")
        conn.execute("INSERT INTO messages (id, chat_id, content, created_at) VALUES (3, 'chat-orphan-99', 'orphan msg B', '2026-09-03 10:06:00');")

    result = salvage_engine.salvage_database(src_db, dst_db)
    assert result.success is True
    assert result.orphans_reconstructed == 1

    with open_db(dst_db) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        fk_check = conn.execute("PRAGMA foreign_key_check;").fetchall()
        assert len(fk_check) == 0, f"Foreign key violations found: {fk_check}"

        stub_chat = conn.execute("SELECT id, title FROM chats WHERE id = 'chat-orphan-99';").fetchone()
        assert stub_chat is not None
        assert "Recovered Session" in stub_chat[1]


def test_salvage_fts_virtual_table(tmp_path: Path, salvage_engine: SQLiteRowidSalvageEngine) -> None:
    src_db = tmp_path / "fts.db"
    dst_db = tmp_path / "recovered.db"

    with open_db(src_db) as conn:
        conn.execute("CREATE TABLE docs (id INTEGER PRIMARY KEY, body TEXT);")
        conn.execute("CREATE VIRTUAL TABLE docs_fts USING fts5(body, content='docs', content_rowid='id');")
        conn.execute("INSERT INTO docs VALUES (1, 'Hello world sqlite salvage');")
        conn.execute("INSERT INTO docs VALUES (2, 'Agent harness durability');")
        conn.execute("INSERT INTO docs_fts(docs_fts) VALUES('rebuild');")

    result = salvage_engine.salvage_database(src_db, dst_db)
    assert result.success is True
    assert "docs_fts" in result.fts_rebuilt

    with open_db(dst_db) as conn:
        res = conn.execute("SELECT rowid FROM docs_fts WHERE docs_fts MATCH 'salvage';").fetchall()
        assert len(res) == 1
        assert res[0][0] == 1


def test_salvage_secondary_indexes_and_views(tmp_path: Path, salvage_engine: SQLiteRowidSalvageEngine) -> None:
    src_db = tmp_path / "indexes_views.db"
    dst_db = tmp_path / "recovered.db"

    with open_db(src_db) as conn:
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, category TEXT, score REAL);")
        conn.execute("CREATE INDEX idx_items_category ON items(category);")
        conn.execute("CREATE INDEX idx_items_score ON items(score DESC);")
        conn.execute("CREATE VIEW v_top_items AS SELECT id, category FROM items WHERE score > 80.0;")
        for i in range(1, 101):
            conn.execute("INSERT INTO items VALUES (?, ?, ?);", (i, f"cat_{i % 5}", float(i)))

    result = salvage_engine.salvage_database(src_db, dst_db)
    assert result.success is True
    assert "idx_items_category" in result.indexes_rebuilt
    assert "idx_items_score" in result.indexes_rebuilt
    assert "v_top_items" in result.views_rebuilt

    with open_db(dst_db) as conn:
        # Verify indexes exist and are valid
        indexes = [row[1] for row in conn.execute("PRAGMA index_list('items');").fetchall()]
        assert "idx_items_category" in indexes
        assert "idx_items_score" in indexes

        # Verify EXPLAIN QUERY PLAN uses index
        plan = conn.execute("EXPLAIN QUERY PLAN SELECT * FROM items WHERE category = 'cat_1';").fetchall()
        plan_str = " ".join(str(p) for p in plan)
        assert "USING INDEX idx_items_category" in plan_str

        # Verify view is queryable
        view_count = conn.execute("SELECT count(*) FROM v_top_items;").fetchone()[0]
        assert view_count == 20  # items 81 to 100


def test_salvage_nonexistent_database(tmp_path: Path, salvage_engine: SQLiteRowidSalvageEngine) -> None:
    non_existent = tmp_path / "ghost.db"
    dst_db = tmp_path / "out.db"

    result = salvage_engine.salvage_database(non_existent, dst_db)
    assert result.success is False
    assert "does not exist" in (result.error or "")

    # Test inspection on non-existent database
    inspection = salvage_engine.inspect_database(non_existent)
    assert inspection["exists"] is False
    assert inspection["readable"] is False


def test_salvage_direct_mode_and_cleanup(tmp_path: Path, salvage_engine: SQLiteRowidSalvageEngine) -> None:
    src_db = tmp_path / "direct_src.db"
    dst_db = tmp_path / "direct_dst.db"

    with open_db(src_db) as conn:
        conn.execute("CREATE TABLE config (k TEXT PRIMARY KEY, v TEXT);")
        conn.execute("INSERT INTO config VALUES ('theme', 'dark');")

    # Run with isolate_sandbox=False to exercise direct execution branch
    result = salvage_engine.salvage_database(src_db, dst_db, isolate_sandbox=False)
    assert result.success is True
    assert result.total_recovered_rows == 1

    # Overwrite existing destination with companion wal
    (tmp_path / "direct_dst.db-wal").write_bytes(b"dummy_wal")
    result2 = salvage_engine.salvage_database(src_db, dst_db, isolate_sandbox=True)
    assert result2.success is True
    assert result2.total_recovered_rows == 1


def test_salvage_empty_table_and_bounds_fallback(tmp_path: Path, salvage_engine: SQLiteRowidSalvageEngine) -> None:
    src_db = tmp_path / "empty.db"
    dst_db = tmp_path / "empty_out.db"

    with open_db(src_db) as conn:
        conn.execute("CREATE TABLE empty_tbl (id INTEGER PRIMARY KEY, note TEXT);")

    result = salvage_engine.salvage_database(src_db, dst_db)
    assert result.success is True
    assert result.table_stats["empty_tbl"].status == "empty"
    assert result.total_recovered_rows == 0
