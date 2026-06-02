"""Unit tests for connection hardening, the EIO-safe WAL fallback, and connectors."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from myrm_agent_harness.utils.db.sqlite import (
    CACHE,
    DEFAULT,
    DURABLE,
    READONLY,
    SENSITIVE,
    SQLiteProfile,
    connect_async,
    harden_connection_async,
    harden_connection_sync,
    should_fallback_to_delete,
)


def _pragma(conn: sqlite3.Connection, name: str) -> object:
    return conn.execute(f"PRAGMA {name}").fetchone()[0]


# ── harden_connection_sync: profiles ─────────────────────────────────


def test_default_profile_applies_wal_and_guards(tmp_path: Path) -> None:
    p = tmp_path / "d.db"
    conn = sqlite3.connect(str(p))
    mode = harden_connection_sync(conn, DEFAULT, db_path=p)
    assert mode == "WAL"
    assert str(_pragma(conn, "journal_mode")).lower() == "wal"
    assert _pragma(conn, "cell_size_check") == 1
    assert _pragma(conn, "foreign_keys") == 1
    assert _pragma(conn, "busy_timeout") == 5000
    conn.close()


def test_sensitive_profile_enables_secure_delete(tmp_path: Path) -> None:
    conn = sqlite3.connect(str(tmp_path / "s.db"))
    harden_connection_sync(conn, SENSITIVE, db_path=tmp_path / "s.db")
    assert _pragma(conn, "secure_delete") == 1
    conn.close()


def test_cache_profile_disables_secure_delete(tmp_path: Path) -> None:
    conn = sqlite3.connect(str(tmp_path / "c.db"))
    harden_connection_sync(conn, CACHE, db_path=tmp_path / "c.db")
    assert _pragma(conn, "secure_delete") == 0
    assert str(_pragma(conn, "journal_mode")).lower() == "wal"
    conn.close()


def test_durable_profile_sets_cache_and_mmap(tmp_path: Path) -> None:
    conn = sqlite3.connect(str(tmp_path / "dur.db"))
    harden_connection_sync(conn, DURABLE, db_path=tmp_path / "dur.db")
    assert _pragma(conn, "cache_size") == -64000
    assert _pragma(conn, "mmap_size") == 268_435_456
    conn.close()


def test_readonly_profile_sets_query_only_and_skips_journal(tmp_path: Path) -> None:
    # Seed a db first, then open read-only.
    seed = sqlite3.connect(str(tmp_path / "ro.db"))
    harden_connection_sync(seed, DEFAULT, db_path=tmp_path / "ro.db")
    seed.execute("CREATE TABLE t(x)")
    seed.commit()
    seed.close()

    conn = sqlite3.connect(str(tmp_path / "ro.db"))
    mode = harden_connection_sync(conn, READONLY, db_path=tmp_path / "ro.db")
    assert mode == "READONLY"
    assert _pragma(conn, "query_only") == 1
    conn.close()


def test_use_wal_false_yields_delete_journal(tmp_path: Path) -> None:
    conn = sqlite3.connect(str(tmp_path / "del.db"))
    profile = SQLiteProfile(use_wal=False)
    mode = harden_connection_sync(conn, profile, db_path=tmp_path / "del.db")
    assert mode == "DELETE"
    assert str(_pragma(conn, "journal_mode")).lower() == "delete"
    # rollback-journal mode is forced to FULL synchronous for safety
    assert _pragma(conn, "synchronous") == 2  # FULL
    conn.close()


def test_page_size_applied_on_empty_db(tmp_path: Path) -> None:
    conn = sqlite3.connect(str(tmp_path / "ps.db"))
    profile = SQLiteProfile(page_size_bytes=8192)
    harden_connection_sync(conn, profile, db_path=tmp_path / "ps.db")
    assert _pragma(conn, "page_size") == 8192
    conn.close()


# ── should_fallback_to_delete: the EIO correctness contract ──────────


@pytest.mark.parametrize(
    "message",
    [
        "locking protocol",
        "not authorized",
        "operation not supported",
        "this is not supported",
        "invalid argument",
    ],
)
def test_definitive_unsupported_errors_downgrade(message: str) -> None:
    assert should_fallback_to_delete(sqlite3.OperationalError(message), None) is True


@pytest.mark.parametrize(
    "message",
    [
        "disk I/O error",
        "database disk image is malformed",
        "attempt to write a readonly database",
        "database is locked",
    ],
)
def test_transient_errors_never_downgrade(message: str) -> None:
    assert should_fallback_to_delete(sqlite3.OperationalError(message), None) is False


def test_on_disk_wal_blocks_downgrade(tmp_path: Path) -> None:
    p = tmp_path / "wal.db"
    conn = sqlite3.connect(str(p))
    harden_connection_sync(conn, DEFAULT, db_path=p)
    conn.execute("CREATE TABLE t(x)")
    conn.commit()
    conn.close()
    # Even a definitive token must not downgrade a provably-WAL database.
    assert should_fallback_to_delete(
        sqlite3.OperationalError("operation not supported"), p
    ) is False


# ── WAL fallback branch coverage with a duck-typed connection ────────


class _Cur:
    def __init__(self, row: object = None) -> None:
        self._row = row

    def fetchone(self) -> object:
        return self._row


class _FailWalSync:
    """Sync connection that raises on the WAL pragma, recording all other PRAGMAs."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.statements: list[str] = []

    def execute(self, sql: str) -> _Cur:
        if sql == "PRAGMA journal_mode=WAL":
            raise self._exc
        self.statements.append(sql)
        return _Cur(None)


