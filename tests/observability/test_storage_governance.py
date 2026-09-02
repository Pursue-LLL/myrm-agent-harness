"""Unit tests for Storage Governance subsystem (Harness layer)."""

import sqlite3
import tempfile
from pathlib import Path

from myrm_agent_harness.observability.storage_governance import (
    StateSnapshotManager,
    StateStorageCompactor,
    StorageCategory,
    StorageGovernanceInspector,
)


def test_storage_governance_inspector_and_compactor() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        db_path = data_dir / "data.db"

        # Create dummy database with some data
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE test_sessions (id INTEGER PRIMARY KEY, payload TEXT);"
        )
        for i in range(100):
            conn.execute(
                "INSERT INTO test_sessions (payload) VALUES (?);", ("x" * 1000,)
            )
        conn.commit()
        conn.close()

        # Create dummy directories
        (data_dir / "qdrant").mkdir()
        (data_dir / "qdrant" / "test_vec.bin").write_bytes(b"0" * 4096)

        (data_dir / "harness").mkdir()
        (data_dir / "harness" / "orphan_1.tmp").write_bytes(b"temp_data")

        # 1. Test Inspector
        inspector = StorageGovernanceInspector(data_dir)
        report = inspector.inspect()

        assert report.total_storage_bytes > 0
        assert len(report.categories) == 6
        sqlite_cat = next(
            c
            for c in report.categories
            if c.category == StorageCategory.SQLITE_DATABASE
        )
        assert sqlite_cat.bytes > 0
        assert "test_sessions" in sqlite_cat.details

        # 2. Test Compactor
        compactor = StateStorageCompactor(data_dir)
        comp_res = compactor.compact(
            purge_orphan_checkpoints=True, max_orphan_age_seconds=-1
        )
        assert comp_res.success is True
        assert comp_res.wal_truncated is True
        assert comp_res.purged_checkpoints >= 1


def test_state_snapshot_manager() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        db_path = data_dir / "data.db"

        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE config (k TEXT, v TEXT);")
        conn.execute("INSERT INTO config VALUES ('version', '1.0');")
        conn.commit()
        conn.close()

        mgr = StateSnapshotManager(data_dir)

        # 1. Create snapshot
        meta = mgr.create_snapshot(label="v1.0-clean")
        assert meta.snapshot_id.startswith("snap_")
        assert meta.label == "v1.0-clean"
        assert meta.size_bytes > 0
        assert len(meta.checksum) == 64

        # 2. List snapshots
        snapshots = mgr.list_snapshots()
        assert len(snapshots) == 1
        assert snapshots[0].snapshot_id == meta.snapshot_id

        # 3. Mutate DB
        conn = sqlite3.connect(str(db_path))
        conn.execute("UPDATE config SET v = '2.0-corrupted';")
        conn.commit()
        conn.close()

        # 4. Restore snapshot
        restored = mgr.restore_snapshot(meta.snapshot_id)
        assert restored is True

        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("SELECT v FROM config WHERE k = 'version';")
        row = cur.fetchone()
        conn.close()
        assert row is not None and row[0] == "1.0"

        # 5. Delete snapshot
        deleted = mgr.delete_snapshot(meta.snapshot_id)
        assert deleted is True
        assert len(mgr.list_snapshots()) == 0
