"""Unit tests for file_snapshot.restore_inbox module."""

import time

import pytest

from myrm_agent_harness.agent.file_snapshot.restore_inbox import (
    RestoreNotification,
    _pending,
    drain_restore_notifications,
    push_restore_notification,
)


@pytest.fixture(autouse=True)
def _clear_pending():
    """Ensure inbox is empty between tests."""
    _pending.clear()
    yield
    _pending.clear()


class TestPushRestoreNotification:
    def test_push_single(self):
        push_restore_notification(snapshot_id="abc123def456", files_restored=3)
        assert len(_pending) == 1
        notif = _pending[0]
        assert notif.snapshot_id == "abc123def456"
        assert notif.files_restored == 3
        assert notif.restored_files is None
        assert notif.timestamp > 0

    def test_push_with_files(self):
        push_restore_notification(
            snapshot_id="xyz789",
            files_restored=2,
            restored_files=["config.py", "main.py"],
        )
        assert _pending[0].restored_files == ["config.py", "main.py"]

    def test_push_multiple(self):
        push_restore_notification(snapshot_id="snap1", files_restored=1)
        push_restore_notification(snapshot_id="snap2", files_restored=2)
        assert len(_pending) == 2


class TestDrainRestoreNotifications:
    def test_drain_empty(self):
        assert drain_restore_notifications() is None

    def test_drain_single_full_restore(self):
        push_restore_notification(snapshot_id="abcdef1234567890", files_restored=5)
        result = drain_restore_notifications()
        assert result is not None
        assert "Entire workspace (5 files) restored" in result
        assert "abcdef12" in result
        assert "Re-read any files" in result
        assert len(_pending) == 0

    def test_drain_single_partial_restore(self):
        push_restore_notification(
            snapshot_id="abcdef1234567890",
            files_restored=2,
            restored_files=["config.py", "app.py"],
        )
        result = drain_restore_notifications()
        assert result is not None
        assert "2 file(s) restored" in result
        assert "config.py, app.py" in result
        assert "Re-read any files" in result

    def test_drain_truncates_large_file_list(self):
        files = [f"file_{i}.py" for i in range(15)]
        push_restore_notification(
            snapshot_id="abcdef1234567890",
            files_restored=15,
            restored_files=files,
        )
        result = drain_restore_notifications()
        assert result is not None
        assert "(+5 more)" in result

    def test_drain_expired_notification(self):
        notif = RestoreNotification(
            snapshot_id="old_snap",
            files_restored=1,
            restored_files=None,
            timestamp=time.time() - 700,  # Expired (TTL is 600s)
        )
        _pending.append(notif)
        assert drain_restore_notifications() is None

    def test_drain_mixed_fresh_and_expired(self):
        expired = RestoreNotification(
            snapshot_id="old_snap",
            files_restored=1,
            restored_files=None,
            timestamp=time.time() - 700,
        )
        _pending.append(expired)
        push_restore_notification(snapshot_id="fresh_snap_1234", files_restored=2)
        result = drain_restore_notifications()
        assert result is not None
        assert "fresh_sn" in result
        assert "old_snap" not in result

    def test_drain_multiple(self):
        push_restore_notification(snapshot_id="snap1111111111", files_restored=1)
        push_restore_notification(snapshot_id="snap2222222222", files_restored=3)
        result = drain_restore_notifications()
        assert result is not None
        assert "snap1111" in result
        assert "snap2222" in result
        assert len(_pending) == 0

    def test_drain_clears_queue(self):
        push_restore_notification(snapshot_id="test_snap_1234", files_restored=1)
        drain_restore_notifications()
        assert drain_restore_notifications() is None
