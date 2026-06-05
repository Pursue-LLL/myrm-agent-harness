"""Unified SQLite connection hardening (sync + async).

Applies a :class:`SQLiteProfile` to a connection: WAL journaling with a
*correct* fallback, crash-safe ``synchronous``, B-tree torn-write detection
(``cell_size_check``), privacy-preserving deletes (``secure_delete``),
referential integrity, and store-specific performance tuning.

Critical correctness property — **never silently downgrade WAL to DELETE on a
transient error**. A downgrade only happens for errors that *definitively* mean
the filesystem cannot host WAL, and never when the on-disk header proves the
database is already a WAL database.

[INPUT]
- sqlite3.Connection / aiosqlite.Connection (POS: open connection to harden)
- SQLiteProfile (POS: PRAGMA specification)
- pathlib.Path (POS: db file, enables the on-disk-header downgrade guard)

[OUTPUT]
- harden_connection_sync / harden_connection_async: apply the profile, return the journal mode

[POS]
Core of the unified SQLite hardening factory. Depends on profile + integrity leaves.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from .integrity import on_disk_journal_mode_is_wal
from .profile import DEFAULT, SQLiteProfile

if TYPE_CHECKING:
    import aiosqlite

logger = logging.getLogger(__name__)

# Errors that *definitively* mean the filesystem cannot host WAL (network/FUSE
# mounts). Transient I/O errors are intentionally absent: a momentary EIO must
# never permanently strip a database of WAL crash-safety.
_DEFINITIVE_WAL_UNSUPPORTED = (
    "locking protocol",
    "not authorized",
    "operation not supported",
    "not supported",
    "invalid argument",
)


def should_fallback_to_delete(exc: sqlite3.Error, db_path: Path | None) -> bool:
    """Decide whether a WAL-set failure warrants a permanent DELETE downgrade.

    Single source of truth shared by the harness factory and the server's
    deployment-aware SQLAlchemy listener: downgrade only on a *definitive*
    filesystem-incompatibility error, and never when the on-disk header proves the
    database is already WAL (i.e. the error is transient).
    """
    if db_path is not None and on_disk_journal_mode_is_wal(db_path):
        return False
    message = str(exc).lower()
    return any(token in message for token in _DEFINITIVE_WAL_UNSUPPORTED)


def _read_only_statements(profile: SQLiteProfile) -> list[str]:
    statements = [f"PRAGMA busy_timeout={profile.busy_timeout_ms}", "PRAGMA query_only=ON"]
    if profile.cache_size is not None:
        statements.append(f"PRAGMA cache_size={profile.cache_size}")
    if profile.temp_store_memory:
        statements.append("PRAGMA temp_store=MEMORY")
    if profile.mmap_size_bytes is not None:
        statements.append(f"PRAGMA mmap_size={profile.mmap_size_bytes}")
    return statements


def _post_journal_statements(profile: SQLiteProfile, journal_mode: str) -> list[str]:
    # WAL fallback to DELETE always uses FULL synchronous for rollback-journal safety.
    synchronous = profile.synchronous.upper() if journal_mode == "WAL" else "FULL"
    statements = [
        f"PRAGMA synchronous={synchronous}",
        f"PRAGMA busy_timeout={profile.busy_timeout_ms}",
    ]
    if profile.cache_size is not None:
        statements.append(f"PRAGMA cache_size={profile.cache_size}")
    if profile.temp_store_memory:
        statements.append("PRAGMA temp_store=MEMORY")
    if profile.mmap_size_bytes is not None:
        statements.append(f"PRAGMA mmap_size={profile.mmap_size_bytes}")
    statements.append(f"PRAGMA foreign_keys={'ON' if profile.foreign_keys else 'OFF'}")
    statements.append(f"PRAGMA secure_delete={profile.secure_delete.upper()}")
    statements.append(f"PRAGMA cell_size_check={'ON' if profile.cell_size_check else 'OFF'}")
    if journal_mode == "WAL" and profile.wal_autocheckpoint_pages is not None:
        statements.append(f"PRAGMA wal_autocheckpoint={profile.wal_autocheckpoint_pages}")
    return statements


def harden_connection_sync(
    conn: sqlite3.Connection,
    profile: SQLiteProfile = DEFAULT,
    *,
    db_path: Path | None = None,
) -> str:
    """Apply ``profile`` to a synchronous connection; return the journal mode."""
    if profile.read_only:
        for statement in _read_only_statements(profile):
            conn.execute(statement)
        return "READONLY"

    if profile.page_size_bytes is not None:
        conn.execute(f"PRAGMA page_size={profile.page_size_bytes}")

    journal_mode = _apply_journal_mode_sync(conn, profile, db_path)
    for statement in _post_journal_statements(profile, journal_mode):
        conn.execute(statement)
    return journal_mode


def _apply_journal_mode_sync(conn: sqlite3.Connection, profile: SQLiteProfile, db_path: Path | None) -> str:
    if not profile.use_wal:
        conn.execute("PRAGMA journal_mode=DELETE")
        return "DELETE"
    try:
        row = conn.execute("PRAGMA journal_mode=WAL").fetchone()
        mode = str(row[0]).upper() if row else "WAL"
        return "WAL" if mode == "WAL" else mode
    except sqlite3.Error as exc:
        if should_fallback_to_delete(exc, db_path):
            logger.warning("SQLite WAL unsupported on this filesystem (%s); using DELETE.", exc)
            conn.execute("PRAGMA journal_mode=DELETE")
            return "DELETE"
        raise


async def harden_connection_async(
    conn: aiosqlite.Connection,
    profile: SQLiteProfile = DEFAULT,
    *,
    db_path: Path | None = None,
) -> str:
    """Apply ``profile`` to an aiosqlite connection; return the journal mode."""
    if profile.read_only:
        for statement in _read_only_statements(profile):
            await conn.execute(statement)
        return "READONLY"

    if profile.page_size_bytes is not None:
        await conn.execute(f"PRAGMA page_size={profile.page_size_bytes}")

    journal_mode = await _apply_journal_mode_async(conn, profile, db_path)
    for statement in _post_journal_statements(profile, journal_mode):
        await conn.execute(statement)
    return journal_mode


async def _apply_journal_mode_async(conn: aiosqlite.Connection, profile: SQLiteProfile, db_path: Path | None) -> str:
    if not profile.use_wal:
        await conn.execute("PRAGMA journal_mode=DELETE")
        return "DELETE"
    try:
        cursor = await conn.execute("PRAGMA journal_mode=WAL")
        row = await cursor.fetchone()
        mode = str(row[0]).upper() if row else "WAL"
        return "WAL" if mode == "WAL" else mode
    except sqlite3.Error as exc:
        if should_fallback_to_delete(exc, db_path):
            logger.warning("SQLite WAL unsupported on this filesystem (%s); using DELETE.", exc)
            await conn.execute("PRAGMA journal_mode=DELETE")
            return "DELETE"
        raise


@asynccontextmanager
async def connect_async(db_path: str | Path, profile: SQLiteProfile = DEFAULT) -> AsyncIterator[aiosqlite.Connection]:
    """Open + harden a short-lived aiosqlite connection, closing it on exit."""
    import aiosqlite

    async with aiosqlite.connect(str(db_path)) as conn:
        await harden_connection_async(conn, profile, db_path=Path(db_path))
        yield conn
