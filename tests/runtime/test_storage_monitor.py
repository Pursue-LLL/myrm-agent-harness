"""Tests for storage monitoring."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.runtime.quota.storage_monitor import (
    get_session_storage_usage,
    get_storage_usage_gb,
    get_total_storage_usage,
)


class TestStorageMonitor:
    """Test storage monitoring utilities."""

    @pytest.fixture
    def temp_context_root(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """Create temporary context root for testing."""
        context_root = tmp_path / ".context"
        context_root.mkdir()

        # Monkeypatch CONTEXT_ROOT
        import myrm_agent_harness.runtime.quota.storage_monitor as monitor_module

        monkeypatch.setattr(monitor_module, "CONTEXT_ROOT", str(context_root))

        return context_root

    def test_get_session_storage_usage_empty(self, temp_context_root: Path) -> None:
        """Test getting storage usage for non-existent session."""
        usage = get_session_storage_usage("nonexistent")

        assert usage.total_bytes == 0
        assert usage.file_count == 0
        assert usage.compacted_files == 0
        assert usage.scratchpad_files == 0

    def test_get_session_storage_usage_with_files(self, temp_context_root: Path) -> None:
        """Test getting storage usage with files."""
        session_id = "test_session"
        session_dir = temp_context_root / session_id
        session_dir.mkdir()

        # Create compacted files
        compacted_dir = session_dir / "compacted"
        compacted_dir.mkdir()
        (compacted_dir / "file1.txt").write_text("A" * 1000)
        (compacted_dir / "file2.txt.gz").write_bytes(b"B" * 500)

        # Create scratchpad files
        scratchpad_dir = session_dir / "scratchpad"
        scratchpad_dir.mkdir()
        (scratchpad_dir / "note.txt").write_text("C" * 200)

        usage = get_session_storage_usage(session_id)

        assert usage.total_bytes == 1700
        assert usage.file_count == 3
        assert usage.compacted_files == 2
        assert usage.scratchpad_files == 1

    def test_get_total_storage_usage_empty(self, temp_context_root: Path) -> None:
        """Test getting total storage usage with no sessions."""
        usage = get_total_storage_usage()

        assert usage.total_bytes == 0
        assert usage.file_count == 0

    def test_get_total_storage_usage_multiple_sessions(self, temp_context_root: Path) -> None:
        """Test getting total storage usage across multiple sessions."""
        # Create session 1
        session1_dir = temp_context_root / "session1"
        session1_dir.mkdir()
        compacted1 = session1_dir / "compacted"
        compacted1.mkdir()
        (compacted1 / "file1.txt").write_text("A" * 1000)

        # Create session 2
        session2_dir = temp_context_root / "session2"
        session2_dir.mkdir()
        compacted2 = session2_dir / "compacted"
        compacted2.mkdir()
        (compacted2 / "file2.txt").write_text("B" * 2000)

        usage = get_total_storage_usage()

        assert usage.total_bytes == 3000
        assert usage.file_count == 2
        assert usage.compacted_files == 2
        assert usage.scratchpad_files == 0

    def test_get_total_storage_usage_skips_system_dir(self, temp_context_root: Path) -> None:
        """Test that system directory is skipped."""
        # Create system directory
        system_dir = temp_context_root / "system"
        system_dir.mkdir()
        (system_dir / "config.txt").write_text("system config")

        # Create regular session
        session_dir = temp_context_root / "session1"
        session_dir.mkdir()
        compacted = session_dir / "compacted"
        compacted.mkdir()
        (compacted / "file.txt").write_text("A" * 1000)

        usage = get_total_storage_usage()

        # Should only count session1, not system
        assert usage.total_bytes == 1000
        assert usage.file_count == 1

    def test_get_storage_usage_gb_session(self, temp_context_root: Path) -> None:
        """Test getting storage usage in GB for a session."""
        session_id = "test_session"
        session_dir = temp_context_root / session_id
        session_dir.mkdir()

        compacted_dir = session_dir / "compacted"
        compacted_dir.mkdir()

        # Create ~1MB file
        (compacted_dir / "large.txt").write_text("A" * (1024 * 1024))

        usage_gb = get_storage_usage_gb(session_id)

        # Should be approximately 1/1024 GB
        assert 0.0009 < usage_gb < 0.0011

    def test_get_storage_usage_gb_total(self, temp_context_root: Path) -> None:
        """Test getting total storage usage in GB."""
        # Create multiple sessions with files
        for i in range(3):
            session_dir = temp_context_root / f"session{i}"
            session_dir.mkdir()
            compacted = session_dir / "compacted"
            compacted.mkdir()
            (compacted / "file.txt").write_text("A" * (1024 * 1024))  # 1MB each

        usage_gb = get_storage_usage_gb()

        # Should be approximately 3/1024 GB
        assert 0.0028 < usage_gb < 0.0032

    def test_nested_directories(self, temp_context_root: Path) -> None:
        """Test that nested directories are scanned correctly."""
        session_id = "test_session"
        session_dir = temp_context_root / session_id
        session_dir.mkdir()

        # Create nested structure
        compacted_dir = session_dir / "compacted"
        compacted_dir.mkdir()
        nested_dir = compacted_dir / "nested"
        nested_dir.mkdir()
        (nested_dir / "deep_file.txt").write_text("A" * 500)

        usage = get_session_storage_usage(session_id)

        assert usage.total_bytes == 500
        assert usage.file_count == 1
        assert usage.compacted_files == 1

    def test_empty_directories_not_counted(self, temp_context_root: Path) -> None:
        """Test that empty directories don't affect counts."""
        session_id = "test_session"
        session_dir = temp_context_root / session_id
        session_dir.mkdir()

        # Create empty directories
        (session_dir / "compacted").mkdir()
        (session_dir / "scratchpad").mkdir()
        (session_dir / "compacted" / "empty_subdir").mkdir()

        usage = get_session_storage_usage(session_id)

        assert usage.total_bytes == 0
        assert usage.file_count == 0
