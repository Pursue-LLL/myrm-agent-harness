"""SQLiteRelationalStore corruption handling — connect-time, integrity check and query-error paths."""

from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

from myrm_agent_harness.toolkits.memory.relational import SQLiteRelationalStore
from myrm_agent_harness.toolkits.memory.relational.exceptions import (
    CorruptedMemoryIndexError,
    RelationalConnectionError,
    RelationalNotFoundError,
    RelationalQueryError,
)

_DEFAULT_REPAIR = "Restore from sqlite_backup snapshot or reset memory store."


class _FixedRowsCursor:
    """Async-context cursor returning a fixed quick_check result."""

    def __init__(self, rows: list[tuple[str]]) -> None:
        self._rows = rows

    async def __aenter__(self) -> _FixedRowsCursor:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def fetchall(self) -> list[tuple[str]]:
        return self._rows


def _intercept_quick_check(conn: aiosqlite.Connection, replacement: object) -> None:
    """Route PRAGMA quick_check through ``replacement`` while other statements run normally."""
    original = conn.execute

    def _execute(sql: str, *args: object, **kwargs: object) -> object:
        if "PRAGMA quick_check" in str(sql):
            return replacement() if callable(replacement) else replacement
        return original(sql, *args, **kwargs)

    conn.execute = _execute  # type: ignore[method-assign]


def _raise(exc: Exception) -> object:
    def _thrower() -> object:
        raise exc

    return _thrower


@pytest.fixture
def store(tmp_path: Path) -> SQLiteRelationalStore:
    return SQLiteRelationalStore(str(tmp_path / "corruption.db"))


class _ConnectionTracker:
    """Records the aiosqlite connection opened by the store so tests can assert it is released."""

    def __init__(self) -> None:
        self.connection: aiosqlite.Connection | None = None


def _track_connection(store: SQLiteRelationalStore, monkeypatch: pytest.MonkeyPatch) -> _ConnectionTracker:
    tracker = _ConnectionTracker()
    original = store._init_connection_settings

    async def _record() -> None:
        tracker.connection = store._connection
        await original()

    monkeypatch.setattr(store, "_init_connection_settings", _record)
    return tracker


async def _assert_closed(conn: aiosqlite.Connection) -> None:
    with pytest.raises(ValueError, match="no active connection"):
        await conn.execute("SELECT 1")


async def _assert_closed(conn: aiosqlite.Connection) -> None:
    with pytest.raises(ValueError, match="no active connection"):
        await conn.execute("SELECT 1")


# ── connect-time failures ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_initial_quick_check_failure_raises_and_releases_connection(
    store: SQLiteRelationalStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    tracker = _track_connection(store, monkeypatch)
    original_init_tables = store._init_tables

    async def _init_then_corrupt() -> None:
        await original_init_tables()
        assert store._connection is not None
        _intercept_quick_check(store._connection, _FixedRowsCursor([("tree cell 3 out of order",)]))

    monkeypatch.setattr(store, "_init_tables", _init_then_corrupt)

    with pytest.raises(CorruptedMemoryIndexError, match="failed initial quick_check") as exc_info:
        await store._get_connection()

    assert exc_info.value.index_type == "sqlite_relational"
    assert exc_info.value.db_path == str(store._db_path)
    assert exc_info.value.repair_suggestion == _DEFAULT_REPAIR
    assert store._connection is None
    assert tracker.connection is not None
    await _assert_closed(tracker.connection)


