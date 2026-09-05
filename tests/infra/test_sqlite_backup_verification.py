"""Unit tests for SQLite snapshot verification and fresh-target isolated restore."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from myrm_agent_harness.infra.sqlite_backup import (
    SnapshotVerificationResult,
    SQLiteBackupManager,
)


def _create_test_db(db_path: Path, *, rows: int = 10) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, data TEXT)")
    for i in range(rows):
        conn.execute("INSERT INTO items (data) VALUES (?)", (f"row-{i}",))
    conn.commit()
    conn.close()


def _count_rows(db_path: Path) -> int:
    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT COUNT(*) FROM items").fetchone()
    conn.close()
    return row[0] if row else 0


class TestVerifySnapshot:
    def test_verify_snapshot_healthy(self, tmp_path: Path) -> None:
        db = tmp_path / "app.db"
        _create_test_db(db, rows=5)
        mgr = SQLiteBackupManager(db, tmp_path / "backups")
        record = mgr.create_backup()

        res = mgr.verify_snapshot()
        assert res.valid is True
        assert res.backup_id == record.backup_id
        assert res.checksum_matched is True
        assert res.integrity_check == "ok"
        assert res.error is None

    def test_verify_all_snapshots(self, tmp_path: Path) -> None:
        db = tmp_path / "app.db"
        _create_test_db(db, rows=5)
        mgr = SQLiteBackupManager(db, tmp_path / "backups", retention=3)
        mgr.create_backup()
        mgr.create_backup()

        results = mgr.verify_all_snapshots()
        assert len(results) == 2
        assert all(r.valid for r in results)

    def test_verify_snapshot_tampered_fails_checksum(self, tmp_path: Path) -> None:
        db = tmp_path / "app.db"
        _create_test_db(db, rows=5)
        mgr = SQLiteBackupManager(db, tmp_path / "backups")
        record = mgr.create_backup()

        snapshot_path = tmp_path / "backups" / "snapshots" / record.file_name
        snapshot_bytes = bytearray(snapshot_path.read_bytes())
        snapshot_bytes[-1] ^= 0xFF
        snapshot_path.write_bytes(bytes(snapshot_bytes))

        res = mgr.verify_snapshot(record)
        assert res.valid is False
        assert res.checksum_matched is False
        assert "Checksum mismatch" in (res.error or "")
        assert res.integrity_check == "skipped"

    def test_verify_snapshot_missing_file(self, tmp_path: Path) -> None:
        db = tmp_path / "app.db"
        _create_test_db(db, rows=5)
        mgr = SQLiteBackupManager(db, tmp_path / "backups")
        record = mgr.create_backup()

        snapshot_path = tmp_path / "backups" / "snapshots" / record.file_name
        snapshot_path.unlink()

        res = mgr.verify_snapshot(record)
        assert res.valid is False
        assert "Snapshot file not found" in (res.error or "")

    def test_verify_snapshot_empty_manifest(self, tmp_path: Path) -> None:
        db = tmp_path / "app.db"
        _create_test_db(db, rows=5)
        mgr = SQLiteBackupManager(db, tmp_path / "backups")

        res = mgr.verify_snapshot()
        assert res.valid is False
        assert "No backup manifest" in (res.error or "")

    def test_verify_snapshot_by_id_and_path(self, tmp_path: Path) -> None:
        db = tmp_path / "app.db"
        _create_test_db(db, rows=5)
        mgr = SQLiteBackupManager(db, tmp_path / "backups")
        record = mgr.create_backup()

        res_id = mgr.verify_snapshot(record.backup_id)
        assert res_id.valid is True
        assert res_id.backup_id == record.backup_id

        snapshot_path = tmp_path / "backups" / "snapshots" / record.file_name
        res_path = mgr.verify_snapshot(snapshot_path)
        assert res_path.valid is True

    def test_verify_snapshot_invalid_ref_type(self, tmp_path: Path) -> None:
        db = tmp_path / "app.db"
        _create_test_db(db, rows=5)
        mgr = SQLiteBackupManager(db, tmp_path / "backups")
        mgr.create_backup()

        res = mgr.verify_snapshot(12345)  # type: ignore[arg-type]
        assert res.valid is False
        assert "Unsupported snapshot reference type" in (res.error or "")


class TestRestoreToFreshTarget:
    def test_restore_to_fresh_target_success(self, tmp_path: Path) -> None:
        db = tmp_path / "app.db"
        _create_test_db(db, rows=15)
        mgr = SQLiteBackupManager(db, tmp_path / "backups")
        record = mgr.create_backup()

        # Modify live db after backup to verify fresh-target gets backup snapshot state
        conn = sqlite3.connect(str(db))
        conn.execute("INSERT INTO items (data) VALUES ('live-modification')")
        conn.commit()
        conn.close()
        assert _count_rows(db) == 16

        res, fresh_path = mgr.restore_to_fresh_target()
        assert res.restored is True
        assert res.snapshot_file == record.file_name
        assert fresh_path is not None
        assert fresh_path.exists()
        assert fresh_path != db
        assert _count_rows(fresh_path) == 15
        # Ensure live db was NOT touched or overwritten
        assert _count_rows(db) == 16

    def test_restore_to_fresh_target_custom_directory(self, tmp_path: Path) -> None:
        db = tmp_path / "app.db"
        _create_test_db(db, rows=8)
        mgr = SQLiteBackupManager(db, tmp_path / "backups")
        mgr.create_backup()

        custom_dir = tmp_path / "sandbox_recovery"
        res, fresh_path = mgr.restore_to_fresh_target(target_dir=custom_dir)
        assert res.restored is True
        assert fresh_path is not None
        assert fresh_path.parent == custom_dir
        assert fresh_path.exists()
        assert _count_rows(fresh_path) == 8

    def test_restore_to_fresh_target_tampered_blocked(self, tmp_path: Path) -> None:
        db = tmp_path / "app.db"
        _create_test_db(db, rows=8)
        mgr = SQLiteBackupManager(db, tmp_path / "backups")
        record = mgr.create_backup()

        # Tamper with snapshot
        snapshot_path = tmp_path / "backups" / "snapshots" / record.file_name
        b = bytearray(snapshot_path.read_bytes())
        b[-1] ^= 0xFF
        snapshot_path.write_bytes(bytes(b))

        res, fresh_path = mgr.restore_to_fresh_target()
        assert res.restored is False
        assert fresh_path is None
        assert "Fresh-target restore blocked" in (res.error or "")

    def test_restore_to_fresh_target_no_snapshots(self, tmp_path: Path) -> None:
        db = tmp_path / "app.db"
        _create_test_db(db, rows=5)
        mgr = SQLiteBackupManager(db, tmp_path / "backups")

        res, fresh_path = mgr.restore_to_fresh_target()
        assert res.restored is False
        assert fresh_path is None
        assert "Fresh-target restore blocked" in (res.error or "")


class TestSnapshotVerificationResult:
    def test_defaults(self) -> None:
        res = SnapshotVerificationResult(valid=True)
        assert res.valid is True
        assert res.backup_id is None
        assert res.file_name is None
        assert res.checksum_sha256 is None
        assert res.checksum_matched is False
        assert res.integrity_check == "unknown"
        assert res.error is None
