"""Unit tests for browser observability module."""

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.browser.observability import (
    BrowserObservability,
    RecordingConfig,
)


class TestRecordingConfig:
    """Test RecordingConfig class."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = RecordingConfig()

        assert config.enabled is False
        assert config.output_dir == "./videos"
        assert config.save_on_success is False
        assert config.save_on_failure is True
        assert config.video_size == (1280, 720)

    def test_custom_config(self) -> None:
        """Test custom configuration."""
        config = RecordingConfig(
            enabled=True,
            output_dir="/tmp/recordings",
            save_on_success=True,
            save_on_failure=False,
            video_size=(1920, 1080),
        )

        assert config.enabled is True
        assert config.output_dir == "/tmp/recordings"
        assert config.save_on_success is True
        assert config.save_on_failure is False
        assert config.video_size == (1920, 1080)

    def test_default_disabled(self) -> None:
        """Test configuration without explicit enable (disabled by default)."""
        config = RecordingConfig()
        assert config.enabled is False

    def test_explicit_enable(self) -> None:
        """Test explicit enable via parameter."""
        config = RecordingConfig(enabled=True)
        assert config.enabled is True

    def test_custom_dir(self) -> None:
        """Test custom output directory."""
        config = RecordingConfig(output_dir="/custom/path")
        assert config.output_dir == "/custom/path"


class TestBrowserObservability:
    """Test BrowserObservability class."""

    def test_initialization(self) -> None:
        """Test observability initialization."""
        config = RecordingConfig(enabled=True)
        obs = BrowserObservability(recording_config=config)

        assert obs.recording_enabled is True
        assert obs.video_path is None

    def test_recording_disabled(self) -> None:
        """Test observability with recording disabled."""
        config = RecordingConfig(enabled=False)
        obs = BrowserObservability(recording_config=config)

        assert obs.recording_enabled is False

        # get_context_kwargs should return empty dict when disabled
        kwargs = obs.get_context_kwargs()
        assert kwargs == {}

    def test_get_context_kwargs_enabled(self, tmp_path: Path) -> None:
        """Test context kwargs when recording is enabled."""
        output_dir = str(tmp_path / "videos")
        config = RecordingConfig(
            enabled=True,
            output_dir=output_dir,
            video_size=(1920, 1080),
        )
        obs = BrowserObservability(recording_config=config)

        kwargs = obs.get_context_kwargs()

        assert "record_video_dir" in kwargs
        assert kwargs["record_video_dir"] == output_dir
        assert "record_video_size" in kwargs
        assert kwargs["record_video_size"] == {"width": 1920, "height": 1080}

        # Verify directory was created
        assert Path(output_dir).exists()

    @pytest.mark.asyncio
    async def test_progress_notification(self) -> None:
        """Test progress notification callback."""
        messages: list[str] = []

        async def callback(msg: str) -> None:
            messages.append(msg)

        config = RecordingConfig(enabled=False)
        obs = BrowserObservability(
            recording_config=config,
            progress_callback=callback,
        )

        await obs.notify_progress("Step 1")
        await obs.notify_progress("Step 2")

        assert messages == ["Step 1", "Step 2"]

    @pytest.mark.asyncio
    async def test_progress_notification_no_callback(self) -> None:
        """Test progress notification without callback (should not crash)."""
        config = RecordingConfig(enabled=False)
        obs = BrowserObservability(recording_config=config)

        # Should not raise
        await obs.notify_progress("Test message")

    @pytest.mark.asyncio
    async def test_progress_callback_error_handling(self) -> None:
        """Test progress callback error handling."""

        async def failing_callback(msg: str) -> None:
            raise RuntimeError("Callback failed")

        config = RecordingConfig(enabled=False)
        obs = BrowserObservability(
            recording_config=config,
            progress_callback=failing_callback,
        )

        # Should not raise (error is logged)
        await obs.notify_progress("Test")

    def test_mark_task_status(self) -> None:
        """Test marking task status."""
        config = RecordingConfig(enabled=True)
        obs = BrowserObservability(recording_config=config)

        # Default is success
        assert obs._task_succeeded is True

        # Mark as failure
        obs.mark_task_status(success=False)
        assert obs._task_succeeded is False

        # Mark as success
        obs.mark_task_status(success=True)
        assert obs._task_succeeded is True

    def test_cleanup_recording_disabled(self) -> None:
        """Test cleanup_recording when recording is disabled."""
        config = RecordingConfig(enabled=False)
        obs = BrowserObservability(recording_config=config)

        # Should be a no-op
        obs.cleanup_recording()
        assert obs.video_path is None

    def test_cleanup_recording_save_on_failure(self, tmp_path: Path) -> None:
        """Test cleanup_recording saves recording on failure."""
        output_dir = tmp_path / "videos"
        output_dir.mkdir()

        # Create a fake video file
        video_file = output_dir / "test-video.webm"
        video_file.write_text("fake video content")

        config = RecordingConfig(
            enabled=True,
            output_dir=str(output_dir),
            save_on_success=False,
            save_on_failure=True,
        )
        obs = BrowserObservability(recording_config=config)
        obs.mark_task_status(success=False)

        obs.cleanup_recording()

        # Video should be kept
        assert video_file.exists()
        assert obs.video_path == video_file

    def test_cleanup_recording_delete_on_success(self, tmp_path: Path) -> None:
        """Test cleanup_recording deletes recording on success."""
        output_dir = tmp_path / "videos"
        output_dir.mkdir()

        # Create a fake video file
        video_file = output_dir / "test-video.webm"
        video_file.write_text("fake video content")

        config = RecordingConfig(
            enabled=True,
            output_dir=str(output_dir),
            save_on_success=False,
            save_on_failure=True,
        )
        obs = BrowserObservability(recording_config=config)
        obs.mark_task_status(success=True)

        obs.cleanup_recording()

        # Video should be deleted
        assert not video_file.exists()
        assert obs.video_path is None