@pytest.mark.asyncio
async def test_corruption_during_connect_is_classified_and_releases_connection(
    store: SQLiteRelationalStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    tracker = _track_connection(store, monkeypatch)

    async def _boom() -> None:
        raise aiosqlite.DatabaseError("file is not a database")

    monkeypatch.setattr(store, "_init_tables", _boom)

    with pytest.raises(CorruptedMemoryIndexError, match="Corrupted SQLite store") as exc_info:
        await store._get_connection()

    assert exc_info.value.repair_suggestion == _DEFAULT_REPAIR
    assert isinstance(exc_info.value.__cause__, aiosqlite.DatabaseError)
    assert store._connection is None
    assert tracker.connection is not None
    await _assert_closed(tracker.connection)


@pytest.mark.asyncio
async def test_unrelated_connect_failure_is_connection_error_and_releases_connection(
    store: SQLiteRelationalStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    tracker = _track_connection(store, monkeypatch)

    async def _boom() -> None:
        raise RuntimeError("schema migration exploded")

    monkeypatch.setattr(store, "_init_tables", _boom)

    with pytest.raises(RelationalConnectionError, match="Failed to connect: schema migration exploded"):
        await store._get_connection()

    assert store._connection is None
    assert tracker.connection is not None
    await _assert_closed(tracker.connection)


@pytest.mark.asyncio
async def test_connect_can_be_retried_after_failure(
    store: SQLiteRelationalStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}
    original = store._init_tables

    async def _flaky() -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        await original()

    monkeypatch.setattr(store, "_init_tables", _flaky)

    with pytest.raises(RelationalConnectionError):
        await store._get_connection()
    await store.set_profile("k", "v")
    assert await store.get_profile("k") == "v"
    await store.close()


@pytest.mark.asyncio
async def test_closed_store_rejects_connection(store: SQLiteRelationalStore) -> None:
    await store.close()
    with pytest.raises(RelationalConnectionError, match="Store has been closed"):
        await store._get_connection()


# ── assert_store_integrity ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_assert_store_integrity_passes_on_healthy_store(store: SQLiteRelationalStore) -> None:
    await store.assert_store_integrity()
    await store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rows",
    [[], [("ok",), ("extra",)], [("*** in database main ***",)]],
    ids=["empty", "multiple-rows", "non-ok"],
)
async def test_assert_store_integrity_rejects_unhealthy_rows(
    store: SQLiteRelationalStore, rows: list[tuple[str]]
) -> None:
    conn = await store._get_connection()
    _intercept_quick_check(conn, _FixedRowsCursor(rows))

    with pytest.raises(CorruptedMemoryIndexError, match="failed quick_check") as exc_info:
        await store.assert_store_integrity()

    assert exc_info.value.repair_suggestion == _DEFAULT_REPAIR
    await store.close()


@pytest.mark.asyncio
async def test_assert_store_integrity_accepts_case_insensitive_ok(store: SQLiteRelationalStore) -> None:
    conn = await store._get_connection()
    _intercept_quick_check(conn, _FixedRowsCursor([("OK",)]))
    await store.assert_store_integrity()
    await store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    ["database disk image is malformed", "file is not a database", "disk I/O error", "database is corrupt"],
)
async def test_assert_store_integrity_classifies_corruption_query_errors(
    store: SQLiteRelationalStore, message: str
) -> None:
    conn = await store._get_connection()
    cause = aiosqlite.DatabaseError(message)
    _intercept_quick_check(conn, _raise(cause))

    with pytest.raises(CorruptedMemoryIndexError, match="integrity check query error") as exc_info:
        await store.assert_store_integrity()

    assert exc_info.value.repair_suggestion == "Check file permissions or restore database from backup."
    assert exc_info.value.__cause__ is cause
    await store.close()


@pytest.mark.asyncio
async def test_assert_store_integrity_wraps_unrelated_errors(store: SQLiteRelationalStore) -> None:
    conn = await store._get_connection()
    _intercept_quick_check(conn, _raise(RuntimeError("cursor exploded")))

    with pytest.raises(RelationalQueryError, match="integrity check query failed: cursor exploded"):
        await store.assert_store_integrity()
    await store.close()


