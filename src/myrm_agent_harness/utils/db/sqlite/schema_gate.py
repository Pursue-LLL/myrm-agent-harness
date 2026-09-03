"""SQLite storage capabilities contract and fail-closed schema startup gate.

Provides:
- StorageCapabilities: immutable capability specification for SQLite-backed stores
- SchemaGateError: hierarchy of schema incompatibility errors
- validate_schema_gate_sync / validate_schema_gate_async: pre-flight startup version gate
  that fails closed on version mismatch to prevent silent data corruption.

[INPUT]
- sqlite3.Connection / aiosqlite.Connection
- StorageCapabilities (POS: expected version and capability bounds)
- pathlib.Path (optional POS: database file path for diagnostic reporting)

[OUTPUT]
- StorageCapabilities: frozen dataclass
- SchemaGateError, SchemaVersionTooNewError, SchemaVersionTooOldError, SchemaShapeMismatchError
- validate_schema_gate_sync / validate_schema_gate_async: validation primitives

[POS]
Core component of utils.db.sqlite. Defines the capability contract and gatekeeper
for all SQLite persistence layers across local WebUI, Tauri desktop, and Cloud Sandboxes.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StorageCapabilities:
    """Explicit capability and version contract for a SQLite storage component.

    Attributes:
        schema_version: Current schema version expected/produced by this software build.
        min_compatible_version: Minimum schema version this software build can read/operate on.
        supports_atomic_batch: Whether the store guarantees atomic transactional writes.
        supports_concurrent_readers: Whether WAL snapshot reads are supported without read locks.
        is_persistent: Whether the store writes to disk (True) or volatile memory (False).
        required_tables: Optional tuple of critical table names that must exist if version > 0.
    """

    schema_version: int = 1
    min_compatible_version: int = 1
    supports_atomic_batch: bool = True
    supports_concurrent_readers: bool = True
    is_persistent: bool = True
    required_tables: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version < 1:
            raise ValueError(f"schema_version must be >= 1, got {self.schema_version}")
        if self.min_compatible_version < 1:
            raise ValueError(
                f"min_compatible_version must be >= 1, got {self.min_compatible_version}"
            )
        if self.min_compatible_version > self.schema_version:
            raise ValueError(
                f"min_compatible_version ({self.min_compatible_version}) "
                f"cannot exceed schema_version ({self.schema_version})"
            )


class SchemaGateError(Exception):
    """Base exception for all database schema gate validation failures."""

    def __init__(
        self,
        message: str,
        *,
        db_path: str | Path | None = None,
        detected_version: int | None = None,
        expected_version: int | None = None,
    ) -> None:
        super().__init__(message)
        self.db_path = str(db_path) if db_path is not None else None
        self.detected_version = detected_version
        self.expected_version = expected_version


class SchemaVersionTooNewError(SchemaGateError):
    """Raised when the database on disk was created/migrated by a newer application version.

    Fail-Closed guard: Prevents older application builds from silently reading or writing
    to a newer database schema, avoiding data corruption and lost column attributes.
    """

    def __init__(
        self,
        *,
        detected_version: int,
        supported_max_version: int,
        db_path: str | Path | None = None,
    ) -> None:
        message = (
            f"Database schema version {detected_version} exceeds maximum supported version "
            f"{supported_max_version} (path: {db_path or '<in-memory>'}). "
            "Startup aborted to prevent silent data corruption. "
            "Please upgrade your application or container image to the latest version."
        )
        super().__init__(
            message,
            db_path=db_path,
            detected_version=detected_version,
            expected_version=supported_max_version,
        )


class SchemaVersionTooOldError(SchemaGateError):
    """Raised when the database on disk is older than the minimum compatible version."""

    def __init__(
        self,
        *,
        detected_version: int,
        min_compatible_version: int,
        db_path: str | Path | None = None,
    ) -> None:
        message = (
            f"Database schema version {detected_version} is older than minimum supported version "
            f"{min_compatible_version} (path: {db_path or '<in-memory>'}). "
            "Migration or upgrade is required before this database can be safely opened."
        )
        super().__init__(
            message,
            db_path=db_path,
            detected_version=detected_version,
            expected_version=min_compatible_version,
        )


class SchemaShapeMismatchError(SchemaGateError):
    """Raised when required tables/columns are missing despite a matching version number."""

    def __init__(
        self,
        *,
        missing_tables: Sequence[str],
        db_path: str | Path | None = None,
        detected_version: int | None = None,
    ) -> None:
        missing_str = ", ".join(missing_tables)
        message = (
            f"Database structural shape mismatch: missing required tables [{missing_str}] "
            f"(version: {detected_version}, path: {db_path or '<in-memory>'})."
        )
        super().__init__(
            message,
            db_path=db_path,
            detected_version=detected_version,
        )


def _get_existing_tables_sync(conn: sqlite3.Connection) -> set[str]:
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {str(row[0]) for row in cursor.fetchall()}


async def _get_existing_tables_async(conn: aiosqlite.Connection) -> set[str]:
    cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    rows = await cursor.fetchall()
    return {str(row[0]) for row in rows}


def validate_schema_gate_sync(
    conn: sqlite3.Connection,
    capabilities: StorageCapabilities,
    *,
    db_path: Path | None = None,
    auto_initialize_version: bool = True,
) -> int:
    """Validate that the synchronous SQLite connection satisfies the schema gate.

    Rules:
    1. Reads ``PRAGMA user_version``.
    2. If ``user_version == 0``:
       - If database is empty (no tables) and ``auto_initialize_version`` is True,
         sets ``PRAGMA user_version = capabilities.schema_version`` and returns.
       - If tables exist without user_version, verifies required tables or allows migration.
    3. If ``user_version > capabilities.schema_version``:
       - Raises ``SchemaVersionTooNewError`` (Fail-Closed).
    4. If ``user_version < capabilities.min_compatible_version``:
       - Raises ``SchemaVersionTooOldError`` (Fail-Closed).
    5. If ``capabilities.required_tables`` is provided and ``user_version > 0``:
       - Asserts all required tables exist; raises ``SchemaShapeMismatchError`` if missing.

    Returns:
        The validated active schema version on the connection.
    """
    row = conn.execute("PRAGMA user_version").fetchone()
    current_version = int(row[0]) if row and row[0] is not None else 0

    if current_version == 0:
        existing_tables = _get_existing_tables_sync(conn)
        user_tables = {t for t in existing_tables if not t.startswith("sqlite_")}
        if not user_tables and auto_initialize_version:
            conn.execute(f"PRAGMA user_version = {capabilities.schema_version}")
            return capabilities.schema_version
        if not user_tables:
            return 0

    if current_version > capabilities.schema_version:
        raise SchemaVersionTooNewError(
            detected_version=current_version,
            supported_max_version=capabilities.schema_version,
            db_path=db_path,
        )

    if 0 < current_version < capabilities.min_compatible_version:
        raise SchemaVersionTooOldError(
            detected_version=current_version,
            min_compatible_version=capabilities.min_compatible_version,
            db_path=db_path,
        )

    if capabilities.required_tables and current_version > 0:
        existing_tables = _get_existing_tables_sync(conn)
        missing = [t for t in capabilities.required_tables if t not in existing_tables]
        if missing:
            raise SchemaShapeMismatchError(
                missing_tables=missing,
                db_path=db_path,
                detected_version=current_version,
            )

    return current_version


async def validate_schema_gate_async(
    conn: aiosqlite.Connection,
    capabilities: StorageCapabilities,
    *,
    db_path: Path | None = None,
    auto_initialize_version: bool = True,
) -> int:
    """Validate that the asynchronous aiosqlite connection satisfies the schema gate."""
    cursor = await conn.execute("PRAGMA user_version")
    row = await cursor.fetchone()
    current_version = int(row[0]) if row and row[0] is not None else 0

    if current_version == 0:
        existing_tables = await _get_existing_tables_async(conn)
        user_tables = {t for t in existing_tables if not t.startswith("sqlite_")}
        if not user_tables and auto_initialize_version:
            await conn.execute(f"PRAGMA user_version = {capabilities.schema_version}")
            return capabilities.schema_version
        if not user_tables:
            return 0

    if current_version > capabilities.schema_version:
        raise SchemaVersionTooNewError(
            detected_version=current_version,
            supported_max_version=capabilities.schema_version,
            db_path=db_path,
        )

    if 0 < current_version < capabilities.min_compatible_version:
        raise SchemaVersionTooOldError(
            detected_version=current_version,
            min_compatible_version=capabilities.min_compatible_version,
            db_path=db_path,
        )

    if capabilities.required_tables and current_version > 0:
        existing_tables = await _get_existing_tables_async(conn)
        missing = [t for t in capabilities.required_tables if t not in existing_tables]
        if missing:
            raise SchemaShapeMismatchError(
                missing_tables=missing,
                db_path=db_path,
                detected_version=current_version,
            )

    return current_version
