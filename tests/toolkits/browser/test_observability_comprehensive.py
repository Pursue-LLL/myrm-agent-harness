"""Comprehensive tests for Browser Observability"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.observability import BrowserObservability, RecordingConfig


class TestRecordingConfig:
    """测试RecordingConfig"""

    def test_default_config(self) -> None:
        """测试默认配置"""
        config = RecordingConfig()

        assert config.enabled is False
        assert config.output_dir == "./videos"
        assert config.save_on_success is False
        assert config.save_on_failure is True
        assert config.video_size == (1280, 720)

    def test_custom_config(self) -> None:
        """测试自定义配置"""
        config = RecordingConfig(
            enabled=True, output_dir="/tmp/videos", save_on_success=True, save_on_failure=False, video_size=(1920, 1080)
        )

        assert config.enabled is True
        assert config.output_dir == "/tmp/videos"
        assert config.save_on_success is True
        assert config.save_on_failure is False
        assert config.video_size == (1920, 1080)

    def test_default_disabled(self) -> None:
        """测试默认配置（未显式启用时禁用）"""
        config = RecordingConfig()
        assert config.enabled is False

    def test_explicit_enabled(self) -> None:
        """测试显式启用录制"""
        config = RecordingConfig(enabled=True)
        assert config.enabled is True

    def test_explicit_disabled(self) -> None:
        """测试显式禁用录制"""
        config = RecordingConfig(enabled=False)
        assert config.enabled is False

    def test_custom_dir(self) -> None:
        """测试自定义输出目录"""
        config = RecordingConfig(output_dir="/custom/path")
        assert config.output_dir == "/custom/path"

    def test_save_on_success(self) -> None:
        """测试配置保存成功录制"""
        config = RecordingConfig(save_on_success=True)
        assert config.save_on_success is True

    def test_not_save_on_failure(self) -> None:
        """测试配置不保存失败录制"""
        config = RecordingConfig(save_on_failure=False)
        assert config.save_on_failure is False


class TestBrowserObservability:
    """测试BrowserObservability"""

    def test_init_defaults(self) -> None:
        """测试默认初始化"""
        config = RecordingConfig()
        obs = BrowserObservability(config)

        assert obs.recording_enabled is False
        assert obs.video_path is None
        assert obs._task_succeeded is True

    def test_init_with_progress_callback(self) -> None:
        """测试带进度回调的初始化"""
        config = RecordingConfig()
        callback = AsyncMock()
        obs = BrowserObservability(config, progress_callback=callback)

        assert obs._progress_callback is callback

    def test_recording_enabled_property(self) -> None:
        """测试recording_enabled属性"""
        config_disabled = RecordingConfig(enabled=False)
        obs_disabled = BrowserObservability(config_disabled)
        assert obs_disabled.recording_enabled is False

        config_enabled = RecordingConfig(enabled=True)
        obs_enabled = BrowserObservability(config_enabled)
        assert obs_enabled.recording_enabled is True

    def test_video_path_property(self) -> None:
        """测试video_path属性"""
        config = RecordingConfig()
        obs = BrowserObservability(config)

        assert obs.video_path is None

        obs._video_path = Path("/tmp/test.webm")
        assert obs.video_path == Path("/tmp/test.webm")

    def test_get_context_kwargs_disabled(self) -> None:
        """测试录制禁用时返回空kwargs"""
        config = RecordingConfig(enabled=False)
        obs = BrowserObservability(config)

        kwargs = obs.get_context_kwargs()

        assert kwargs == {}

    def test_get_context_kwargs_enabled(self, tmp_path: Path) -> None:
        """测试录制启用时返回录制参数"""
        config = RecordingConfig(enabled=True, output_dir=str(tmp_path), video_size=(1920, 1080))
        obs = BrowserObservability(config)

        kwargs = obs.get_context_kwargs()

        assert "record_video_dir" in kwargs
        assert kwargs["record_video_dir"] == str(tmp_path)
        assert kwargs["record_video_size"] == {"width": 1920, "height": 1080}
        assert tmp_path.exists()

    @pytest.mark.asyncio
    async def test_notify_progress_with_callback(self) -> None:
        """测试进度通知调用回调"""
        config = RecordingConfig()
        callback = AsyncMock()
        obs = BrowserObservability(config, progress_callback=callback)

        await obs.notify_progress("Step 1/3: Navigate")

        callback.assert_called_once_with("Step 1/3: Navigate")

    @pytest.mark.asyncio
    async def test_notify_progress_without_callback(self) -> None:
        """测试无回调时进度通知不报错"""
        config = RecordingConfig()
        obs = BrowserObservability(config)

        await obs.notify_progress("Test message")

    @pytest.mark.asyncio
    async def test_notify_progress_callback_exception(self) -> None:
        """测试回调异常被捕获和记录"""
        config = RecordingConfig()
        callback = AsyncMock(side_effect=RuntimeError("Callback failed"))
        obs = BrowserObservability(config, progress_callback=callback)

        with patch("myrm_agent_harness.toolkits.browser.observability.logger") as mock_logger:
            await obs.notify_progress("Test")

            mock_logger.warning.assert_called_once()
            assert "Progress callback failed" in str(mock_logger.warning.call_args)

    def test_mark_task_status(self) -> None:
        """测试标记任务状态"""
        config = RecordingConfig()
        obs = BrowserObservability(config)

        assert obs._task_succeeded is True

        obs.mark_task_status(False)
        assert obs._task_succeeded is False

        obs.mark_task_status(True)
        assert obs._task_succeeded is True

    def test_cleanup_recording_disabled(self) -> None:
        """测试录制禁用时cleanup不做任何操作"""
        config = RecordingConfig(enabled=False)
        obs = BrowserObservability(config)

        obs.cleanup_recording()

        assert obs.video_path is None

    def test_cleanup_recording_no_output_dir(self) -> None:
        """测试输出目录不存在时cleanup返回"""
        config = RecordingConfig(enabled=True, output_dir="/nonexistent/path")
        obs = BrowserObservability(config)

        obs.cleanup_recording()

        assert obs.video_path is None

    def test_cleanup_recording_no_video_files(self, tmp_path: Path) -> None:
        """测试没有视频文件时记录警告"""
        config = RecordingConfig(enabled=True, output_dir=str(tmp_path))
        obs = BrowserObservability(config)

        with patch("myrm_agent_harness.toolkits.browser.observability.logger") as mock_logger:
            obs.cleanup_recording()

            mock_logger.warning.assert_called_once()
            assert "no video file found" in str(mock_logger.warning.call_args)

    def test_cleanup_recording_save_on_success(self, tmp_path: Path) -> None:
        """测试成功时保存录制"""
        video_file = tmp_path / "test.webm"
        video_file.write_text("fake video")

        config = RecordingConfig(enabled=True, output_dir=str(tmp_path), save_on_success=True)
        obs = BrowserObservability(config)
        obs.mark_task_status(True)

        obs.cleanup_recording()

        assert video_file.exists()
        assert obs.video_path == video_file

    def test_cleanup_recording_delete_on_success(self, tmp_path: Path) -> None:
        """测试成功时删除录制"""
        video_file = tmp_path / "test.webm"
        video_file.write_text("fake video")

        config = RecordingConfig(enabled=True, output_dir=str(tmp_path), save_on_success=False)
        obs = BrowserObservability(config)
        obs.mark_task_status(True)

        obs.cleanup_recording()

        assert not video_file.exists()
        assert obs.video_path is None

    def test_cleanup_recording_save_on_failure(self, tmp_path: Path) -> None:
        """测试失败时保存录制"""
        video_file = tmp_path / "test.webm"
        video_file.write_text("fake video")

        config = RecordingConfig(enabled=True, output_dir=str(tmp_path), save_on_failure=True)
        obs = BrowserObservability(config)
        obs.mark_task_status(False)

        obs.cleanup_recording()

        assert video_file.exists()
        assert obs.video_path == video_file

    def test_cleanup_recording_delete_failure_exception(self, tmp_path: Path) -> None:
        """测试删除录制失败时记录警告"""
        video_file = tmp_path / "test.webm"
        video_file.write_text("fake video")

        config = RecordingConfig(enabled=True, output_dir=str(tmp_path), save_on_failure=False)
        obs = BrowserObservability(config)
        obs.mark_task_status(False)

        with patch.object(Path, "unlink", side_effect=OSError("Permission denied")):
            with patch("myrm_agent_harness.toolkits.browser.observability.logger") as mock_logger:
                obs.cleanup_recording()

                mock_logger.warning.assert_called()
                assert "Failed to delete recording" in str(mock_logger.warning.call_args)

    def test_cleanup_recording_multiple_videos_selects_newest(self, tmp_path: Path) -> None:
        """测试多个视频文件时选择最新的"""
        old_video = tmp_path / "old.webm"
        old_video.write_text("old")

        import time

        time.sleep(0.01)

        new_video = tmp_path / "new.webm"
        new_video.write_text("new")

        config = RecordingConfig(enabled=True, output_dir=str(tmp_path), save_on_success=True)
        obs = BrowserObservability(config)
        obs.mark_task_status(True)

        obs.cleanup_recording()

        assert obs.video_path == new_video
