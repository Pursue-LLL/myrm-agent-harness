"""Live integration tests for SQLite Schema Gate and capability contracts.

Validates:
1. Fresh database bootstrap + migration engine PRAGMA user_version synchronisation.
2. Server init_database startup fail-closed gate on version too new / too old / shape mismatch.
3. Full lifecycle live SQLite connection hardening with SchemaGate (sync + async).
4. Critical paths remain completely unmocked.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import aiosqlite
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from myrm_agent_harness.utils.db.migration_engine import (
    MigrationStatement,
    StatefulMigrationEngine,
)
from myrm_agent_harness.utils.db.sqlite import (
    DEFAULT,
    SchemaShapeMismatchError,
    SchemaVersionTooNewError,
    SchemaVersionTooOldError,
    StorageCapabilities,
    connect_async,
    harden_connection_async,
    harden_connection_sync,
    validate_schema_gate_async,
    validate_schema_gate_sync,
)


def test_sqlite_schema_gate_sync_live_lifecycle(tmp_path: Path) -> None:
    """Synchronous real SQLite connection lifecycle validation against SchemaGate."""
    db_file = tmp_path / "live_sync_gate.db"
    caps = StorageCapabilities(
        schema_version=5,
        min_compatible_version=2,
        supports_atomic_batch=True,
        supports_concurrent_readers=True,
        is_persistent=True,
        required_tables=("users", "sessions"),
    )

    # 1. Fresh empty database with auto-initialize sets user_version to 5
    with sqlite3.connect(str(db_file)) as conn:
        journal_mode = harden_connection_sync(
            conn, DEFAULT, db_path=db_file, capabilities=caps
        )
        assert journal_mode == "WAL"

        # user_version was auto-initialized to 5
        cursor = conn.execute("PRAGMA user_version")
        assert cursor.fetchone()[0] == 5

    # 2. Add required tables to satisfy shape validation
    with sqlite3.connect(str(db_file)) as conn:
        conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY, name TEXT)")
        conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, user_id TEXT)")
        conn.commit()

        # Should pass validation cleanly
        validated_ver = validate_schema_gate_sync(conn, caps, db_path=db_file)
        assert validated_ver == 5

    # 3. Simulate high version database (e.g. version 10 created by future binary)
    with sqlite3.connect(str(db_file)) as conn:
        conn.execute("PRAGMA user_version = 10")
        conn.commit()

    # Fail-Closed: Older build must abort startup with SchemaVersionTooNewError
    with sqlite3.connect(str(db_file)) as conn:
        with pytest.raises(SchemaVersionTooNewError) as exc_info:
            harden_connection_sync(conn, DEFAULT, db_path=db_file, capabilities=caps)
        assert exc_info.value.detected_version == 10
        assert exc_info.value.expected_version == 5
        assert "Database schema version 10 exceeds maximum supported version 5" in str(
            exc_info.value
        )

    # 4. Simulate low version database (e.g. version 1 which is < min_compatible_version 2)
    with sqlite3.connect(str(db_file)) as conn:
        conn.execute("PRAGMA user_version = 1")
        conn.commit()

    # Fail-Closed: Older version below min must abort with SchemaVersionTooOldError
    with sqlite3.connect(str(db_file)) as conn:
        with pytest.raises(SchemaVersionTooOldError) as exc_info:
            harden_connection_sync(conn, DEFAULT, db_path=db_file, capabilities=caps)
        assert exc_info.value.detected_version == 1
        assert exc_info.value.expected_version == 2
        assert "is older than minimum supported version 2" in str(exc_info.value)

    # 5. Simulate shape mismatch: drop required table
    with sqlite3.connect(str(db_file)) as conn:
        conn.execute("PRAGMA user_version = 3")
        conn.execute("DROP TABLE sessions")
        conn.commit()

    with sqlite3.connect(str(db_file)) as conn:
        with pytest.raises(SchemaShapeMismatchError) as exc_info:
            validate_schema_gate_sync(conn, caps, db_path=db_file)
        assert "missing required tables [sessions]" in str(exc_info.value)


@pytest.mark.asyncio
async def test_sqlite_schema_gate_async_live_lifecycle(tmp_path: Path) -> None:
    """Asynchronous real aiosqlite connection lifecycle validation against SchemaGate."""
    db_file = tmp_path / "live_async_gate.db"
    caps = StorageCapabilities(
        schema_version=8,
        min_compatible_version=3,
        supports_atomic_batch=True,
        supports_concurrent_readers=True,
        is_persistent=True,
    )

    # 1. Connect via connect_async helper and verify auto-init on fresh DB
    async with connect_async(db_file, DEFAULT, capabilities=caps) as conn:
        cursor = await conn.execute("PRAGMA user_version")
        row = await cursor.fetchone()
        assert row is not None and row[0] == 8

    # 2. Validate async harden_connection_async on compatible DB
    async with aiosqlite.connect(str(db_file)) as conn:
        journal_mode = await harden_connection_async(
            conn, DEFAULT, db_path=db_file, capabilities=caps
        )
        assert journal_mode == "WAL"

    # 3. Future database version fail-closed
    async with aiosqlite.connect(str(db_file)) as conn:
        await conn.execute("PRAGMA user_version = 99")
        await conn.commit()

    async with aiosqlite.connect(str(db_file)) as conn:
        with pytest.raises(SchemaVersionTooNewError) as exc_info:
            await harden_connection_async(
                conn, DEFAULT, db_path=db_file, capabilities=caps
            )
        assert exc_info.value.detected_version == 99
        assert exc_info.value.expected_version == 8


@pytest.mark.asyncio
async def test_migration_engine_live_full_stack_integration(tmp_path: Path) -> None:
    """Full-stack migration engine run atomically synchronizes user_version."""
    db_file = tmp_path / "migration_live.db"
    async_engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")

    try:
        # Run 3 stateful migrations on real SQLite
        migrations = [
            MigrationStatement(
                version=0,
                sql="CREATE TABLE orders (id VARCHAR(32) PRIMARY KEY, total REAL)",
            ),
            MigrationStatement(
                version=1, sql="ALTER TABLE orders ADD COLUMN status VARCHAR(20)"
            ),
            MigrationStatement(
                version=2,
                sql="CREATE INDEX idx_orders_status ON orders(status)",
            ),
        ]
        migration_engine = StatefulMigrationEngine(
            engine=async_engine,
            table_name="_schema_migrations",
        )
        report = await migration_engine.run_migrations(migrations)
        assert report.applied_count == 3
        assert report.failed_count == 0

        # Verify PRAGMA user_version is atomically set to max migration version = 2
        async with async_engine.connect() as conn:
            raw_conn = await conn.get_raw_connection()
            cursor = await raw_conn.driver_connection.execute("PRAGMA user_version")
            row = await cursor.fetchone()
            assert row is not None and row[0] == 2

        # Schema Gate validation at version 2
        caps = StorageCapabilities(
            schema_version=2,
            min_compatible_version=1,
            required_tables=("orders",),
        )
        async with async_engine.connect() as conn:
            raw_conn = await conn.get_raw_connection()
            ver = await validate_schema_gate_async(
                raw_conn.driver_connection, caps, db_path=db_file
            )
            assert ver == 2
    finally:
        await async_engine.dispose()


@pytest.mark.asyncio
async def test_migration_engine_failure_retains_prior_user_version(
    tmp_path: Path,
) -> None:
    """When a migration in the chain fails, user_version is NOT updated to corrupted state."""
    db_file = tmp_path / "failed_migration.db"
    async_engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")

    try:
        # Step 1: Successful initial migration v0
        m1 = [
            MigrationStatement(
                version=0, sql="CREATE TABLE valid_tbl (id INTEGER PRIMARY KEY)"
            )
        ]
        engine1 = StatefulMigrationEngine(engine=async_engine)
        rep1 = await engine1.run_migrations(m1)
        assert rep1.applied_count == 1
        assert rep1.failed_count == 0

        # Check user_version == 0
        async with async_engine.connect() as conn:
            raw_conn = await conn.get_raw_connection()
            cursor = await raw_conn.driver_connection.execute("PRAGMA user_version")
            row = await cursor.fetchone()
            assert row is not None and row[0] == 0

        # Step 2: Second migration contains syntax error at v1
        m2 = [
            MigrationStatement(
                version=0, sql="CREATE TABLE valid_tbl (id INTEGER PRIMARY KEY)"
            ),
            MigrationStatement(version=1, sql="INVALID SYNTAX SQL STATEMENT ERROR"),
        ]
        engine2 = StatefulMigrationEngine(engine=async_engine)
        rep2 = await engine2.run_migrations(m2)
        assert rep2.failed_count == 1
        assert rep2.failed_version == 1

        # Check user_version is NOT advanced to 1, still at 0
        async with async_engine.connect() as conn:
            raw_conn = await conn.get_raw_connection()
            cursor = await raw_conn.driver_connection.execute("PRAGMA user_version")
            row = await cursor.fetchone()
            assert row is not None and row[0] == 0
    finally:
        await async_engine.dispose()
