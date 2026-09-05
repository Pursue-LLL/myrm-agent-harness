"""Data models and low-level SQLite PRAGMA utilities for sqlite_backup.

Defines immutable records for backup snapshots, verification outcomes,
restore results, and low-level hash and SQLite PRAGMA integrity inspectors.

[INPUT]
- pathlib.Path, sqlite3.Connection

[OUTPUT]
- BackupRecord: Metadata for a single backup snapshot.
- RestoreResult: Outcome of a restore operation.
- SnapshotVerificationResult: Cryptographic and structural verification result.
- Low-level helpers: _compute_sha256, _pragma_quick_check, _pragma_integrity_check,
  _pragma_schema_version, _timestamp_dirname.

[POS]
Harness infra internal models module for SQLite physical backup operations.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

_SNAPSHOTS_DIR = "snapshots"
_QUARANTINE_DIR = "quarantine"
_MANIFEST_FILE = "manifest.json"
_MANIFEST_VERSION = 1
_DEFAULT_RETENTION = 3
_BACKUP_PAGE_BATCH = 100


@dataclass(frozen=True, slots=True)
class BackupRecord:
    """Immutable metadata for a single backup snapshot."""

    backup_id: str
    file_name: str
    created_at: float
    size_bytes: int
    checksum_sha256: str
    quick_check: str
    schema_version: int | None
    restore_tested: bool


@dataclass(frozen=True, slots=True)
class RestoreResult:
    """Outcome of a restore operation."""

    restored: bool
    snapshot_file: str | None = None
    quarantine_dir: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class SnapshotVerificationResult:
    """Outcome of a snapshot verification check."""

    valid: bool
    backup_id: str | None = None
    file_name: str | None = None
    checksum_sha256: str | None = None
    checksum_matched: bool = False
    integrity_check: str = "unknown"
    error: str | None = None


def _compute_sha256(path: Path) -> str:
    """Compute SHA-256 digest of a file in 64 KiB chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 16):
            h.update(chunk)
    return h.hexdigest()


def _pragma_quick_check(db_path: str | Path) -> str:
    """Run PRAGMA quick_check on a database file and return the result string.

    Returns ``"ok"`` when healthy. On severe corruption the PRAGMA itself may
    raise ``sqlite3.DatabaseError``; this is caught and surfaced as a string.
    """
    try:
        conn = sqlite3.connect(str(db_path), timeout=5.0)
    except sqlite3.Error as exc:
        return f"connection failed: {exc}"
    try:
        row = conn.execute("PRAGMA quick_check").fetchone()
        return row[0] if row else "empty result"
    except sqlite3.DatabaseError as exc:
        return f"database error: {exc}"
    finally:
        conn.close()


def _pragma_integrity_check(db_path: str | Path) -> str:
    """Run PRAGMA integrity_check on a database file and return the result string.

    Performs a thorough validation of B-trees, freelists, and indexing consistency.
    Returns ``"ok"`` when healthy, or an error description string on failure.
    """
    try:
        conn = sqlite3.connect(str(db_path), timeout=5.0)
    except sqlite3.Error as exc:
        return f"connection failed: {exc}"
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        return row[0] if row else "empty result"
    except sqlite3.DatabaseError as exc:
        return f"database error: {exc}"
    finally:
        conn.close()


def _pragma_schema_version(db_path: str | Path) -> int | None:
    """Read PRAGMA schema_version from a database file."""
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    try:
        row = conn.execute("PRAGMA schema_version").fetchone()
        return int(row[0]) if row and isinstance(row[0], int) else None
    finally:
        conn.close()


def _timestamp_dirname(ts: float) -> str:
    """Generate ISO-like UTC timestamp folder name for quarantine directories."""
    t = time.gmtime(ts)
    return f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}T{t.tm_hour:02d}-{t.tm_min:02d}-{t.tm_sec:02d}"
