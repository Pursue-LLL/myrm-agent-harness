from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.utils.video_reader import (
    is_video_path,
    read_video_as_content_blocks,
)
from myrm_agent_harness.toolkits.llms.vision.video_analysis_engine import MAX_VIDEO_BYTES


@pytest.fixture
def mock_executor():
    executor = AsyncMock()
    return executor


class TestIsVideoPath:
    def test_video_formats(self):
        assert is_video_path("test.mp4") is True
        assert is_video_path("test.MOV") is True
        assert is_video_path("/path/to/video.webm") is True
        assert is_video_path("clip.avi") is True

    def test_non_video_formats(self):
        assert is_video_path("test.py") is False
        assert is_video_path("image.png") is False
        assert is_video_path("doc.pdf") is False


class TestReadVideoAsContentBlocks:
    @pytest.mark.asyncio
    async def test_no_vision_no_video_returns_text(self, mock_executor):
        mock_executor.read_file_bytes.return_value = b"fake_video_data"

        result = await read_video_as_content_blocks(
            "clip.mp4", mock_executor, supports_vision=False, supports_video=False
        )
        assert isinstance(result, str)
        assert "does not support vision or video" in result

    @pytest.mark.asyncio
    async def test_too_large_returns_text(self, mock_executor):
        mock_executor.read_file_bytes.return_value = b"x" * (MAX_VIDEO_BYTES + 1)

        result = await read_video_as_content_blocks(
            "large.mp4", mock_executor, supports_vision=True, supports_video=True
        )
        assert isinstance(result, str)
        assert "Exceeds" in result

    @pytest.mark.asyncio
    async def test_supports_video_returns_content_blocks(self, mock_executor):
        video_data = b"small_fake_video"
        mock_executor.read_file_bytes.return_value = video_data

        result = await read_video_as_content_blocks(
            "clip.mp4", mock_executor, supports_vision=True, supports_video=True
        )
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[1]["type"] == "image_url"
        assert "data:video/mp4;base64," in result[1]["image_url"]["url"]

    @pytest.mark.asyncio
    async def test_file_not_found_raises(self, mock_executor):
        mock_executor.read_file_bytes.side_effect = FileNotFoundError("not found")

        with pytest.raises(FileNotFoundError):
            await read_video_as_content_blocks(
                "missing.mp4", mock_executor, supports_vision=True, supports_video=True
            )

    @pytest.mark.asyncio
    async def test_read_error_returns_text(self, mock_executor):
        mock_executor.read_file_bytes.side_effect = OSError("disk error")

        result = await read_video_as_content_blocks(
            "broken.mp4", mock_executor, supports_vision=True, supports_video=True
        )
        assert isinstance(result, str)
        assert "Failed to read" in result

    @pytest.mark.asyncio
    async def test_vision_only_no_fallback_returns_text(self, mock_executor):
        mock_executor.read_file_bytes.return_value = b"fake_video"

        result = await read_video_as_content_blocks(
            "clip.mp4",
            mock_executor,
            supports_vision=True,
            supports_video=False,
            vision_fallback_model_cfg=None,
        )
        assert isinstance(result, str)
        assert "Configure a vision fallback model" in result

    @pytest.mark.asyncio
    async def test_vision_only_with_fallback_calls_engine(self, mock_executor):
        mock_executor.read_file_bytes.return_value = b"fake_video"

        fallback_cfg = MagicMock()
        fallback_cfg.model = "gpt-4o-mini"
        fallback_cfg.api_key = "test"
        fallback_cfg.base_url = None
        fallback_cfg.model_kwargs = None

        with patch(
            "myrm_agent_harness.agent.config.llm.LLMConfig.model_validate"
        ) as mock_model_validate, patch(
            "myrm_agent_harness.toolkits.llms.vision.video_analysis_engine.VideoAnalysisEngine.__init__",
            return_value=None,
        ), patch(
            "myrm_agent_harness.toolkits.llms.vision.video_analysis_engine.VideoAnalysisEngine.analyze_local_video",
            new_callable=AsyncMock,
            return_value="A cat playing",
        ):
            mock_model_validate.return_value = MagicMock()

            result = await read_video_as_content_blocks(
                "clip.mp4",
                mock_executor,
                supports_vision=True,
                supports_video=False,
                vision_fallback_model_cfg=fallback_cfg,
            )
            assert isinstance(result, str)
            assert "A cat playing" in result
            assert "[Video Analysis]" in result

    @pytest.mark.asyncio
    async def test_mime_type_detection(self, mock_executor):
        mock_executor.read_file_bytes.return_value = b"data"

        result = await read_video_as_content_blocks(
            "clip.mov", mock_executor, supports_vision=True, supports_video=True
        )
        assert isinstance(result, list)
        assert "video/quicktime" in result[1]["image_url"]["url"]