# ── _handle_query_error ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "error",
    [
        CorruptedMemoryIndexError("already classified"),
        RelationalNotFoundError("missing"),
        RelationalQueryError("already wrapped"),
    ],
    ids=lambda e: type(e).__name__,
)
def test_handle_query_error_reraises_store_errors_unchanged(store: SQLiteRelationalStore, error: Exception) -> None:
    with pytest.raises(type(error)) as exc_info:
        store._handle_query_error("op", error)
    assert exc_info.value is error


@pytest.mark.asyncio
async def test_handle_query_error_corruption_drops_connection(store: SQLiteRelationalStore) -> None:
    conn = await store._get_connection()
    cause = aiosqlite.DatabaseError("database disk image is malformed")

    with pytest.raises(CorruptedMemoryIndexError, match="corrupted during set_profile") as exc_info:
        store._handle_query_error("set_profile", cause)

    assert exc_info.value.repair_suggestion == _DEFAULT_REPAIR
    assert exc_info.value.__cause__ is cause
    assert store._connection is None
    await conn.close()


def test_handle_query_error_wraps_other_errors_and_keeps_connection(store: SQLiteRelationalStore) -> None:
    with pytest.raises(RelationalQueryError, match="list_rules failed: boom"):
        store._handle_query_error("list_rules", RuntimeError("boom"))


# ── per-operation error classification ───────────────────────────────

_STORE_OPERATIONS = {
    "set_profile": lambda s: s.set_profile("k", "v"),
    "delete_profile": lambda s: s.delete_profile("k"),
    "get_rule": lambda s: s.get_rule("missing"),
    "count_rules_inactive": lambda s: s.count_rules(active_only=False),
    "delete_rule": lambda s: s.delete_rule("missing"),
    "delete_all": lambda s: s.delete_all(),
    "get_pending": lambda s: s.get_pending("missing"),
    "pending_exists": lambda s: s.pending_exists("semantic", "x"),
    "mark_pending": lambda s: s.mark_pending("missing", "approved"),
    "delete_pending_by_source_chat_id": lambda s: s.delete_pending_by_source_chat_id("chat"),
    "count_pending_by_source_chat_id": lambda s: s.count_pending_by_source_chat_id("chat"),
    "delete_exact_fact": lambda s: s.delete_exact_fact("missing"),
}


def _fail_non_pragma_statements(conn: aiosqlite.Connection, error: Exception) -> None:
    original = conn.execute

    def _execute(sql: str, *args: object, **kwargs: object) -> object:
        if str(sql).lstrip().upper().startswith("PRAGMA"):
            return original(sql, *args, **kwargs)
        raise error

    conn.execute = _execute  # type: ignore[method-assign]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", sorted(_STORE_OPERATIONS))
async def test_operation_failure_is_wrapped_with_operation_name(store: SQLiteRelationalStore, operation: str) -> None:
    conn = await store._get_connection()
    _fail_non_pragma_statements(conn, aiosqlite.OperationalError("disk is busy"))

    with pytest.raises(RelationalQueryError, match="disk is busy"):
        await _STORE_OPERATIONS[operation](store)

    assert store._connection is conn
    await conn.close()


# Read operations that surface every failure as RelationalQueryError without corruption classification.
_UNCLASSIFIED_READS = frozenset({"count_rules_inactive", "count_pending_by_source_chat_id"})


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", sorted(_STORE_OPERATIONS))
async def test_operation_corruption_handling(store: SQLiteRelationalStore, operation: str) -> None:
    conn = await store._get_connection()
    _fail_non_pragma_statements(conn, aiosqlite.DatabaseError("database disk image is malformed"))

    if operation in _UNCLASSIFIED_READS:
        with pytest.raises(RelationalQueryError, match="malformed"):
            await _STORE_OPERATIONS[operation](store)
        assert store._connection is conn
    else:
        with pytest.raises(CorruptedMemoryIndexError, match="corrupted during"):
            await _STORE_OPERATIONS[operation](store)
        assert store._connection is None
    await conn.close()
