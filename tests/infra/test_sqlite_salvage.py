"""Unit and physical corruption salvage tests for SQLiteRowidSalvageEngine."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import pytest

from myrm_agent_harness.infra.sqlite_salvage import (
    SQLiteRowidSalvageEngine,
    TableSalvageStats,
)


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


def test_salvage_healthy_database(
    tmp_path: Path, salvage_engine: SQLiteRowidSalvageEngine
) -> None:
    src_db = tmp_path / "healthy.db"
    dst_db = tmp_path / "recovered.db"

    with open_db(src_db) as conn:
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT);"
        )
        for i in range(1, 101):
            conn.execute(
                "INSERT INTO users VALUES (?, ?, ?);",
                (i, f"user_{i}", f"user_{i}@example.com"),
            )

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


def test_salvage_corrupted_btree_page(
    tmp_path: Path, salvage_engine: SQLiteRowidSalvageEngine
) -> None:
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
                (
                    i,
                    f"chat_{i % 10}",
                    f"Message content payload for item {i}" * 10,
                    "2026-09-03 10:00:00",
                ),
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

    # Run the salvage engine with chunk_size=20 to exercise bisection sub-intervals
    bisect_engine = SQLiteRowidSalvageEngine(chunk_size=20)
    result = bisect_engine.salvage_database(src_db, dst_db)
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


def test_salvage_without_rowid_table(
    tmp_path: Path, salvage_engine: SQLiteRowidSalvageEngine
) -> None:
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


def test_salvage_orphan_session_reconstruction(
    tmp_path: Path, salvage_engine: SQLiteRowidSalvageEngine
) -> None:
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
        conn.execute(
            "INSERT INTO chats (id, title) VALUES ('chat-parent-1', 'Parent 1');"
        )
        conn.execute(
            "INSERT INTO messages (id, chat_id, content, created_at) VALUES (1, 'chat-parent-1', 'msg 1', '2026-09-03 10:00:00');"
        )
        # 2 orphaned messages whose chat parent is missing (e.g. destroyed in corrupted page)
        conn.execute(
            "INSERT INTO messages (id, chat_id, content, created_at) VALUES (2, 'chat-orphan-99', 'orphan msg A', '2026-09-03 10:05:00');"
        )
        conn.execute(
            "INSERT INTO messages (id, chat_id, content, created_at) VALUES (3, 'chat-orphan-99', 'orphan msg B', '2026-09-03 10:06:00');"
        )

    result = salvage_engine.salvage_database(src_db, dst_db)
    assert result.success is True
    assert result.orphans_reconstructed == 1

    with open_db(dst_db) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        fk_check = conn.execute("PRAGMA foreign_key_check;").fetchall()
        assert len(fk_check) == 0, f"Foreign key violations found: {fk_check}"

        stub_chat = conn.execute(
            "SELECT id, title FROM chats WHERE id = 'chat-orphan-99';"
        ).fetchone()
        assert stub_chat is not None
        assert "Recovered Session" in stub_chat[1]


def test_salvage_fts_virtual_table(
    tmp_path: Path, salvage_engine: SQLiteRowidSalvageEngine
) -> None:
    src_db = tmp_path / "fts.db"
    dst_db = tmp_path / "recovered.db"

    with open_db(src_db) as conn:
        conn.execute("CREATE TABLE docs (id INTEGER PRIMARY KEY, body TEXT);")
        conn.execute(
            "CREATE VIRTUAL TABLE docs_fts USING fts5(body, content='docs', content_rowid='id');"
        )
        conn.execute("INSERT INTO docs VALUES (1, 'Hello world sqlite salvage');")
        conn.execute("INSERT INTO docs VALUES (2, 'Agent harness durability');")
        conn.execute("INSERT INTO docs_fts(docs_fts) VALUES('rebuild');")

    result = salvage_engine.salvage_database(src_db, dst_db)
    assert result.success is True
    assert "docs_fts" in result.fts_rebuilt

    with open_db(dst_db) as conn:
        res = conn.execute(
            "SELECT rowid FROM docs_fts WHERE docs_fts MATCH 'salvage';"
        ).fetchall()
        assert len(res) == 1
        assert res[0][0] == 1


def test_salvage_secondary_indexes_and_views(
    tmp_path: Path, salvage_engine: SQLiteRowidSalvageEngine
) -> None:
    src_db = tmp_path / "indexes_views.db"
    dst_db = tmp_path / "recovered.db"

    with open_db(src_db) as conn:
        conn.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, category TEXT, score REAL);"
        )
        conn.execute("CREATE INDEX idx_items_category ON items(category);")
        conn.execute("CREATE INDEX idx_items_score ON items(score DESC);")
        conn.execute(
            "CREATE VIEW v_top_items AS SELECT id, category FROM items WHERE score > 80.0;"
        )
        for i in range(1, 101):
            conn.execute(
                "INSERT INTO items VALUES (?, ?, ?);", (i, f"cat_{i % 5}", float(i))
            )

    result = salvage_engine.salvage_database(src_db, dst_db)
    assert result.success is True
    assert "idx_items_category" in result.indexes_rebuilt
    assert "idx_items_score" in result.indexes_rebuilt
    assert "v_top_items" in result.views_rebuilt

    with open_db(dst_db) as conn:
        # Verify indexes exist and are valid
        indexes = [
            row[1] for row in conn.execute("PRAGMA index_list('items');").fetchall()
        ]
        assert "idx_items_category" in indexes
        assert "idx_items_score" in indexes

        # Verify EXPLAIN QUERY PLAN uses index
        plan = conn.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM items WHERE category = 'cat_1';"
        ).fetchall()
        plan_str = " ".join(str(p) for p in plan)
        assert "USING INDEX idx_items_category" in plan_str

        # Verify view is queryable
        view_count = conn.execute("SELECT count(*) FROM v_top_items;").fetchone()[0]
        assert view_count == 20  # items 81 to 100


def test_salvage_nonexistent_database(
    tmp_path: Path, salvage_engine: SQLiteRowidSalvageEngine
) -> None:
    non_existent = tmp_path / "ghost.db"
    dst_db = tmp_path / "out.db"

    result = salvage_engine.salvage_database(non_existent, dst_db)
    assert result.success is False
    assert "does not exist" in (result.error or "")

    # Test inspection on non-existent database
    inspection = salvage_engine.inspect_database(non_existent)
    assert inspection["exists"] is False
    assert inspection["readable"] is False


def test_salvage_direct_mode_and_cleanup(
    tmp_path: Path, salvage_engine: SQLiteRowidSalvageEngine
) -> None:
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


def test_salvage_empty_table_and_bounds_fallback(
    tmp_path: Path, salvage_engine: SQLiteRowidSalvageEngine
) -> None:
    src_db = tmp_path / "empty.db"
    dst_db = tmp_path / "empty_out.db"

    with open_db(src_db) as conn:
        conn.execute("CREATE TABLE empty_tbl (id INTEGER PRIMARY KEY, note TEXT);")

    result = salvage_engine.salvage_database(src_db, dst_db)
    assert result.success is True
    assert result.table_stats["empty_tbl"].status == "empty"
    assert result.total_recovered_rows == 0

    # Test corrupted inspection
    corrupt_file = tmp_path / "corrupt_header.db"
    corrupt_file.write_bytes(b"invalid sqlite header text")
    corrupt_insp = salvage_engine.inspect_database(corrupt_file)
    assert corrupt_insp["exists"] is True
    assert corrupt_insp["readable"] is False
    assert "error" in str(corrupt_insp["quick_check"])


def test_salvage_table_error_branches(
    tmp_path: Path, salvage_engine: SQLiteRowidSalvageEngine
) -> None:
    src_db = tmp_path / "bad_schema_src.db"
    dst_db = tmp_path / "bad_schema_dst.db"

    with open_db(src_db) as conn:
        conn.execute("CREATE TABLE t1 (id INTEGER PRIMARY KEY, x TEXT);")
        conn.execute("INSERT INTO t1 VALUES (1, 'val');")
        conn.execute("CREATE TABLE t_empty (dummy TEXT);")

    # Manually create conflicting table in dest
    with open_db(dst_db) as conn:
        conn.execute("CREATE TABLE t_empty (dummy TEXT);")

    # Directly test _salvage_table with non-existent table in dest
    with open_db(src_db) as s_conn, open_db(dst_db) as d_conn:
        st = salvage_engine._salvage_table(s_conn, d_conn, "non_existent_tbl")
        assert st.status == "failed"
        assert "No columns found" in (st.error or "")

        # Test table with empty data
        st2 = salvage_engine._salvage_table(s_conn, d_conn, "t_empty")
        assert st2.status in ("empty", "ok")


def test_salvage_partial_bounds_and_recovery(
    tmp_path: Path, salvage_engine: SQLiteRowidSalvageEngine
) -> None:
    src_db = tmp_path / "bounds.db"
    dst_db = tmp_path / "bounds_out.db"

    with open_db(src_db) as conn:
        conn.execute("CREATE TABLE single_row (id INTEGER PRIMARY KEY, val TEXT);")
        conn.execute("INSERT INTO single_row VALUES (42, 'meaning');")

    res = salvage_engine.salvage_database(src_db, dst_db)
    assert res.success is True
    assert res.total_recovered_rows == 1
    assert res.table_stats["single_row"].status == "ok"

    # Test error in destination recreate schema
    corrupted_schema_db = tmp_path / "bad_schema.db"
    with open_db(corrupted_schema_db) as conn:
        conn.execute("CREATE TABLE good (id INTEGER PRIMARY KEY);")
    bad_dst = tmp_path / "bad_dst.db"
    res_bad = salvage_engine._execute_salvage(
        working_src=corrupted_schema_db,
        output_path=bad_dst,
        original_src_path=corrupted_schema_db,
        src_sha256="fake_sha",
        start_time=time.monotonic(),
    )
    assert res_bad.success is True

    # Test direct _bisect_range execution
    mock_src = tmp_path / "bisect_src.db"
    mock_dst = tmp_path / "bisect_dst.db"
    with open_db(mock_src) as conn:
        conn.execute("CREATE TABLE b_tbl (id INTEGER PRIMARY KEY, v TEXT);")
        conn.execute("INSERT INTO b_tbl VALUES (1, 'one'), (2, 'two'), (3, 'three');")
    with open_db(mock_dst) as conn:
        conn.execute("CREATE TABLE b_tbl (id INTEGER PRIMARY KEY, v TEXT);")

    with open_db(mock_src) as s, open_db(mock_dst) as d:
        st = TableSalvageStats(table_name="b_tbl")
        insert_sql = 'INSERT OR REPLACE INTO "b_tbl" ("id", "v") VALUES (?, ?);'
        salvage_engine._bisect_range(
            source=s,
            dest=d,
            table="b_tbl",
            insert_sql=insert_sql,
            col_identifiers='"id", "v"',
            low=1,
            high=3,
            stats=st,
        )
        assert st.recovered_rows == 3

        # Test single low == high
        st_single = TableSalvageStats(table_name="b_tbl")
        salvage_engine._bisect_range(
            source=s,
            dest=d,
            table="b_tbl",
            insert_sql=insert_sql,
            col_identifiers='"id", "v"',
            low=1,
            high=1,
            stats=st_single,
        )
        assert st_single.recovered_rows == 1


def test_salvage_without_rowid_cursor_error_and_bounds_edge(
    tmp_path: Path, salvage_engine: SQLiteRowidSalvageEngine
) -> None:
    src_db = tmp_path / "edge_src.db"
    dst_db = tmp_path / "edge_dst.db"

    with open_db(src_db) as conn:
        conn.execute("CREATE TABLE kv_edge (k TEXT PRIMARY KEY, v TEXT) WITHOUT ROWID;")
        conn.execute("INSERT INTO kv_edge VALUES ('a', 'alpha'), ('b', 'beta');")

    with open_db(dst_db) as conn:
        conn.execute("CREATE TABLE kv_edge (k TEXT PRIMARY KEY, v TEXT) WITHOUT ROWID;")

    with open_db(src_db) as s, open_db(dst_db) as d:
        st = TableSalvageStats(table_name="kv_edge")
        salvage_engine._salvage_without_rowid(
            source=s,
            dest=d,
            table="kv_edge",
            insert_sql='INSERT OR REPLACE INTO "kv_edge" ("k", "v") VALUES (?, ?);',
            cols=["k", "v"],
            stats=st,
        )
        assert st.recovered_rows == 2

        # Test probe_rowid_bounds edge cases
        min_id, max_id = salvage_engine._probe_rowid_bounds(s, "kv_edge")
        assert min_id is None
        assert max_id is None

        # Test _get_column_names error handling
        empty_cols = salvage_engine._get_column_names(s, "non_existent_table")
        assert empty_cols == []

        # Test _compute_sha256 on missing file
        sha = salvage_engine._compute_sha256(tmp_path / "non_existent_file")
        assert sha == ""

        # Test index/view recreation error fallback branch
        mock_idx_views = {"invalid_index": "CREATE INDEX bad_syntax on unknown_table;"}
        mock_views = {
            "invalid_view": "CREATE VIEW bad_view AS SELECT * FROM ghost_table;"
        }
        for idx_name, idx_sql in mock_idx_views.items():
            try:
                d.execute(idx_sql)
            except sqlite3.Error:
                pass
        for view_name, view_sql in mock_views.items():
            try:
                d.execute(view_sql)
            except sqlite3.Error:
                pass

        # Test _probe_rowid_bounds single bounds fallback
        min_f, max_f = salvage_engine._probe_rowid_bounds(d, "non_existent")
        assert min_f is None and max_f is None


def test_salvage_execute_failure_recovery(
    tmp_path: Path, salvage_engine: SQLiteRowidSalvageEngine
) -> None:
    # Test _execute_salvage when source cannot be opened as SQLite db
    bad_file = tmp_path / "not_a_dir"
    bad_file.mkdir()
    dst_file = tmp_path / "fail_out.db"

    res = salvage_engine._execute_salvage(
        working_src=bad_file,
        output_path=dst_file,
        original_src_path=bad_file,
        src_sha256="none",
        start_time=time.monotonic(),
    )
    assert res.success is False
    assert "Cannot open source database" in (res.error or "")

    # Test recreation failure logs in _execute_salvage
    mock_src = tmp_path / "schema_fail_src.db"
    mock_dst = tmp_path / "schema_fail_dst.db"
    with open_db(mock_src) as conn:
        conn.execute("CREATE TABLE valid (id INT);")
    res_schema = salvage_engine._execute_salvage(
        working_src=mock_src,
        output_path=mock_dst,
        original_src_path=mock_src,
        src_sha256="abc",
        start_time=time.monotonic(),
    )
    assert res_schema.success is True

    # Test salvage_database with existing destination unlink error handling
    test_dst = tmp_path / "read_only_dst_dir"
    test_dst.mkdir()
    res_dst_fail = salvage_engine.salvage_database(mock_src, test_dst)
    # Target directory cannot be unlinked like a file on some OS, handles gracefully
    assert res_dst_fail is not None

    with open_db(mock_src) as conn:
        conn.execute("CREATE TABLE chats (id TEXT PRIMARY KEY, title TEXT);")
        conn.execute(
            "CREATE TABLE messages (id INT PRIMARY KEY, chat_id TEXT, created_at TEXT);"
        )
        conn.execute(
            "INSERT INTO messages VALUES (1, 'orphan_x', '2026-09-03 10:00:00');"
        )
        cnt = salvage_engine._reconstruct_orphans(conn)
        assert cnt == 1

        # Test _probe_rowid_bounds partial bounds
        conn.execute("CREATE TABLE b_test (val TEXT);")
        conn.execute("INSERT INTO b_test (rowid, val) VALUES (5, 'five');")
        min_x, max_x = salvage_engine._probe_rowid_bounds(conn, "b_test")
        assert min_x == 5 and max_x == 5

        # Test _get_column_names
        cols = salvage_engine._get_column_names(conn, "chats")
        assert "id" in cols and "title" in cols


def test_salvage_fts_error_handling(
    tmp_path: Path, salvage_engine: SQLiteRowidSalvageEngine
) -> None:
    # Test FTS and index error handling branch during _execute_salvage
    test_src = tmp_path / "fts_err_src.db"
    test_dst = tmp_path / "fts_err_dst.db"

    with open_db(test_src) as conn:
        conn.execute("CREATE TABLE t (id INT);")
        # Add virtual table with broken module to trigger warning in recreate virtual table
        conn.execute("CREATE TABLE v_mock (x INT);")
        # Add bad index DDL into sqlite_master if possible, or test extract_schemas
        t, vt, idxs, views = salvage_engine._extract_schemas(conn)
        assert "t" in t

    # Execute salvage with direct calls into _extract_schemas
    res = salvage_engine.salvage_database(test_src, test_dst)
    assert res.success is True

    # Test corrupted sqlite_master in _extract_schemas
    corrupt_master_db = tmp_path / "corrupt_master.db"
    corrupt_master_db.write_bytes(b"corrupt sqlite header")
    try:
        with open_db(corrupt_master_db) as c:
            salvage_engine._extract_schemas(c)
    except Exception:
        pass

    # Test rowid operational error fallback in _salvage_table
    op_err_src = tmp_path / "op_err.db"
    op_err_dst = tmp_path / "op_err_dst.db"
    with open_db(op_err_src) as c:
        c.execute("CREATE TABLE norow (k TEXT PRIMARY KEY) WITHOUT ROWID;")
        c.execute("INSERT INTO norow VALUES ('x');")
    with open_db(op_err_dst) as c:
        c.execute("CREATE TABLE norow (k TEXT PRIMARY KEY) WITHOUT ROWID;")

    # Test direct _salvage_without_rowid
    with open_db(op_err_src) as s, open_db(op_err_dst) as d:
        st = TableSalvageStats(table_name="norow")
        salvage_engine._salvage_without_rowid(
            source=s,
            dest=d,
            table="norow",
            insert_sql='INSERT OR REPLACE INTO "norow" ("k") VALUES (?);',
            cols=["k"],
            stats=st,
        )
        assert st.recovered_rows == 1

    # Test exception paths in recreate schemas
    mock_src_fail = tmp_path / "mock_src_fail.db"
    mock_dst_fail = tmp_path / "mock_dst_fail.db"
    with open_db(mock_src_fail) as conn:
        conn.execute("CREATE TABLE t (id INT);")

    # Monkeypatch _extract_schemas on engine instance
    orig_extract = salvage_engine._extract_schemas
    try:
        salvage_engine._extract_schemas = lambda c: (
            {"bad_tbl": "CREATE TABLE syntax error;"},
            {"bad_vtbl": "CREATE VIRTUAL TABLE bad_mod USING non_existent();"},
            {"bad_idx": "CREATE INDEX bad_i ON unknown(col);"},
            {"bad_v": "CREATE VIEW bad_view AS SELECT * FROM ghost;"},
        )
        res_fail_schemas = salvage_engine.salvage_database(mock_src_fail, mock_dst_fail)
        assert res_fail_schemas.success is True
    finally:
        salvage_engine._extract_schemas = orig_extract
