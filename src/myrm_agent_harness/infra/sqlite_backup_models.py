"""Data models and low-level SQLite PRAGMA utilities for sqlite_backup.

Defines immutable records for backup snapshots, verification outcomes,
restore results, low-level hash and SQLite PRAGMA integrity inspectors, and the
lifecycle of the temporary image a backup is written to before it is published.

[INPUT]
- pathlib.Path, sqlite3.Connection

[OUTPUT]
- BackupRecord: Metadata for a single backup snapshot.
- RestoreResult: Outcome of a restore operation.
- SnapshotVerificationResult: Cryptographic and structural verification result.
- Low-level helpers: _compute_sha256, _pragma_quick_check, _pragma_integrity_check,
  _pragma_schema_version, _timestamp_dirname.
- Temporary-image lifecycle: _discard_on_failure, _require_backup_image,
  _sweep_stale_tmp_backups.

[POS]
Harness infra internal models module for SQLite physical backup operations.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

_SNAPSHOTS_DIR = "snapshots"
_QUARANTINE_DIR = "quarantine"
_MANIFEST_FILE = "manifest.json"
_MANIFEST_VERSION = 1
_DEFAULT_RETENTION = 3
_BACKUP_PAGE_BATCH = 100
_TMP_PREFIX = ".tmp-"
# A live copy keeps rewriting its image; one idle this long belongs to a process that died mid-copy.
_STALE_TMP_SECONDS = 5 * 60
_SQLITE_SIDECAR_SUFFIXES = ("-journal", "-wal", "-shm")


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


def _discard_tmp_backup(tmp_path: Path) -> None:
    """Remove a temporary backup image and the SQLite sidecar files its connections left beside it."""
    for suffix in ("", *_SQLITE_SIDECAR_SUFFIXES):
        with suppress(OSError):
            Path(f"{tmp_path}{suffix}").unlink(missing_ok=True)


@contextmanager
def _discard_on_failure(tmp_path: Path) -> Iterator[None]:
    """Delete the temporary image when the block fails or is interrupted, so only a published backup survives."""
    try:
        yield
    except BaseException:
        _discard_tmp_backup(tmp_path)
        raise


def _require_backup_image(tmp_path: Path) -> None:
    """Fail loudly when the copied image is gone: verifying a missing path would create an empty database."""
    if not tmp_path.is_file() or tmp_path.stat().st_size == 0:
        raise RuntimeError(f"Backup image {tmp_path.name} is missing or empty after the copy")


def _sweep_stale_tmp_backups(snapshots_dir: Path) -> int:
    """Delete temporary images and sidecars idle past the grace period; return how many files were removed.

    A killed process cannot clean up after itself, so the next backup reclaims what it left behind. Only
    ``.tmp-`` names are touched: a ``backup-*`` file is never inferred to be an orphan.
    """
    now = time.time()
    removed = 0
    try:
        with os.scandir(snapshots_dir) as entries:
            for entry in entries:
                if not entry.name.startswith(_TMP_PREFIX):
                    continue
                try:
                    stale = now - entry.stat(follow_symlinks=False).st_mtime > _STALE_TMP_SECONDS
                    if stale and entry.is_file(follow_symlinks=False):
                        os.unlink(entry.path)
                        removed += 1
                except OSError:
                    continue
    except OSError:
        return removed
    return removed
