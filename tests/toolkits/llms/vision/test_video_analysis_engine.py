import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.config.llm import LLMConfig
from myrm_agent_harness.toolkits.llms.vision.video_analysis_engine import (
    MAX_VIDEO_BYTES,
    VIDEO_EXTENSIONS,
    VIDEO_MIME_TYPES,
    VideoAnalysisEngine,
    _has_ffmpeg,
    is_video_path,
)


@pytest.fixture
def mock_llm_config():
    return LLMConfig(model="gpt-4o-mini", api_key="test-key")


@pytest.fixture
def video_engine(mock_llm_config):
    with patch(
        "myrm_agent_harness.toolkits.llms.vision.video_analysis_engine.create_litellm_model"
    ) as mock_create:
        mock_model = AsyncMock()
        mock_create.return_value = mock_model
        engine = VideoAnalysisEngine(mock_llm_config)
        engine.model = mock_model
        yield engine


class TestIsVideoPath:
    def test_mp4(self):
        assert is_video_path("video.mp4") is True

    def test_mov(self):
        assert is_video_path("/path/to/clip.MOV") is True

    def test_webm(self):
        assert is_video_path("recording.webm") is True

    def test_non_video(self):
        assert is_video_path("image.png") is False

    def test_no_extension(self):
        assert is_video_path("noext") is False

    def test_txt(self):
        assert is_video_path("readme.txt") is False


class TestVideoExtensions:
    def test_all_extensions_have_mime(self):
        for ext in VIDEO_EXTENSIONS:
            assert ext in VIDEO_MIME_TYPES, f"Missing MIME for {ext}"

    def test_common_formats_present(self):
        assert ".mp4" in VIDEO_EXTENSIONS
        assert ".mov" in VIDEO_EXTENSIONS
        assert ".webm" in VIDEO_EXTENSIONS
        assert ".avi" in VIDEO_EXTENSIONS


class TestVideoAnalysisEngineDirectAnalyze:
    @pytest.mark.asyncio
    async def test_direct_analyze_success(self, video_engine):
        mock_response = MagicMock()
        mock_response.content = "Video shows a cat playing"
        video_engine.model.ainvoke.return_value = mock_response

        result = await video_engine.analyze_video_b64(
            "dummyb64data", "video/mp4", supports_video=True
        )
        assert result == "Video shows a cat playing"
        video_engine.model.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_direct_analyze_exception(self, video_engine):
        video_engine.model.ainvoke.side_effect = Exception("API Error")

        result = await video_engine.analyze_video_b64(
            "dummyb64data", "video/mp4", supports_video=True
        )
        assert "[Video Analysis Failed:" in result

    @pytest.mark.asyncio
    async def test_analyze_video_url_supported(self, video_engine):
        mock_response = MagicMock()
        mock_response.content = "A lecture video"
        video_engine.model.ainvoke.return_value = mock_response

        result = await video_engine.analyze_video_url(
            "https://example.com/video.mp4", supports_video=True
        )
        assert result == "A lecture video"

    @pytest.mark.asyncio
    async def test_analyze_video_url_not_supported(self, video_engine):
        result = await video_engine.analyze_video_url(
            "https://example.com/video.mp4", supports_video=False
        )
        assert "requires a video-capable model" in result


