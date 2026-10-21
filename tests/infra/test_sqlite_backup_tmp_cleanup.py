"""Tests for the temporary-image lifecycle of SQLiteBackupManager.create_backup.

A backup is written to ``.tmp-<id>.sqlite`` and published only after verification. A failed or interrupted
run must not leave that image behind, and images abandoned by a killed process are reclaimed by the next run.
"""

import os
import sqlite3
import time
from pathlib import Path

import pytest

from myrm_agent_harness.infra import sqlite_backup
from myrm_agent_harness.infra.sqlite_backup import SQLiteBackupManager
from myrm_agent_harness.infra.sqlite_backup_models import (
    _SQLITE_SIDECAR_SUFFIXES,
    _STALE_TMP_SECONDS,
    _discard_on_failure,
    _require_backup_image,
    _sweep_stale_tmp_backups,
)

_IDLE_SECONDS = _STALE_TMP_SECONDS + 60


def _create_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, data TEXT)")
    conn.executemany("INSERT INTO items (data) VALUES (?)", [(f"row-{i}",) for i in range(20)])
    conn.commit()
    conn.close()


def _age(path: Path, seconds: float) -> None:
    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp))


def _names(directory: Path) -> set[str]:
    return {entry.name for entry in directory.iterdir()}


def _image_with_sidecars(directory: Path) -> Path:
    image = directory / ".tmp-1.sqlite"
    image.write_bytes(b"x" * 100)
    for suffix in _SQLITE_SIDECAR_SUFFIXES:
        Path(f"{image}{suffix}").write_bytes(b"y")
    return image


class TestDiscardOnFailure:
    def test_failure_removes_image_and_sidecars_and_reraises(self, tmp_path: Path) -> None:
        image = _image_with_sidecars(tmp_path)
        with pytest.raises(OSError, match="disk full"), _discard_on_failure(image):
            raise OSError("disk full")
        assert _names(tmp_path) == set()

    def test_interrupt_is_cleaned_up_too(self, tmp_path: Path) -> None:
        image = _image_with_sidecars(tmp_path)
        with pytest.raises(KeyboardInterrupt), _discard_on_failure(image):
            raise KeyboardInterrupt
        assert _names(tmp_path) == set()

    def test_success_keeps_the_image(self, tmp_path: Path) -> None:
        image = _image_with_sidecars(tmp_path)
        with _discard_on_failure(image):
            pass
        assert image.exists()

    def test_image_that_was_never_created_does_not_mask_the_error(self, tmp_path: Path) -> None:
        with pytest.raises(RuntimeError, match="copy failed"), _discard_on_failure(tmp_path / ".tmp-9.sqlite"):
            raise RuntimeError("copy failed")


class TestRequireBackupImage:
    def test_missing_image_fails_without_creating_one(self, tmp_path: Path) -> None:
        image = tmp_path / ".tmp-1.sqlite"
        with pytest.raises(RuntimeError, match="missing or empty"):
            _require_backup_image(image)
        assert not image.exists()

    def test_empty_image_fails(self, tmp_path: Path) -> None:
        image = tmp_path / ".tmp-1.sqlite"
        image.touch()
        with pytest.raises(RuntimeError, match="missing or empty"):
            _require_backup_image(image)

    def test_populated_image_passes(self, tmp_path: Path) -> None:
        image = tmp_path / ".tmp-1.sqlite"
        image.write_bytes(b"x")
        _require_backup_image(image)


class TestSweepStaleTmpBackups:
    def test_removes_only_idle_temporary_files(self, tmp_path: Path) -> None:
        idle_image = tmp_path / ".tmp-1.sqlite"
        idle_sidecar = tmp_path / ".tmp-1.sqlite-wal"
        live_image = tmp_path / ".tmp-2.sqlite"
        published = tmp_path / "backup-3.sqlite"
        unrelated = tmp_path / "notes.txt"
        for path in (idle_image, idle_sidecar, live_image, published, unrelated):
            path.write_bytes(b"data")
        for path in (idle_image, idle_sidecar, published, unrelated):
            _age(path, _IDLE_SECONDS)

        assert _sweep_stale_tmp_backups(tmp_path) == 2
        assert _names(tmp_path) == {".tmp-2.sqlite", "backup-3.sqlite", "notes.txt"}

    def test_missing_directory_is_a_noop(self, tmp_path: Path) -> None:
        assert _sweep_stale_tmp_backups(tmp_path / "absent") == 0

    @pytest.mark.skipif(os.utime not in os.supports_follow_symlinks, reason="needs lutimes support")
    def test_symlinks_are_never_followed_or_removed(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside.sqlite"
        outside.write_bytes(b"keep")
        snapshots = tmp_path / "snapshots"
        snapshots.mkdir()
        link = snapshots / ".tmp-1.sqlite"
        link.symlink_to(outside)
        stamp = time.time() - _IDLE_SECONDS
        os.utime(link, (stamp, stamp), follow_symlinks=False)

        assert _sweep_stale_tmp_backups(snapshots) == 0
        assert link.is_symlink()
        assert outside.read_bytes() == b"keep"


class TestCreateBackupCleanup:
    @staticmethod
    def _manager(tmp_path: Path) -> tuple[SQLiteBackupManager, Path]:
        db_path = tmp_path / "app.db"
        _create_db(db_path)
        backup_dir = tmp_path / "backups"
        return SQLiteBackupManager(db_path, backup_dir), backup_dir / "snapshots"

    @pytest.mark.parametrize("failure", [OSError("disk full"), KeyboardInterrupt()])
    def test_failure_after_the_copy_leaves_no_temporary_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: BaseException
    ) -> None:
        manager, snapshots = self._manager(tmp_path)

        def explode(path: Path) -> str:
            Path(f"{path}-journal").write_bytes(b"j")  # what an interrupted connection leaves beside the image
            raise failure

        monkeypatch.setattr(sqlite_backup, "_compute_sha256", explode)

        with pytest.raises(type(failure)):
            manager.create_backup()
        assert _names(snapshots) == set()

    def test_failed_verification_leaves_no_temporary_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager, snapshots = self._manager(tmp_path)
        monkeypatch.setattr(sqlite_backup, "_pragma_quick_check", lambda _path: "database disk image is malformed")

        with pytest.raises(RuntimeError, match="quick_check"):
            manager.create_backup()
        assert _names(snapshots) == set()

    def test_abandoned_images_are_reclaimed_by_the_next_backup(self, tmp_path: Path) -> None:
        manager, snapshots = self._manager(tmp_path)
        snapshots.mkdir(parents=True)
        for name in (".tmp-1700000000000.sqlite", ".tmp-1700000000000.sqlite-wal"):
            orphan = snapshots / name
            orphan.write_bytes(b"partial copy")
            _age(orphan, _IDLE_SECONDS)

        record = manager.create_backup()

        assert _names(snapshots) == {record.file_name}

    def test_image_of_a_backup_in_flight_is_left_alone(self, tmp_path: Path) -> None:
        manager, snapshots = self._manager(tmp_path)
        snapshots.mkdir(parents=True)
        in_flight = snapshots / ".tmp-9999999999999.sqlite"
        in_flight.write_bytes(b"being written")

        record = manager.create_backup()

        assert _names(snapshots) == {record.file_name, in_flight.name}
