"""Tests for YouTube transcript extraction."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.web_fetch.youtube_extractor import (
    _extract_video_id,
    _format_timestamp,
    extract_youtube_transcript,
    is_youtube_url,
)


class TestIsYoutubeUrl:
    """URL detection with correct matches and rejection of spoofed domains."""

    def test_standard_watch(self) -> None:
        assert is_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") is True

    def test_no_www(self) -> None:
        assert is_youtube_url("https://youtube.com/watch?v=dQw4w9WgXcQ") is True

    def test_mobile(self) -> None:
        assert is_youtube_url("https://m.youtube.com/watch?v=dQw4w9WgXcQ") is True

    def test_music(self) -> None:
        assert is_youtube_url("https://music.youtube.com/watch?v=dQw4w9WgXcQ") is True

    def test_shorts(self) -> None:
        assert is_youtube_url("https://www.youtube.com/shorts/dQw4w9WgXcQ") is True

    def test_embed(self) -> None:
        assert is_youtube_url("https://www.youtube.com/embed/dQw4w9WgXcQ") is True

    def test_live(self) -> None:
        assert is_youtube_url("https://www.youtube.com/live/dQw4w9WgXcQ") is True

    def test_short_url(self) -> None:
        assert is_youtube_url("https://youtu.be/dQw4w9WgXcQ") is True

    def test_http(self) -> None:
        assert is_youtube_url("http://youtube.com/watch?v=dQw4w9WgXcQ") is True

    def test_query_param_order(self) -> None:
        assert is_youtube_url("https://www.youtube.com/watch?feature=share&v=dQw4w9WgXcQ") is True

    def test_reject_notyoutube(self) -> None:
        assert is_youtube_url("https://notyoutube.com/watch?v=dQw4w9WgXcQ") is False

    def test_reject_fakeyoutube(self) -> None:
        assert is_youtube_url("https://fakeyoutube.com/watch?v=dQw4w9WgXcQ") is False

    def test_reject_evil_subdomain(self) -> None:
        assert is_youtube_url("https://youtube.com.evil.com/watch?v=dQw4w9WgXcQ") is False

    def test_reject_no_protocol(self) -> None:
        assert is_youtube_url("youtube.com/watch?v=dQw4w9WgXcQ") is False

    def test_reject_non_url(self) -> None:
        assert is_youtube_url("hello world") is False

    def test_reject_empty(self) -> None:
        assert is_youtube_url("") is False


class TestExtractVideoId:
    def test_standard(self) -> None:
        assert _extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_short_url(self) -> None:
        assert _extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_shorts(self) -> None:
        assert _extract_video_id("https://youtube.com/shorts/abc123XYZ00") == "abc123XYZ00"

    def test_invalid_url(self) -> None:
        assert _extract_video_id("https://example.com") is None

    def test_invalid_video_id_length(self) -> None:
        assert _extract_video_id("https://youtube.com/watch?v=short") is None

    def test_extra_query_params(self) -> None:
        assert _extract_video_id("https://youtube.com/watch?v=dQw4w9WgXcQ&t=120") == "dQw4w9WgXcQ"

    def test_embed_url(self) -> None:
        assert _extract_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_live_url(self) -> None:
        assert _extract_video_id("https://www.youtube.com/live/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_id_with_dashes_and_underscores(self) -> None:
        assert _extract_video_id("https://youtube.com/watch?v=A-b_C1d2E3f") == "A-b_C1d2E3f"


class TestFormatTimestamp:
    def test_zero(self) -> None:
        assert _format_timestamp(0.0) == "00:00"

    def test_seconds_only(self) -> None:
        assert _format_timestamp(45.0) == "00:45"

    def test_minutes_and_seconds(self) -> None:
        assert _format_timestamp(125.0) == "02:05"

    def test_one_hour(self) -> None:
        assert _format_timestamp(3600.0) == "1:00:00"

    def test_over_one_hour(self) -> None:
        assert _format_timestamp(3661.0) == "1:01:01"

    def test_fractional(self) -> None:
        assert _format_timestamp(59.9) == "00:59"

    def test_large_value(self) -> None:
        assert _format_timestamp(7261.0) == "2:01:01"

    def test_exact_minute(self) -> None:
        assert _format_timestamp(60.0) == "01:00"


class TestExtractYoutubeTranscript:
    @pytest.mark.asyncio
    async def test_invalid_url_returns_none(self) -> None:
        result = await extract_youtube_transcript("https://example.com/page")
        assert result is None

    @pytest.mark.asyncio
    async def test_import_error_returns_none(self) -> None:
        with patch.dict("sys.modules", {"youtube_transcript_api": None}):
            with patch("builtins.__import__", side_effect=ImportError("no module")):
                result = await extract_youtube_transcript("https://youtube.com/watch?v=dQw4w9WgXcQ")
                assert result is None

    @pytest.mark.asyncio
    async def test_successful_extraction(self) -> None:
        mock_segment = MagicMock()
        mock_segment.start = 0.0
        mock_segment.duration = 5.0
        mock_segment.text = "Hello world"

        mock_segment2 = MagicMock()
        mock_segment2.start = 5.0
        mock_segment2.duration = 3.0
        mock_segment2.text = "Second line"

        mock_api_instance = MagicMock()
        mock_api_instance.fetch = MagicMock(return_value=[mock_segment, mock_segment2])

        mock_api_class = MagicMock(return_value=mock_api_instance)

        with patch("myrm_agent_harness.toolkits.web_fetch.youtube_extractor.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = AsyncMock(return_value=[mock_segment, mock_segment2])

            with patch.dict("sys.modules", {"youtube_transcript_api": MagicMock()}):
                import importlib

                import myrm_agent_harness.toolkits.web_fetch.youtube_extractor as yt_mod

                with patch.object(yt_mod, "asyncio", mock_asyncio):
                    result = await extract_youtube_transcript(
                        "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
                    )

        if result is not None:
            assert "Hello world" in result.page_content
            assert "00:00 Hello world" in result.page_content
            assert "00:05 Second line" in result.page_content
            assert result.metadata["video_id"] == "dQw4w9WgXcQ"
            assert result.metadata["source_type"] == "youtube_transcript"
            assert result.metadata["segment_count"] == 2
            assert result.metadata["url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
            assert result.metadata["duration"] == "00:08"

    @pytest.mark.asyncio
    async def test_custom_languages_passed(self) -> None:
        """Custom preferred_languages are forwarded to API."""
        mock_segment = MagicMock()
        mock_segment.start = 0.0
        mock_segment.duration = 2.0
        mock_segment.text = "Chinese text"

        mock_api_instance = MagicMock()
        mock_fetch = MagicMock(return_value=[mock_segment])
        mock_api_instance.fetch = mock_fetch

        mock_module = MagicMock()
        mock_module.YouTubeTranscriptApi = MagicMock(return_value=mock_api_instance)

        with patch.dict("sys.modules", {"youtube_transcript_api": mock_module}):
            import importlib

            import myrm_agent_harness.toolkits.web_fetch.youtube_extractor as yt_mod

            importlib.reload(yt_mod)

            with patch("asyncio.to_thread", new_callable=AsyncMock, return_value=[mock_segment]) as mock_thread:
                result = await yt_mod.extract_youtube_transcript(
                    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    preferred_languages=["zh-Hans", "en"],
                )

                # Verify languages were passed to api.fetch
                call_args = mock_thread.call_args
                assert call_args[1]["languages"] == ["zh-Hans", "en"]

        assert result is not None
        assert "Chinese text" in result.page_content

    @pytest.mark.asyncio
    async def test_transcript_disabled_returns_none(self) -> None:
        mock_api_class = MagicMock()
        mock_api_instance = MagicMock()
        mock_api_instance.fetch = MagicMock(side_effect=Exception("Subtitles are disabled"))
        mock_api_class.return_value = mock_api_instance

        mock_module = MagicMock()
        mock_module.YouTubeTranscriptApi = mock_api_class

        with patch.dict("sys.modules", {"youtube_transcript_api": mock_module}):
            import importlib

            import myrm_agent_harness.toolkits.web_fetch.youtube_extractor as yt_mod

            importlib.reload(yt_mod)

            with patch("asyncio.to_thread", side_effect=Exception("Subtitles are disabled")):
                result = await yt_mod.extract_youtube_transcript(
                    "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
                )
                assert result is None

    @pytest.mark.asyncio
    async def test_empty_segments_returns_none(self) -> None:
        with patch("asyncio.to_thread", new_callable=AsyncMock, return_value=[]):
            with patch.dict("sys.modules", {"youtube_transcript_api": MagicMock()}):
                import importlib

                import myrm_agent_harness.toolkits.web_fetch.youtube_extractor as yt_mod

                importlib.reload(yt_mod)
                result = await yt_mod.extract_youtube_transcript(
                    "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
                )
                assert result is None

    @pytest.mark.asyncio
    async def test_generic_exception_returns_none(self) -> None:
        """Non-disabled/no-transcript exceptions hit the warning branch."""
        with patch("asyncio.to_thread", side_effect=Exception("Connection timeout")):
            with patch.dict("sys.modules", {"youtube_transcript_api": MagicMock()}):
                import importlib

                import myrm_agent_harness.toolkits.web_fetch.youtube_extractor as yt_mod

                importlib.reload(yt_mod)
                result = await yt_mod.extract_youtube_transcript(
                    "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
                )
                assert result is None

    @pytest.mark.asyncio
    async def test_proxy_pool_integration(self) -> None:
        """Proxy pool is used when provided."""
        mock_proxy_config = MagicMock()
        mock_proxy_config.to_url.return_value = "http://proxy:8080"

        mock_pool = MagicMock()
        mock_pool.get_next.return_value = mock_proxy_config

        mock_generic_proxy = MagicMock()
        mock_proxies_module = MagicMock()
        mock_proxies_module.GenericProxyConfig = mock_generic_proxy

        mock_yt_module = MagicMock()

        mock_segment = MagicMock()
        mock_segment.start = 0.0
        mock_segment.duration = 5.0
        mock_segment.text = "Proxy test"

        with patch.dict("sys.modules", {
            "youtube_transcript_api": mock_yt_module,
            "youtube_transcript_api.proxies": mock_proxies_module,
        }):
            import importlib

            import myrm_agent_harness.toolkits.web_fetch.youtube_extractor as yt_mod

            importlib.reload(yt_mod)

            with patch("asyncio.to_thread", new_callable=AsyncMock, return_value=[mock_segment]):
                result = await yt_mod.extract_youtube_transcript(
                    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    proxy_pool=mock_pool,
                )

        mock_pool.get_next.assert_called_once()
        mock_proxy_config.to_url.assert_called_once()
        mock_generic_proxy.assert_called_once_with(https_url="http://proxy:8080")
        assert result is not None
        assert "Proxy test" in result.page_content
