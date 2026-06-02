"""Unit tests for RecordingManager."""

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.recording_manager import (
    FileManager,
    RecordingManager,
    RecordingState,
)


class TestRecordingState:
    """Test RecordingState dataclass."""

    def test_default_state(self):
        """Test default RecordingState initialization."""
        state = RecordingState()
        assert state.active is False
        assert state.output_path is None
        assert state.start_time is None

    def test_active_state(self):
        """Test RecordingState with active recording."""
        now = datetime.now()
        path = Path("/tmp/test.zip")
        state = RecordingState(active=True, output_path=path, start_time=now)
        assert state.active is True
        assert state.output_path == path
        assert state.start_time == now


class TestFileManager:
    """Test FileManager."""

    def test_generate_filename(self, tmp_path):
        """Test filename generation with timestamp."""
        manager = FileManager(tmp_path, max_files=5)
        filename = manager.generate_filename("trace", "zip")

        assert filename.parent == tmp_path
        assert filename.name.startswith("trace-")
        assert filename.suffix == ".zip"
        assert len(filename.stem.split("-")) == 3  # trace-YYYYMMDD-HHMMSS

    def test_cleanup_old_files(self, tmp_path):
        """Test automatic cleanup of old files."""
        manager = FileManager(tmp_path, max_files=3)

        # Create 5 test files with different timestamps
        for i in range(5):
            test_file = tmp_path / f"trace-2024010{i}-120000.zip"
            test_file.touch()

        # Cleanup should keep only 3 newest files
        manager.cleanup_old_files("trace-*.zip")

        remaining_files = list(tmp_path.glob("trace-*.zip"))
        assert len(remaining_files) == 3

    def test_cleanup_with_no_files(self, tmp_path):
        """Test cleanup when no files exist."""
        manager = FileManager(tmp_path, max_files=3)
        manager.cleanup_old_files("trace-*.zip")  # Should not raise

    def test_cleanup_with_fewer_files_than_max(self, tmp_path):
        """Test cleanup when file count is below max."""
        manager = FileManager(tmp_path, max_files=5)

        # Create only 2 files
        for i in range(2):
            test_file = tmp_path / f"trace-2024010{i}-120000.zip"
            test_file.touch()

        manager.cleanup_old_files("trace-*.zip")

        remaining_files = list(tmp_path.glob("trace-*.zip"))
        assert len(remaining_files) == 2  # All files should remain


class TestRecordingManager:
    """Test RecordingManager."""

    @pytest.fixture
    def manager(self, tmp_path):
        """Create RecordingManager with temp directory."""
        return RecordingManager(base_dir=tmp_path, max_files=5)

    @pytest.fixture
    def mock_context(self):
        """Create mock BrowserContext."""
        context = MagicMock()
        context.tracing = MagicMock()
        context.tracing.start = AsyncMock()
        context.tracing.stop = AsyncMock()
        return context

    @pytest.fixture
    def mock_page(self):
        """Create mock Page."""
        page = MagicMock()
        page.route_from_har = AsyncMock()
        page.unroute_all = AsyncMock()
        return page

    async def test_start_trace_success(self, manager, mock_context):
        """Test successful trace start."""
        result = await manager.start_trace(mock_context)

        assert "started successfully" in result.lower()
        assert manager.trace_active is True
        mock_context.tracing.start.assert_called_once_with(screenshots=True, snapshots=True, sources=True)

    async def test_start_trace_already_active(self, manager, mock_context):
        """Test starting trace when already active."""
        await manager.start_trace(mock_context)

        with pytest.raises(RuntimeError, match="already active"):
            await manager.start_trace(mock_context)

    async def test_stop_trace_success(self, manager, mock_context):
        """Test successful trace stop."""
        await manager.start_trace(mock_context)
        output_path = await manager.stop_trace(mock_context)

        assert output_path.exists() is False  # File not created in test
        assert output_path.name.startswith("trace-")
        assert output_path.suffix == ".zip"
        assert manager.trace_active is False
        mock_context.tracing.stop.assert_called_once()

    async def test_stop_trace_not_active(self, manager, mock_context):
        """Test stopping trace when not active."""
        with pytest.raises(RuntimeError, match="No active trace"):
            await manager.stop_trace(mock_context)

    async def test_start_har_success(self, manager, mock_page):
        """Test successful HAR start."""
        result = await manager.start_har(mock_page)

        assert "started successfully" in result.lower()
        assert manager.har_active is True
        mock_page.route_from_har.assert_called_once()

    async def test_start_har_already_active(self, manager, mock_page):
        """Test starting HAR when already active."""
        await manager.start_har(mock_page)

        with pytest.raises(RuntimeError, match="already active"):
            await manager.start_har(mock_page)

    async def test_stop_har_success(self, manager, mock_page):
        """Test successful HAR stop."""
        await manager.start_har(mock_page)
        output_path = await manager.stop_har(mock_page)

        assert output_path.name.startswith("har-")
        assert output_path.suffix == ".har"
        assert manager.har_active is False
        mock_page.unroute_all.assert_called_once_with(behavior="wait")

    async def test_stop_har_not_active(self, manager, mock_page):
        """Test stopping HAR when not active."""
        with pytest.raises(RuntimeError, match="No active HAR"):
            await manager.stop_har(mock_page)

    def test_get_status_no_recordings(self, manager):
        """Test status when no recordings active."""
        status = manager.get_status()

        assert status["trace"]["active"] is False
        assert status["trace"]["output_path"] is None
        assert status["har"]["active"] is False
        assert status["har"]["output_path"] is None

    async def test_get_status_with_active_trace(self, manager, mock_context):
        """Test status with active trace recording."""
        await manager.start_trace(mock_context)
        status = manager.get_status()

        assert status["trace"]["active"] is True
        assert status["trace"]["start_time"] is not None
        assert status["har"]["active"] is False

    async def test_trace_output_path_property(self, manager, mock_context):
        """Test trace_output_path property."""
        assert manager.trace_output_path is None

        await manager.start_trace(mock_context)
        await manager.stop_trace(mock_context)

        assert manager.trace_output_path is not None
        assert manager.trace_output_path.name.startswith("trace-")

    async def test_har_output_path_property(self, manager, mock_page):
        """Test har_output_path property."""
        assert manager.har_output_path is None

        await manager.start_har(mock_page)
        await manager.stop_har(mock_page)

        assert manager.har_output_path is not None
        assert manager.har_output_path.name.startswith("har-")

    async def test_concurrent_trace_and_har(self, manager, mock_context, mock_page):
        """Test running trace and HAR simultaneously."""
        await manager.start_trace(mock_context)
        await manager.start_har(mock_page)

        assert manager.trace_active is True
        assert manager.har_active is True

        await manager.stop_trace(mock_context)
        await manager.stop_har(mock_page)

        assert manager.trace_active is False
        assert manager.har_active is False