class TestVideoAnalysisEngineFrameExtraction:
    @pytest.mark.asyncio
    async def test_frame_extraction_no_ffmpeg(self, video_engine):
        with patch(
            "myrm_agent_harness.toolkits.llms.vision.video_analysis_engine._has_ffmpeg",
            return_value=False,
        ):
            result = await video_engine.analyze_video_b64(
                "dummyb64", "video/mp4", supports_video=False
            )
            assert "ffmpeg is not installed" in result

    @pytest.mark.asyncio
    async def test_frame_extraction_success(self, video_engine):
        mock_response = MagicMock()
        mock_response.content = "Frame analysis: person walking"
        video_engine.model.ainvoke.return_value = mock_response

        fake_frame = b"\xff\xd8\xff\xe0" + b"\x00" * 100  # fake JPEG header
        with patch(
            "myrm_agent_harness.toolkits.llms.vision.video_analysis_engine._has_ffmpeg",
            return_value=True,
        ), patch(
            "myrm_agent_harness.toolkits.llms.vision.video_analysis_engine._extract_frames_ffmpeg",
            new_callable=AsyncMock,
            return_value=[(fake_frame, "image/jpeg"), (fake_frame, "image/jpeg")],
        ):
            result = await video_engine.analyze_video_b64(
                base64.b64encode(b"fake_video_data").decode(),
                "video/mp4",
                supports_video=False,
            )
            assert result == "Frame analysis: person walking"

    @pytest.mark.asyncio
    async def test_frame_extraction_empty_frames(self, video_engine):
        with patch(
            "myrm_agent_harness.toolkits.llms.vision.video_analysis_engine._has_ffmpeg",
            return_value=True,
        ), patch(
            "myrm_agent_harness.toolkits.llms.vision.video_analysis_engine._extract_frames_ffmpeg",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await video_engine.analyze_video_b64(
                base64.b64encode(b"fake_video").decode(),
                "video/mp4",
                supports_video=False,
            )
            assert "No frames could be extracted" in result


class TestVideoAnalysisEngineLocalVideo:
    @pytest.mark.asyncio
    async def test_local_video_too_large(self, video_engine):
        mock_executor = AsyncMock()
        mock_executor.read_file_bytes.return_value = b"x" * (MAX_VIDEO_BYTES + 1)

        result = await video_engine.analyze_local_video(
            "/path/video.mp4", mock_executor, supports_video=True
        )
        assert "Video too large" in result

    @pytest.mark.asyncio
    async def test_local_video_read_error(self, video_engine):
        mock_executor = AsyncMock()
        mock_executor.read_file_bytes.side_effect = OSError("Permission denied")

        result = await video_engine.analyze_local_video(
            "/path/video.mp4", mock_executor, supports_video=True
        )
        assert "Failed to read video" in result

    @pytest.mark.asyncio
    async def test_local_video_direct_success(self, video_engine):
        mock_executor = AsyncMock()
        mock_executor.read_file_bytes.return_value = b"fake_video_bytes"

        mock_response = MagicMock()
        mock_response.content = "Video content described"
        video_engine.model.ainvoke.return_value = mock_response

        result = await video_engine.analyze_local_video(
            "/path/video.mp4", mock_executor, supports_video=True
        )
        assert result == "Video content described"

    @pytest.mark.asyncio
    async def test_local_video_no_ffmpeg_no_support(self, video_engine):
        mock_executor = AsyncMock()
        mock_executor.read_file_bytes.return_value = b"fake"

        with patch(
            "myrm_agent_harness.toolkits.llms.vision.video_analysis_engine._has_ffmpeg",
            return_value=False,
        ):
            result = await video_engine.analyze_local_video(
                "/path/video.mp4", mock_executor, supports_video=False
            )
            assert "ffmpeg is not installed" in result


class TestMaxVideoBytes:
    def test_limit_is_100mb(self):
        assert MAX_VIDEO_BYTES == 100 * 1024 * 1024


class TestHasFfmpeg:
    def test_returns_true_when_binary_present(self):
        with patch("myrm_agent_harness.toolkits.llms.vision.video_analysis_engine.shutil.which", return_value="/usr/bin/ffmpeg"):
            assert _has_ffmpeg() is True

    def test_returns_false_when_missing(self):
        with patch("myrm_agent_harness.toolkits.llms.vision.video_analysis_engine.shutil.which", return_value=None):
            assert _has_ffmpeg() is False


class TestVideoAnalysisEngineAdditionalPaths:
    @pytest.mark.asyncio
    async def test_analyze_video_url_invoke_failure(self, video_engine):
        video_engine.model.ainvoke.side_effect = Exception("upstream down")

        result = await video_engine.analyze_video_url("https://example.com/v.mp4", supports_video=True)

        assert "[Video Analysis Failed:" in result

    @pytest.mark.asyncio
    async def test_local_video_uses_frame_extraction_when_no_video_support(self, video_engine):
        mock_executor = AsyncMock()

        with patch(
            "myrm_agent_harness.toolkits.llms.vision.video_analysis_engine._has_ffmpeg",
            return_value=True,
        ), patch.object(
            video_engine,
            "_frame_extraction_analyze_path",
            new_callable=AsyncMock,
            return_value="frame summary",
        ) as mock_frames:
            result = await video_engine.analyze_local_video(
                "/path/video.mp4", mock_executor, supports_video=False
            )

        assert result == "frame summary"
        mock_frames.assert_awaited_once_with("/path/video.mp4", None)

    @pytest.mark.asyncio
    async def test_frame_extraction_analyze_path_extract_failure(self, video_engine):
        with patch(
            "myrm_agent_harness.toolkits.llms.vision.video_analysis_engine._extract_frames_ffmpeg",
            new_callable=AsyncMock,
            side_effect=RuntimeError("ffmpeg boom"),
        ):
            result = await video_engine._frame_extraction_analyze_path("/path/video.mp4")

        assert "[Video frame extraction failed:" in result

    @pytest.mark.asyncio
    async def test_frame_extraction_analyze_path_model_failure(self, video_engine):
        fake_frame = b"\xff\xd8\xff\xe0" + b"\x00" * 10
        video_engine.model.ainvoke.side_effect = Exception("model boom")

        with patch(
            "myrm_agent_harness.toolkits.llms.vision.video_analysis_engine._extract_frames_ffmpeg",
            new_callable=AsyncMock,
            return_value=[(fake_frame, "image/jpeg")],
        ):
            result = await video_engine._frame_extraction_analyze_path("/path/video.mp4")

        assert "[Video Frame Analysis Failed:" in result

    @pytest.mark.asyncio
    async def test_analyze_video_b64_uses_quicktime_suffix_for_matching_mime(self, video_engine):
        mock_response = MagicMock()
        mock_response.content = "mov summary"
        video_engine.model.ainvoke.return_value = mock_response

        with patch(
            "myrm_agent_harness.toolkits.llms.vision.video_analysis_engine._has_ffmpeg",
            return_value=True,
        ), patch.object(
            video_engine,
            "_frame_extraction_analyze_path",
            new_callable=AsyncMock,
            return_value="unused",
        ) as mock_path:
            await video_engine.analyze_video_b64(
                base64.b64encode(b"fake-mov").decode(),
                "video/quicktime",
                supports_video=False,
            )

        assert mock_path.await_args is not None
        assert str(mock_path.await_args.args[0]).endswith(".mov")
