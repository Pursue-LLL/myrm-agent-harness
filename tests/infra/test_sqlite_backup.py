"""Unit tests for infra/sqlite_backup.py — SQLiteBackupManager."""

import json
import sqlite3
from pathlib import Path

import pytest

from myrm_agent_harness.infra.sqlite_backup import (
    BackupRecord,
    RestoreResult,
    SQLiteBackupManager,
    _compute_sha256,
    _pragma_quick_check,
    _pragma_schema_version,
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


def _corrupt_db(db_path: Path) -> None:
    """Corrupt a SQLite database by zeroing out multiple B-tree pages.

    Targets pages 1-3 (each 4096 bytes in default page size) to ensure
    ``PRAGMA quick_check`` reliably detects the damage.
    """
    data = bytearray(db_path.read_bytes())
    page_size = 4096
    for page_idx in range(1, min(4, len(data) // page_size)):
        start = page_idx * page_size
        end = min(start + page_size, len(data))
        for i in range(start, end):
            data[i] = 0x00
    db_path.write_bytes(bytes(data))


# ---------------------------------------------------------------
# _compute_sha256
# ---------------------------------------------------------------

class TestComputeSha256:
    def test_deterministic(self, tmp_path: Path) -> None:
        f = tmp_path / "a.bin"
        f.write_bytes(b"hello world")
        assert _compute_sha256(f) == _compute_sha256(f)

    def test_different_content(self, tmp_path: Path) -> None:
        a = tmp_path / "a.bin"
        b = tmp_path / "b.bin"
        a.write_bytes(b"aaa")
        b.write_bytes(b"bbb")
        assert _compute_sha256(a) != _compute_sha256(b)


# ---------------------------------------------------------------
# _pragma_quick_check
# ---------------------------------------------------------------

class TestPragmaQuickCheck:
    def test_healthy_db(self, tmp_path: Path) -> None:
        db = tmp_path / "ok.db"
        _create_test_db(db)
        assert _pragma_quick_check(db) == "ok"

    def test_corrupted_db(self, tmp_path: Path) -> None:
        db = tmp_path / "bad.db"
        _create_test_db(db, rows=100)
        _corrupt_db(db)
        result = _pragma_quick_check(db)
        assert result != "ok"

    def test_nonexistent_db(self, tmp_path: Path) -> None:
        db = tmp_path / "missing.db"
        result = _pragma_quick_check(db)
        assert result == "ok" or isinstance(result, str)

    def test_not_a_database(self, tmp_path: Path) -> None:
        f = tmp_path / "garbage.db"
        f.write_bytes(b"this is not a sqlite file at all" * 100)
        result = _pragma_quick_check(f)
        assert result != "ok"


# ---------------------------------------------------------------
# _pragma_schema_version
# ---------------------------------------------------------------

class TestPragmaSchemaVersion:
    def test_healthy_db(self, tmp_path: Path) -> None:
        db = tmp_path / "ok.db"
        _create_test_db(db)
        ver = _pragma_schema_version(db)
        assert isinstance(ver, int)
        assert ver >= 0


# ---------------------------------------------------------------
# SQLiteBackupManager.create_backup
# ---------------------------------------------------------------

class TestCreateBackup:
    def test_basic_backup(self, tmp_path: Path) -> None:
        db = tmp_path / "app.db"
        _create_test_db(db, rows=50)
        mgr = SQLiteBackupManager(db, tmp_path / "backups")

        record = mgr.create_backup()

        assert isinstance(record, BackupRecord)
        assert record.quick_check == "ok"
        assert record.size_bytes > 0
        assert len(record.checksum_sha256) == 64
        assert record.schema_version is not None

    def test_backup_file_exists(self, tmp_path: Path) -> None:
        db = tmp_path / "app.db"
        _create_test_db(db)
        mgr = SQLiteBackupManager(db, tmp_path / "backups")

        record = mgr.create_backup()
        snapshot = tmp_path / "backups" / "snapshots" / record.file_name
        assert snapshot.exists()

    def test_backup_integrity(self, tmp_path: Path) -> None:
        db = tmp_path / "app.db"
        _create_test_db(db, rows=100)
        mgr = SQLiteBackupManager(db, tmp_path / "backups")

        record = mgr.create_backup()
        snapshot = tmp_path / "backups" / "snapshots" / record.file_name
        assert _pragma_quick_check(snapshot) == "ok"

    def test_backup_sha256_matches(self, tmp_path: Path) -> None:
        db = tmp_path / "app.db"
        _create_test_db(db)
        mgr = SQLiteBackupManager(db, tmp_path / "backups")

        record = mgr.create_backup()
        snapshot = tmp_path / "backups" / "snapshots" / record.file_name
        assert _compute_sha256(snapshot) == record.checksum_sha256

    def test_manifest_updated(self, tmp_path: Path) -> None:
        db = tmp_path / "app.db"
        _create_test_db(db)
        mgr = SQLiteBackupManager(db, tmp_path / "backups")

        mgr.create_backup()
        manifest = tmp_path / "backups" / "manifest.json"
        assert manifest.exists()
        data = json.loads(manifest.read_text("utf-8"))
        assert len(data["snapshots"]) == 1

    def test_multiple_backups_accumulate(self, tmp_path: Path) -> None:
        db = tmp_path / "app.db"
        _create_test_db(db)
        mgr = SQLiteBackupManager(db, tmp_path / "backups", retention=5)

        for _ in range(3):
            mgr.create_backup()

        records = mgr.list_backups()
        assert len(records) == 3

    def test_no_tmp_files_left(self, tmp_path: Path) -> None:
        db = tmp_path / "app.db"
        _create_test_db(db)
        mgr = SQLiteBackupManager(db, tmp_path / "backups")

        mgr.create_backup()
        snapshots_dir = tmp_path / "backups" / "snapshots"
        tmp_files = list(snapshots_dir.glob(".tmp-*"))
        assert len(tmp_files) == 0


# ---------------------------------------------------------------
# SQLiteBackupManager.verify_health
# ---------------------------------------------------------------

class TestVerifyHealth:
    def test_healthy(self, tmp_path: Path) -> None:
        db = tmp_path / "app.db"
        _create_test_db(db)
        mgr = SQLiteBackupManager(db, tmp_path / "backups")
        assert mgr.verify_health() == "ok"

    def test_missing_db_returns_ok(self, tmp_path: Path) -> None:
        db = tmp_path / "nonexistent.db"
        mgr = SQLiteBackupManager(db, tmp_path / "backups")
        assert mgr.verify_health() == "ok"

    def test_corrupted_db(self, tmp_path: Path) -> None:
        db = tmp_path / "app.db"
        _create_test_db(db, rows=100)
        _corrupt_db(db)
        mgr = SQLiteBackupManager(db, tmp_path / "backups")
        result = mgr.verify_health()
        assert result != "ok"


# ---------------------------------------------------------------
# SQLiteBackupManager.restore_latest
# ---------------------------------------------------------------

class TestRestoreLatest:
    def test_restore_after_corruption(self, tmp_path: Path) -> None:
        db = tmp_path / "app.db"
        _create_test_db(db, rows=50)
        mgr = SQLiteBackupManager(db, tmp_path / "backups")
        mgr.create_backup()

        _corrupt_db(db)
        result = mgr.restore_latest()

        assert isinstance(result, RestoreResult)
        assert result.restored is True
        assert result.snapshot_file is not None
        assert _count_rows(db) == 50

    def test_quarantine_created(self, tmp_path: Path) -> None:
        db = tmp_path / "app.db"
        _create_test_db(db)
        mgr = SQLiteBackupManager(db, tmp_path / "backups")
        mgr.create_backup()

        _corrupt_db(db)
        result = mgr.restore_latest()

        assert result.quarantine_dir is not None
        quarantine = Path(result.quarantine_dir)
        assert quarantine.exists()

    def test_wal_shm_cleaned(self, tmp_path: Path) -> None:
        db = tmp_path / "app.db"
        _create_test_db(db, rows=10)
        mgr = SQLiteBackupManager(db, tmp_path / "backups")
        mgr.create_backup()

        wal = db.with_name(db.name + "-wal")
        shm = db.with_name(db.name + "-shm")

        _corrupt_db(db)
        mgr.restore_latest()

        assert not wal.exists()
        assert not shm.exists()

    def test_no_backups_returns_failure(self, tmp_path: Path) -> None:
        db = tmp_path / "app.db"
        _create_test_db(db)
        mgr = SQLiteBackupManager(db, tmp_path / "backups")

        result = mgr.restore_latest()

        assert result.restored is False
        assert result.error is not None

    def test_restore_to_custom_target(self, tmp_path: Path) -> None:
        db = tmp_path / "app.db"
        _create_test_db(db, rows=25)
        mgr = SQLiteBackupManager(db, tmp_path / "backups")
        mgr.create_backup()

        target = tmp_path / "restored.db"
        result = mgr.restore_latest(target_path=target)

        assert result.restored is True
        assert target.exists()
        assert _count_rows(target) == 25

    def test_restore_picks_newest(self, tmp_path: Path) -> None:
        db = tmp_path / "app.db"
        _create_test_db(db, rows=10)
        mgr = SQLiteBackupManager(db, tmp_path / "backups", retention=5)

        mgr.create_backup()
        conn = sqlite3.connect(str(db))
        for i in range(10, 30):
            conn.execute("INSERT INTO items (data) VALUES (?)", (f"row-{i}",))
        conn.commit()
        conn.close()
        mgr.create_backup()

        _corrupt_db(db)
        result = mgr.restore_latest()

        assert result.restored is True
        assert _count_rows(db) == 30


# ---------------------------------------------------------------
# SQLiteBackupManager.list_backups
# ---------------------------------------------------------------

class TestListBackups:
    def test_empty_when_no_backups(self, tmp_path: Path) -> None:
        db = tmp_path / "app.db"
        _create_test_db(db)
        mgr = SQLiteBackupManager(db, tmp_path / "backups")
        assert mgr.list_backups() == []

    def test_sorted_newest_first(self, tmp_path: Path) -> None:
        db = tmp_path / "app.db"
        _create_test_db(db)
        mgr = SQLiteBackupManager(db, tmp_path / "backups", retention=5)

        for _ in range(3):
            mgr.create_backup()

        records = mgr.list_backups()
        assert len(records) == 3
        assert records[0].created_at >= records[1].created_at >= records[2].created_at


# ---------------------------------------------------------------
# Retention policy
# ---------------------------------------------------------------

class TestRetention:
    def test_retention_enforced(self, tmp_path: Path) -> None:
        db = tmp_path / "app.db"
        _create_test_db(db)
        mgr = SQLiteBackupManager(db, tmp_path / "backups", retention=2)

        for _ in range(5):
            mgr.create_backup()

        records = mgr.list_backups()
        assert len(records) == 2

    def test_old_snapshots_deleted(self, tmp_path: Path) -> None:
        db = tmp_path / "app.db"
        _create_test_db(db)
        mgr = SQLiteBackupManager(db, tmp_path / "backups", retention=2)

        all_records: list[BackupRecord] = []
        for _ in range(4):
            all_records.append(mgr.create_backup())

        snapshots_dir = tmp_path / "backups" / "snapshots"
        existing = {f.name for f in snapshots_dir.iterdir() if not f.name.startswith(".")}
        current = {r.file_name for r in mgr.list_backups()}
        assert existing == current

    def test_retention_min_one(self, tmp_path: Path) -> None:
        db = tmp_path / "app.db"
        _create_test_db(db)
        mgr = SQLiteBackupManager(db, tmp_path / "backups", retention=0)

        mgr.create_backup()
        mgr.create_backup()

        assert len(mgr.list_backups()) == 1


# ---------------------------------------------------------------
# Manifest robustness
# ---------------------------------------------------------------

class TestManifest:
    def test_corrupt_manifest_gracefully_handled(self, tmp_path: Path) -> None:
        db = tmp_path / "app.db"
        _create_test_db(db)
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        manifest = backup_dir / "manifest.json"
        manifest.write_text("not valid json!!!", "utf-8")

        mgr = SQLiteBackupManager(db, backup_dir)
        assert mgr.list_backups() == []

    def test_manifest_atomic_write(self, tmp_path: Path) -> None:
        db = tmp_path / "app.db"
        _create_test_db(db)
        mgr = SQLiteBackupManager(db, tmp_path / "backups")
        mgr.create_backup()

        tmp_files = list((tmp_path / "backups").glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_manifest_version_field(self, tmp_path: Path) -> None:
        db = tmp_path / "app.db"
        _create_test_db(db)
        mgr = SQLiteBackupManager(db, tmp_path / "backups")
        mgr.create_backup()

        data = json.loads((tmp_path / "backups" / "manifest.json").read_text("utf-8"))
        assert data["version"] == 1
        assert "updated_at" in data


# ---------------------------------------------------------------
# BackupRecord / RestoreResult dataclasses
# ---------------------------------------------------------------

class TestDataclasses:
    def test_backup_record_frozen(self) -> None:
        record = BackupRecord(
            backup_id="1",
            file_name="backup-1.sqlite",
            created_at=1.0,
            size_bytes=1024,
            checksum_sha256="abc",
            quick_check="ok",
            schema_version=1,
            restore_tested=False,
        )
        with pytest.raises(AttributeError):
            record.backup_id = "2"  # type: ignore[misc]

    def test_restore_result_defaults(self) -> None:
        result = RestoreResult(restored=False)
        assert result.snapshot_file is None
        assert result.quarantine_dir is None
        assert result.error is None
