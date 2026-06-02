"""Unit tests for the file-level integrity & crash-recovery primitives."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from myrm_agent_harness.utils.db.sqlite import (
    DEFAULT,
    SQLiteIntegrityError,
    SQLiteProfile,
    check_page_count_invariant,
    checkpoint_truncate_async,
    checkpoint_truncate_sync,
    cleanup_orphan_wal,
    harden_connection_sync,
    on_disk_journal_mode_is_wal,
    prepare_database_file,
    quick_check_sync,
    validate_sqlite_header,
)
from myrm_agent_harness.utils.db.sqlite.integrity import _is_quick_check_ok


def _make_db(path: Path, *, rows: int = 2000, wal: bool = True) -> None:
    conn = sqlite3.connect(str(path))
    harden_connection_sync(conn, DEFAULT if wal else SQLiteProfile(use_wal=False), db_path=path)
    conn.execute("CREATE TABLE t(x INTEGER)")
    conn.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(rows)])
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()


# ── validate_sqlite_header ────────────────────────────────────────────


def test_header_missing_file_is_allowed(tmp_path: Path) -> None:
    validate_sqlite_header(tmp_path / "nope.db")  # no raise


def test_header_empty_file_is_allowed(tmp_path: Path) -> None:
    p = tmp_path / "empty.db"
    p.write_bytes(b"")
    validate_sqlite_header(p)  # no raise


def test_header_garbage_file_rejected(tmp_path: Path) -> None:
    p = tmp_path / "garbage.db"
    p.write_bytes(b"this is definitely not sqlite" * 8)
    with pytest.raises(SQLiteIntegrityError, match="not a SQLite database"):
        validate_sqlite_header(p)


def test_header_valid_db_accepted(tmp_path: Path) -> None:
    p = tmp_path / "ok.db"
    _make_db(p)
    validate_sqlite_header(p)  # no raise


# ── check_page_count_invariant ────────────────────────────────────────


def test_truncation_detected(tmp_path: Path) -> None:
    p = tmp_path / "trunc.db"
    _make_db(p, rows=5000)
    size = p.stat().st_size
    with p.open("r+b") as handle:
        handle.truncate(size - 8192)
    with pytest.raises(SQLiteIntegrityError, match="truncated"):
        check_page_count_invariant(p)


def test_healthy_db_passes_page_count(tmp_path: Path) -> None:
    p = tmp_path / "healthy.db"
    _make_db(p)
    check_page_count_invariant(p)  # no raise


def test_too_small_for_header_is_ignored(tmp_path: Path) -> None:
    p = tmp_path / "tiny.db"
    p.write_bytes(b"abc")
    check_page_count_invariant(p)  # no raise (cannot host a header)


def test_non_sqlite_file_skips_page_count(tmp_path: Path) -> None:
    p = tmp_path / "blob.bin"
    p.write_bytes(b"x" * 4096)
    check_page_count_invariant(p)  # header check is separate; no raise here


# ── cleanup_orphan_wal ────────────────────────────────────────────────


def test_orphan_wal_removed_for_empty_main(tmp_path: Path) -> None:
    main = tmp_path / "o.db"
    main.write_bytes(b"")
    wal = Path(f"{main}-wal")
    shm = Path(f"{main}-shm")
    wal.write_bytes(b"junk")
    shm.write_bytes(b"junk")
    cleanup_orphan_wal(main)
    assert not wal.exists()
    assert not shm.exists()


def test_wal_kept_for_nonempty_main(tmp_path: Path) -> None:
    main = tmp_path / "keep.db"
    _make_db(main)
    wal = Path(f"{main}-wal")
    wal.write_bytes(b"live-wal")
    cleanup_orphan_wal(main)
    assert wal.exists()  # main db has data → not an orphan


def test_cleanup_missing_main_is_noop(tmp_path: Path) -> None:
    cleanup_orphan_wal(tmp_path / "absent.db")  # no raise


# ── prepare_database_file ─────────────────────────────────────────────


def test_prepare_passes_for_healthy_db(tmp_path: Path) -> None:
    p = tmp_path / "prep.db"
    _make_db(p)
    prepare_database_file(p)  # cleanup + validate, no raise


def test_prepare_raises_on_truncation(tmp_path: Path) -> None:
    p = tmp_path / "preptrunc.db"
    _make_db(p, rows=5000)
    size = p.stat().st_size
    with p.open("r+b") as handle:
        handle.truncate(size - 8192)
    with pytest.raises(SQLiteIntegrityError):
        prepare_database_file(p)


def test_prepare_validate_false_skips_checks(tmp_path: Path) -> None:
    p = tmp_path / "garbage2.db"
    p.write_bytes(b"not sqlite at all" * 8)
    prepare_database_file(p, validate=False)  # only cleanup, no raise


# ── on_disk_journal_mode_is_wal ───────────────────────────────────────


def test_on_disk_wal_true_for_wal_db(tmp_path: Path) -> None:
    p = tmp_path / "wal.db"
    _make_db(p, wal=True)
    assert on_disk_journal_mode_is_wal(p) is True


def test_on_disk_wal_false_for_rollback_db(tmp_path: Path) -> None:
    p = tmp_path / "delete.db"
    _make_db(p, wal=False)
    assert on_disk_journal_mode_is_wal(p) is False


def test_on_disk_wal_false_for_missing(tmp_path: Path) -> None:
    assert on_disk_journal_mode_is_wal(tmp_path / "ghost.db") is False


def test_on_disk_wal_false_for_non_sqlite(tmp_path: Path) -> None:
    p = tmp_path / "x.bin"
    p.write_bytes(b"z" * 64)
    assert on_disk_journal_mode_is_wal(p) is False


# ── quick_check ───────────────────────────────────────────────────────


def test_quick_check_ok_helper() -> None:
    assert _is_quick_check_ok([("ok",)]) is True
    assert _is_quick_check_ok([("*** in database main ***",)]) is False
    assert _is_quick_check_ok([]) is False


def test_quick_check_sync_healthy(tmp_path: Path) -> None:
    p = tmp_path / "qc.db"
    _make_db(p)
    conn = sqlite3.connect(str(p))
    quick_check_sync(conn)  # no raise
    conn.close()


def test_quick_check_sync_raises_on_corruption() -> None:
    class _Cur:
        def fetchall(self):
            return [("*** corrupt page 7 ***",)]

    class _Conn:
        def execute(self, _sql):
            return _Cur()

    with pytest.raises(SQLiteIntegrityError, match="quick_check"):
        quick_check_sync(_Conn())  # type: ignore[arg-type]


# ── checkpoint helpers ────────────────────────────────────────────────


def test_checkpoint_truncate_sync_best_effort(tmp_path: Path) -> None:
    p = tmp_path / "ckpt.db"
    _make_db(p)
    conn = sqlite3.connect(str(p))
    checkpoint_truncate_sync(conn)  # no raise
    conn.close()


def test_checkpoint_truncate_sync_swallows_errors() -> None:
    class _Conn:
        def execute(self, _sql):
            raise sqlite3.OperationalError("no wal here")

    checkpoint_truncate_sync(_Conn())  # type: ignore[arg-type]  # best effort, no raise


async def test_checkpoint_truncate_async_best_effort(tmp_path: Path) -> None:
    import aiosqlite

    p = tmp_path / "ckpta.db"
    _make_db(p)
    async with aiosqlite.connect(str(p)) as db:
        await checkpoint_truncate_async(db)  # no raise


async def test_checkpoint_truncate_async_swallows_errors() -> None:
    class _Conn:
        async def execute(self, _sql):
            raise sqlite3.OperationalError("boom")

    await checkpoint_truncate_async(_Conn())  # type: ignore[arg-type]
