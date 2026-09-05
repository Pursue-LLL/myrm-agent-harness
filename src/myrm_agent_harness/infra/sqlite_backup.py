"""SQLite hot-backup manager with integrity verification and atomic publish.

Provides online backup via the native ``sqlite3.Connection.backup()`` API,
SHA-256 checksum verification, quarantine of corrupted databases, and a
JSON manifest for tracking backup metadata.

Usage::

    manager = SQLiteBackupManager(db_path="/data/app.db", backup_dir="/data/backups")
    record  = manager.create_backup()          # hot-backup without blocking readers
    result  = manager.restore_latest("/data/app.db")  # restore from latest valid snapshot

[INPUT]
- pathlib.Path, sqlite3.Connection

[OUTPUT]
- SQLiteBackupManager: Hot-backup, verify, restore, quarantine for SQLite databases.
- BackupRecord: Immutable metadata for a single backup snapshot.
- RestoreResult: Outcome of a restore operation.
- SnapshotVerificationResult: Integrity verification outcome.

[POS]
Framework-level SQLite physical backup utility. Technology-agnostic — any project
that stores data in SQLite can use this. Business-layer integration (scheduling,
GUI repair actions) is handled externally.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path

from .sqlite_backup_models import (
    _BACKUP_PAGE_BATCH,
    _DEFAULT_RETENTION,
    _MANIFEST_FILE,
    _MANIFEST_VERSION,
    _QUARANTINE_DIR,
    _SNAPSHOTS_DIR,
    _compute_sha256,
    _pragma_integrity_check,
    _pragma_quick_check,
    _pragma_schema_version,
    _timestamp_dirname,
    BackupRecord,
    RestoreResult,
    SnapshotVerificationResult,
)

logger = logging.getLogger(__name__)

__all__ = [
    "SQLiteBackupManager",
    "BackupRecord",
    "RestoreResult",
    "SnapshotVerificationResult",
    "_compute_sha256",
    "_pragma_quick_check",
    "_pragma_integrity_check",
    "_pragma_schema_version",
]


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

    def verify_snapshot(
        self, snapshot_ref: str | Path | BackupRecord | None = None
    ) -> SnapshotVerificationResult:
        """Verify artifact hash and SQLite integrity for a snapshot.

        Validates:
          1. Snapshot file existence.
          2. SHA-256 matches the manifest checksum (tamper & corruption check).
          3. SQLite PRAGMA integrity_check passes.
        """
        manifest = self._read_manifest()
        if not manifest:
            return SnapshotVerificationResult(
                valid=False,
                error="No backup manifest or snapshots available",
            )

        target_record: BackupRecord | None = None
        target_path: Path | None = None

        if snapshot_ref is None:
            target_record = max(manifest, key=lambda r: r.created_at)
            target_path = self._snapshots_dir / target_record.file_name
        elif isinstance(snapshot_ref, BackupRecord):
            target_record = snapshot_ref
            target_path = self._snapshots_dir / target_record.file_name
        elif isinstance(snapshot_ref, Path):
            target_path = snapshot_ref
            target_record = next((r for r in manifest if r.file_name == target_path.name), None)
        elif isinstance(snapshot_ref, str):
            target_record = next(
                (r for r in manifest if r.backup_id == snapshot_ref or r.file_name == snapshot_ref),
                None,
            )
            target_path = self._snapshots_dir / (
                target_record.file_name if target_record else snapshot_ref
            )
        else:
            return SnapshotVerificationResult(
                valid=False,
                error=f"Unsupported snapshot reference type: {type(snapshot_ref)}",
            )

        if target_path is None or not target_path.exists():
            return SnapshotVerificationResult(
                valid=False,
                backup_id=target_record.backup_id if target_record else None,
                file_name=target_record.file_name if target_record else None,
                error=f"Snapshot file not found: {target_path}",
            )

        actual_sha256 = _compute_sha256(target_path)
        expected_sha256 = target_record.checksum_sha256 if target_record else None
        checksum_matched = bool(expected_sha256 and actual_sha256.lower() == expected_sha256.lower())

        if expected_sha256 and not checksum_matched:
            return SnapshotVerificationResult(
                valid=False,
                backup_id=target_record.backup_id if target_record else None,
                file_name=target_path.name,
                checksum_sha256=actual_sha256,
                checksum_matched=False,
                integrity_check="skipped",
                error=f"Checksum mismatch: expected {expected_sha256}, got {actual_sha256}",
            )

        ic = _pragma_integrity_check(target_path)
        if ic != "ok":
            return SnapshotVerificationResult(
                valid=False,
                backup_id=target_record.backup_id if target_record else None,
                file_name=target_path.name,
                checksum_sha256=actual_sha256,
                checksum_matched=checksum_matched,
                integrity_check=ic,
                error=f"SQLite integrity_check failed: {ic}",
            )

        return SnapshotVerificationResult(
            valid=True,
            backup_id=target_record.backup_id if target_record else None,
            file_name=target_path.name,
            checksum_sha256=actual_sha256,
            checksum_matched=checksum_matched or (expected_sha256 is None),
            integrity_check="ok",
        )

    def verify_all_snapshots(self) -> list[SnapshotVerificationResult]:
        """Verify all snapshots recorded in the manifest (newest first)."""
        manifest = self.list_backups()
        return [self.verify_snapshot(record) for record in manifest]

    def restore_to_fresh_target(
        self,
        target_dir: str | Path | None = None,
        snapshot_ref: str | Path | BackupRecord | None = None,
    ) -> tuple[RestoreResult, Path | None]:
        """Safely restore a verified snapshot to a fresh, isolated database file.

        Enforces the Fresh-Target Restore Gate:
        - Never touches or overwrites the live active database.
        - Verifies SHA-256 and SQLite integrity before and after copy.
        - Creates a new unique file for testing or recovery migration.
        """
        dest_dir = Path(target_dir) if target_dir else self._db_path.parent
        dest_dir.mkdir(parents=True, exist_ok=True)

        v_res = self.verify_snapshot(snapshot_ref)
        if not v_res.valid or not v_res.file_name:
            return (
                RestoreResult(
                    restored=False,
                    snapshot_file=v_res.file_name,
                    error=f"Fresh-target restore blocked: snapshot verification failed ({v_res.error})",
                ),
                None,
            )

        source_snapshot = self._snapshots_dir / v_res.file_name
        ts_suffix = f"{int(time.time() * 1000)}"
        fresh_name = f"{self._db_path.stem}.restored.{ts_suffix}.sqlite"
        fresh_target = dest_dir / fresh_name

        try:
            shutil.copy2(str(source_snapshot), str(fresh_target))
            for suffix in ("-wal", "-shm"):
                fresh_target.with_name(fresh_target.name + suffix).unlink(missing_ok=True)

            post_ic = _pragma_integrity_check(fresh_target)
            if post_ic != "ok":
                fresh_target.unlink(missing_ok=True)
                return (
                    RestoreResult(
                        restored=False,
                        snapshot_file=v_res.file_name,
                        error=f"Post-restore integrity check failed: {post_ic}",
                    ),
                    None,
                )

            logger.info(
                "[SQLiteBackup] Fresh-target restore succeeded: %s -> %s",
                v_res.file_name,
                fresh_target,
            )
            return (
                RestoreResult(
                    restored=True,
                    snapshot_file=v_res.file_name,
                ),
                fresh_target,
            )
        except OSError as exc:
            fresh_target.unlink(missing_ok=True)
            return (
                RestoreResult(
                    restored=False,
                    snapshot_file=v_res.file_name,
                    error=f"Failed to copy fresh-target restore file: {exc}",
                ),
                None,
            )

    def restore_latest(
        self,
        target_path: str | Path | None = None,
        *,
        allow_live_overwrite: bool = True,
    ) -> RestoreResult:
        """Restore the database from the most recent valid backup.

        Steps:
          1. Check safety against accidental in-place live overwrites.
          2. Verify snapshot hash and SQLite integrity.
          3. Quarantine current database and WAL/SHM files if dest exists.
          4. Restore and verify SQLite integrity on target.
        """
        dest = Path(target_path) if target_path else self._db_path
        if not allow_live_overwrite and dest.resolve() == self._db_path.resolve():
            return RestoreResult(
                restored=False,
                error="Live database overwrite prevented by safety gate. Set allow_live_overwrite=True or use restore_to_fresh_target().",
            )

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

            v_res = self.verify_snapshot(record)
            if not v_res.valid:
                logger.warning(
                    "[SQLiteBackup] Snapshot %s failed verification (%s), trying next",
                    record.file_name,
                    v_res.error,
                )
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

                ic = _pragma_integrity_check(dest)
                if ic == "ok":
                    logger.info(
                        "[SQLiteBackup] Restored from snapshot %s",
                        record.file_name,
                    )
                    return RestoreResult(
                        restored=True,
                        snapshot_file=record.file_name,
                        quarantine_dir=str(quarantine_target) if quarantined else None,
                    )

                logger.warning(
                    "[SQLiteBackup] Target %s failed integrity_check: %s, trying next",
                    record.file_name,
                    ic,
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