def test_definitive_error_falls_back_to_delete_sync() -> None:
    conn = _FailWalSync(sqlite3.OperationalError("operation not supported"))
    mode = harden_connection_sync(conn, DEFAULT, db_path=None)  # type: ignore[arg-type]
    assert mode == "DELETE"
    assert "PRAGMA journal_mode=DELETE" in conn.statements
    assert "PRAGMA synchronous=FULL" in conn.statements


def test_transient_error_reraises_sync() -> None:
    conn = _FailWalSync(sqlite3.OperationalError("disk I/O error"))
    with pytest.raises(sqlite3.OperationalError):
        harden_connection_sync(conn, DEFAULT, db_path=None)  # type: ignore[arg-type]


def test_memory_journal_mode_uses_full_synchronous() -> None:
    # An in-memory db reports journal_mode "memory"; treat as non-WAL → FULL sync.
    class _MemConn:
        def __init__(self) -> None:
            self.statements: list[str] = []

        def execute(self, sql: str) -> _Cur:
            if sql == "PRAGMA journal_mode=WAL":
                return _Cur(("memory",))
            self.statements.append(sql)
            return _Cur(None)

    conn = _MemConn()
    mode = harden_connection_sync(conn, DEFAULT, db_path=None)  # type: ignore[arg-type]
    assert mode == "MEMORY"
    assert "PRAGMA synchronous=FULL" in conn.statements


# ── async hardening + context managers ───────────────────────────────


async def test_harden_async_applies_wal(tmp_path: Path) -> None:
    import aiosqlite

    p = tmp_path / "a.db"
    async with aiosqlite.connect(str(p)) as db:
        mode = await harden_connection_async(db, DEFAULT, db_path=p)
        assert mode == "WAL"
        cur = await db.execute("PRAGMA journal_mode")
        row = await cur.fetchone()
        assert str(row[0]).lower() == "wal"


async def test_connect_async_context_manager(tmp_path: Path) -> None:
    p = tmp_path / "ca.db"
    async with connect_async(p, DURABLE) as db:
        await db.execute("CREATE TABLE t(x)")
        await db.commit()
        cur = await db.execute("PRAGMA journal_mode")
        row = await cur.fetchone()
        assert str(row[0]).lower() == "wal"
    # connection is closed on exit; a fresh open still sees the table
    async with connect_async(p) as db:
        cur = await db.execute("SELECT count(*) FROM t")
        assert (await cur.fetchone())[0] == 0


async def test_definitive_error_falls_back_to_delete_async() -> None:
    class _AsyncCur:
        def __init__(self, row: object = None) -> None:
            self._row = row

        async def fetchone(self) -> object:
            return self._row

    class _FailWalAsync:
        def __init__(self, exc: Exception) -> None:
            self._exc = exc
            self.statements: list[str] = []

        async def execute(self, sql: str) -> _AsyncCur:
            if sql == "PRAGMA journal_mode=WAL":
                raise self._exc
            self.statements.append(sql)
            return _AsyncCur(None)

    conn = _FailWalAsync(sqlite3.OperationalError("not authorized"))
    mode = await harden_connection_async(conn, DEFAULT, db_path=None)  # type: ignore[arg-type]
    assert mode == "DELETE"
    assert "PRAGMA journal_mode=DELETE" in conn.statements


def test_readonly_profile_applies_optional_pragmas(tmp_path: Path) -> None:
    seed = sqlite3.connect(str(tmp_path / "rox.db"))
    harden_connection_sync(seed, DEFAULT, db_path=tmp_path / "rox.db")
    seed.execute("CREATE TABLE t(x)")
    seed.commit()
    seed.close()

    profile = SQLiteProfile(
        read_only=True,
        use_wal=False,
        cache_size=-2000,
        temp_store_memory=True,
        mmap_size_bytes=1_048_576,
    )
    conn = sqlite3.connect(str(tmp_path / "rox.db"))
    assert harden_connection_sync(conn, profile, db_path=tmp_path / "rox.db") == "READONLY"
    assert _pragma(conn, "cache_size") == -2000
    assert _pragma(conn, "mmap_size") == 1_048_576
    assert _pragma(conn, "query_only") == 1
    conn.close()


async def test_harden_async_readonly(tmp_path: Path) -> None:
    import aiosqlite

    p = tmp_path / "aro.db"
    seed = sqlite3.connect(str(p))
    harden_connection_sync(seed, DEFAULT, db_path=p)
    seed.execute("CREATE TABLE t(x)")
    seed.commit()
    seed.close()

    async with aiosqlite.connect(str(p)) as db:
        mode = await harden_connection_async(db, READONLY, db_path=p)
        assert mode == "READONLY"
        cur = await db.execute("PRAGMA query_only")
        assert (await cur.fetchone())[0] == 1


async def test_harden_async_use_wal_false_yields_delete(tmp_path: Path) -> None:
    import aiosqlite

    p = tmp_path / "ad.db"
    async with aiosqlite.connect(str(p)) as db:
        mode = await harden_connection_async(db, SQLiteProfile(use_wal=False), db_path=p)
        assert mode == "DELETE"
        cur = await db.execute("PRAGMA journal_mode")
        assert str((await cur.fetchone())[0]).lower() == "delete"


async def test_harden_async_page_size_applied(tmp_path: Path) -> None:
    import aiosqlite

    p = tmp_path / "aps.db"
    async with aiosqlite.connect(str(p)) as db:
        await harden_connection_async(db, SQLiteProfile(page_size_bytes=8192), db_path=p)
        cur = await db.execute("PRAGMA page_size")
        assert (await cur.fetchone())[0] == 8192
