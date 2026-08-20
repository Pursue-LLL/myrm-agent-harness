"""Unit tests for StorageCapabilities and Fail-Closed Schema Gate."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import aiosqlite
import pytest

from myrm_agent_harness.utils.db.sqlite import (
    DEFAULT,
    SchemaGateError,
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


def test_capabilities_bounds_validation() -> None:
    with pytest.raises(ValueError, match="schema_version must be >= 1"):
        StorageCapabilities(schema_version=0)

    with pytest.raises(ValueError, match="min_compatible_version must be >= 1"):
        StorageCapabilities(schema_version=2, min_compatible_version=0)

    with pytest.raises(ValueError, match="cannot exceed schema_version"):
        StorageCapabilities(schema_version=1, min_compatible_version=2)

    caps = StorageCapabilities(schema_version=5, min_compatible_version=2)
    assert caps.schema_version == 5
    assert caps.min_compatible_version == 2
    assert caps.supports_atomic_batch is True
    assert caps.supports_concurrent_readers is True


def test_schema_gate_sync_auto_initialize_empty_db(tmp_path: Path) -> None:
    db_file = tmp_path / "new.db"
    conn = sqlite3.connect(str(db_file))
    caps = StorageCapabilities(schema_version=3)

    version = validate_schema_gate_sync(conn, caps, db_path=db_file)
    assert version == 3

    # Assert PRAGMA user_version persisted
    row = conn.execute("PRAGMA user_version").fetchone()
    assert row[0] == 3
    conn.close()


def test_schema_gate_sync_fail_closed_on_too_new_version(tmp_path: Path) -> None:
    db_file = tmp_path / "future.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE mock_table (id TEXT PRIMARY KEY)")
    conn.execute("PRAGMA user_version = 5")
    conn.commit()

    older_caps = StorageCapabilities(schema_version=3, min_compatible_version=1)

    with pytest.raises(SchemaVersionTooNewError) as exc_info:
        validate_schema_gate_sync(conn, older_caps, db_path=db_file)

    assert exc_info.value.detected_version == 5
    assert exc_info.value.expected_version == 3
    assert "exceeds maximum supported version" in str(exc_info.value)
    conn.close()


def test_schema_gate_sync_fail_closed_on_too_old_version(tmp_path: Path) -> None:
    db_file = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE mock_table (id TEXT PRIMARY KEY)")
    conn.execute("PRAGMA user_version = 1")
    conn.commit()

    newer_caps = StorageCapabilities(schema_version=5, min_compatible_version=3)

    with pytest.raises(SchemaVersionTooOldError) as exc_info:
        validate_schema_gate_sync(conn, newer_caps, db_path=db_file)

    assert exc_info.value.detected_version == 1
    assert exc_info.value.expected_version == 3
    assert "older than minimum supported version" in str(exc_info.value)
    conn.close()


def test_schema_gate_sync_shape_mismatch_check(tmp_path: Path) -> None:
    db_file = tmp_path / "partial.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE table_a (id TEXT PRIMARY KEY)")
    conn.execute("PRAGMA user_version = 2")
    conn.commit()

    caps = StorageCapabilities(
        schema_version=2,
        min_compatible_version=1,
        required_tables=("table_a", "table_b"),
    )

    with pytest.raises(SchemaShapeMismatchError) as exc_info:
        validate_schema_gate_sync(conn, caps, db_path=db_file)

    assert "table_b" in str(exc_info.value)
    conn.close()


def test_harden_connection_sync_with_capabilities(tmp_path: Path) -> None:
    db_file = tmp_path / "hardened.db"
    conn = sqlite3.connect(str(db_file))
    caps = StorageCapabilities(schema_version=4)

    mode = harden_connection_sync(conn, DEFAULT, db_path=db_file, capabilities=caps)
    assert mode == "WAL"

    row = conn.execute("PRAGMA user_version").fetchone()
    assert row[0] == 4
    conn.close()


@pytest.mark.asyncio
async def test_schema_gate_async_flow(tmp_path: Path) -> None:
    db_file = tmp_path / "async.db"
    async with aiosqlite.connect(str(db_file)) as conn:
        caps = StorageCapabilities(schema_version=2)
        version = await validate_schema_gate_async(conn, caps, db_path=db_file)
        assert version == 2

        # Verify through hardening
        await harden_connection_async(conn, DEFAULT, db_path=db_file, capabilities=caps)

    # Test connect_async context manager with capabilities
    async with connect_async(db_file, DEFAULT, capabilities=caps) as conn:
        cursor = await conn.execute("PRAGMA user_version")
        row = await cursor.fetchone()
        assert row[0] == 2
