"""SQLite hot-backup manager with integrity verification and atomic publish.

Provides online backup via the native ``sqlite3.Connection.backup()`` API,
SHA-256 checksum verification, quarantine of corrupted databases, and a
JSON manifest for tracking backup metadata.

Usage::

    manager = SQLiteBackupManager(db_path="/data/app.db", backup_dir="/data/backups")
    record  = manager.create_backup()          # hot-backup without blocking readers
    result  = manager.restore_latest("/data/app.db")  # restore from latest valid snapshot

[INPUT]
- (none)

[OUTPUT]
- SQLiteBackupManager: Hot-backup, verify, restore, quarantine for SQLite databases.
- BackupRecord: Immutable metadata for a single backup snapshot.
- RestoreResult: Outcome of a restore operation.

[POS]
Framework-level SQLite physical backup utility. Technology-agnostic — any project
that stores data in SQLite can use this. Business-layer integration (scheduling,
GUI repair actions) is handled externally.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

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


def _compute_sha256(path: Path) -> str:
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


def _pragma_schema_version(db_path: str | Path) -> int | None:
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    try:
        row = conn.execute("PRAGMA schema_version").fetchone()
        return int(row[0]) if row and isinstance(row[0], int) else None
    finally:
        conn.close()


def _timestamp_dirname(ts: float) -> str:
    t = time.gmtime(ts)
    return f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}T{t.tm_hour:02d}-{t.tm_min:02d}-{t.tm_sec:02d}"


class SQLiteBackupManager:
    """Hot-backup, verify, restore, and quarantine manager for SQLite databases.

    Designed as a framework-level utility: no business logic, no async,
    no external dependencies beyond the Python standard library.

    Args:
        db_path: Path to the SQLite database file to protect.
        backup_dir: Directory where backups, manifest, and quarantine are stored.
        retention: Maximum number of backup snapshots to keep.
    """

    def __init__(
        self,
        db_path: str | Path,
        backup_dir: str | Path,
        *,
        retention: int = _DEFAULT_RETENTION,
    ) -> None:
        self._db_path = Path(db_path)
        self._backup_dir = Path(backup_dir)
        self._retention = max(1, retention)
        self._snapshots_dir = self._backup_dir / _SNAPSHOTS_DIR
        self._quarantine_dir = self._backup_dir / _QUARANTINE_DIR
        self._manifest_path = self._backup_dir / _MANIFEST_FILE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_backup(self) -> BackupRecord:
        """Create a hot-backup of the database.

        Uses ``sqlite3.Connection.backup()`` which copies pages without
        blocking concurrent readers/writers.  The backup file is written
        to a temporary path first, verified with ``PRAGMA quick_check``,
        then atomically published via ``os.replace``.

        Returns:
            BackupRecord with metadata of the new snapshot.

        Raises:
            sqlite3.Error: If the source database cannot be opened.
            OSError: If filesystem operations fail.
        """
        self._snapshots_dir.mkdir(parents=True, exist_ok=True)

        backup_id = f"{int(time.time() * 1000)}"
        tmp_name = f".tmp-{backup_id}.sqlite"
        final_name = f"backup-{backup_id}.sqlite"
        tmp_path = self._snapshots_dir / tmp_name
        final_path = self._snapshots_dir / final_name

        logger.info("[SQLiteBackup] Starting hot backup of %s", self._db_path)

        src = sqlite3.connect(str(self._db_path), timeout=10.0)
        try:
            dst = sqlite3.connect(str(tmp_path))
            try:
                src.backup(dst, pages=_BACKUP_PAGE_BATCH)
            finally:
                dst.close()
        finally:
            src.close()

        qc = _pragma_quick_check(tmp_path)
        if qc != "ok":
            tmp_path.unlink(missing_ok=True)
            msg = f"Backup quick_check failed: {qc}"
            logger.error("[SQLiteBackup] %s", msg)
            raise RuntimeError(msg)

        checksum = _compute_sha256(tmp_path)
        schema_ver = _pragma_schema_version(tmp_path)

        os.replace(str(tmp_path), str(final_path))

        record = BackupRecord(
            backup_id=backup_id,
            file_name=final_name,
            created_at=time.time(),
            size_bytes=final_path.stat().st_size,
            checksum_sha256=checksum,
            quick_check="ok",
            schema_version=schema_ver,
            restore_tested=False,
        )

        self._append_to_manifest(record)
        self._enforce_retention()

        logger.info(
            "[SQLiteBackup] Backup complete: %s (%d bytes, sha256=%s…)",
            final_name,
            record.size_bytes,
            checksum[:12],
        )
        return record

    def verify_health(self) -> str:
        """Run ``PRAGMA quick_check`` on the live database.

        Returns:
            ``"ok"`` if healthy, otherwise the error description.
        """
        if not self._db_path.exists():
            return "ok"
        return _pragma_quick_check(self._db_path)

    def restore_latest(self, target_path: str | Path | None = None) -> RestoreResult:
        """Restore the live database from the most recent valid backup.

        Steps:
          1. Quarantine the current (presumably corrupted) database and WAL/SHM files.
          2. Iterate snapshots newest-first, copy to target, run ``PRAGMA integrity_check``.
          3. Return on the first snapshot that passes integrity verification.

        Args:
            target_path: Where to restore.  Defaults to ``self._db_path``.

        Returns:
            RestoreResult indicating success or failure.
        """
        dest = Path(target_path) if target_path else self._db_path
        manifest = self._read_manifest()

        if not manifest:
            return RestoreResult(restored=False, error="No backup snapshots available")

        quarantine_ts = _timestamp_dirname(time.time())
        quarantine_target = self._quarantine_dir / quarantine_ts
        quarantined = False

        for record in sorted(manifest, key=lambda r: r.created_at, reverse=True):
            snapshot_path = self._snapshots_dir / record.file_name
            if not snapshot_path.exists():
                continue

            if not quarantined and dest.exists():
                quarantine_target.mkdir(parents=True, exist_ok=True)
                self._quarantine_files(dest, quarantine_target)
                quarantined = True

            try:
                shutil.copy2(str(snapshot_path), str(dest))
                for suffix in ("-wal", "-shm"):
                    wal = dest.with_name(dest.name + suffix)
                    wal.unlink(missing_ok=True)

                conn = sqlite3.connect(str(dest), timeout=5.0)
                try:
                    ic = conn.execute("PRAGMA integrity_check").fetchone()
                    if ic and ic[0] == "ok":
                        logger.info(
                            "[SQLiteBackup] Restored from snapshot %s",
                            record.file_name,
                        )
                        return RestoreResult(
                            restored=True,
                            snapshot_file=record.file_name,
                            quarantine_dir=str(quarantine_target) if quarantined else None,
                        )
                finally:
                    conn.close()

                logger.warning(
                    "[SQLiteBackup] Snapshot %s failed integrity_check, trying next",
                    record.file_name,
                )
                dest.unlink(missing_ok=True)

            except (sqlite3.Error, OSError) as exc:
                logger.warning(
                    "[SQLiteBackup] Failed to restore %s: %s",
                    record.file_name,
                    exc,
                )
                dest.unlink(missing_ok=True)

        return RestoreResult(
            restored=False,
            quarantine_dir=str(quarantine_target) if quarantined else None,
            error="All backup snapshots failed integrity verification",
        )

    def list_backups(self) -> list[BackupRecord]:
        """Return backup records sorted newest-first."""
        return sorted(self._read_manifest(), key=lambda r: r.created_at, reverse=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _quarantine_files(self, db_path: Path, target_dir: Path) -> None:
        """Move the database and its WAL/SHM files into quarantine."""
        for suffix in ("", "-wal", "-shm"):
            src = db_path.with_name(db_path.name + suffix) if suffix else db_path
            if src.exists():
                dst = target_dir / src.name
                try:
                    shutil.move(str(src), str(dst))
                except OSError:
                    logger.warning("[SQLiteBackup] Could not quarantine %s", src)

    def _read_manifest(self) -> list[BackupRecord]:
        if not self._manifest_path.exists():
            return []
        try:
            data = json.loads(self._manifest_path.read_text("utf-8"))
            return [BackupRecord(**s) for s in data.get("snapshots", [])]
        except (json.JSONDecodeError, TypeError, KeyError):
            logger.warning("[SQLiteBackup] Corrupt manifest, returning empty")
            return []

    def _write_manifest(self, records: list[BackupRecord]) -> None:
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": _MANIFEST_VERSION,
            "snapshots": [asdict(r) for r in records],
            "updated_at": time.time(),
        }
        tmp = self._manifest_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), "utf-8")
        os.replace(str(tmp), str(self._manifest_path))

    def _append_to_manifest(self, record: BackupRecord) -> None:
        records = self._read_manifest()
        records.append(record)
        self._write_manifest(records)

    def _enforce_retention(self) -> None:
        records = sorted(self._read_manifest(), key=lambda r: r.created_at, reverse=True)
        if len(records) <= self._retention:
            return
        keep = records[: self._retention]
        remove = records[self._retention :]
        for r in remove:
            path = self._snapshots_dir / r.file_name
            path.unlink(missing_ok=True)
            logger.debug("[SQLiteBackup] Removed old snapshot %s", r.file_name)
        self._write_manifest(keep)
