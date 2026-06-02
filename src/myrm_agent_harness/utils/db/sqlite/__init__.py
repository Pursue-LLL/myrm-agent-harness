"""Unified SQLite hardening factory.

One authoritative place to configure SQLite durability, privacy, concurrency, and
crash-recovery for every store in the framework — replacing scattered, divergent
per-connection PRAGMA blocks.

[INPUT]
- sqlite3.Connection / aiosqlite.Connection, pathlib.Path, SQLiteProfile

[OUTPUT]
- SQLiteProfile + presets (DEFAULT/DURABLE/SENSITIVE/CACHE/READONLY)
- harden_connection_sync / harden_connection_async
- prepare_database_file + integrity guards + WAL checkpoint helpers
- SQLiteIntegrityError

[POS]
Public package facade for ``utils.db.sqlite``. Import this from any store.
"""

from __future__ import annotations

from .hardening import (
    connect_async,
    harden_connection_async,
    harden_connection_sync,
    should_fallback_to_delete,
)
from .integrity import (
    SQLiteIntegrityError,
    check_page_count_invariant,
    checkpoint_truncate_async,
    checkpoint_truncate_sync,
    cleanup_orphan_wal,
    on_disk_journal_mode_is_wal,
    prepare_database_file,
    quick_check_sync,
    validate_sqlite_header,
)
from .profile import CACHE, DEFAULT, DURABLE, READONLY, SENSITIVE, SQLiteProfile

__all__ = [
    "CACHE",
    "DEFAULT",
    "DURABLE",
    "READONLY",
    "SENSITIVE",
    "SQLiteIntegrityError",
    "SQLiteProfile",
    "check_page_count_invariant",
    "checkpoint_truncate_async",
    "checkpoint_truncate_sync",
    "cleanup_orphan_wal",
    "connect_async",
    "harden_connection_async",
    "harden_connection_sync",
    "on_disk_journal_mode_is_wal",
    "prepare_database_file",
    "quick_check_sync",
    "should_fallback_to_delete",
    "validate_sqlite_header",
]
