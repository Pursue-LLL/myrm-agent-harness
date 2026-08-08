"""Tests for xAI provider extend/edit routing logic.

[POS]
Unit tests for XAIGrokProvider extend and edit mode routing.
Covers: mode resolution, URL extraction, capabilities, endpoint routing,
error handling, poll timeout, download size limit, duration clamping,
idempotency headers, and progress callbacks.
"""

from __future__ import annotations

import json

import pytest

respx = pytest.importorskip("respx")
import httpx
from httpx import Response
from pydantic import SecretStr

from myrm_agent_harness.toolkits.llms.video.models import VideoGenerationConfig
from myrm_agent_harness.toolkits.llms.video.providers.xai_provider import XAIGrokProvider


@pytest.fixture
def xai_config() -> VideoGenerationConfig:
    return VideoGenerationConfig(
        provider="xai",
        model="grok-imagine-video",
        api_key=SecretStr("test-key"),
        base_url="https://api.x.ai/v1",
        poll_interval_seconds=0.01,
        max_poll_attempts=3,
    )


class TestResolveMode:
    """Unit tests for _resolve_mode static method."""

    def test_generate_when_no_videos(self) -> None:
        assert XAIGrokProvider._resolve_mode(None, None, None) == "generate"

    def test_generate_when_no_url(self) -> None:
        assert XAIGrokProvider._resolve_mode([b"data"], None, 8) == "generate"

    def test_extend_with_url_and_duration(self) -> None:
        assert XAIGrokProvider._resolve_mode([b"data"], "https://cdn/v.mp4", 8) == "extend"

    def test_edit_with_url_no_duration(self) -> None:
        assert XAIGrokProvider._resolve_mode([b"data"], "https://cdn/v.mp4", None) == "edit"

    def test_extend_with_zero_duration(self) -> None:
        assert XAIGrokProvider._resolve_mode([b"data"], "https://cdn/v.mp4", 0) == "extend"

    def test_generate_when_empty_videos_list(self) -> None:
        assert XAIGrokProvider._resolve_mode([], "https://cdn/v.mp4", 5) == "generate"

    def test_generate_when_url_none_with_duration(self) -> None:
        assert XAIGrokProvider._resolve_mode([b"data"], None, 10) == "generate"

    def test_extend_with_negative_duration(self) -> None:
        assert XAIGrokProvider._resolve_mode([b"d"], "https://cdn/v.mp4", -1) == "extend"


class TestExtractVideoSourceUrl:
    """Unit tests for _extract_video_source_url static method."""

    def test_none_params(self) -> None:
        assert XAIGrokProvider._extract_video_source_url(None) is None

    def test_empty_params(self) -> None:
        assert XAIGrokProvider._extract_video_source_url({}) is None

    def test_missing_key(self) -> None:
        assert XAIGrokProvider._extract_video_source_url({"other": "val"}) is None

    def test_valid_https_url(self) -> None:
        params = {"_video_source_urls": ["https://cdn.example.com/video.mp4"]}
        assert XAIGrokProvider._extract_video_source_url(params) == "https://cdn.example.com/video.mp4"

    def test_valid_http_url(self) -> None:
        params = {"_video_source_urls": ["http://cdn.example.com/video.mp4"]}
        assert XAIGrokProvider._extract_video_source_url(params) == "http://cdn.example.com/video.mp4"

    def test_local_path_rejected(self) -> None:
        params = {"_video_source_urls": ["/tmp/video.mp4"]}
        assert XAIGrokProvider._extract_video_source_url(params) is None

    def test_empty_list(self) -> None:
        params = {"_video_source_urls": []}
        assert XAIGrokProvider._extract_video_source_url(params) is None

    def test_whitespace_url_stripped(self) -> None:
        params = {"_video_source_urls": ["  https://cdn.example.com/v.mp4  "]}
        assert XAIGrokProvider._extract_video_source_url(params) == "https://cdn.example.com/v.mp4"

    def test_non_list_value_ignored(self) -> None:
        params = {"_video_source_urls": "https://cdn.example.com/v.mp4"}
        assert XAIGrokProvider._extract_video_source_url(params) is None

    def test_multiple_urls_returns_first(self) -> None:
        params = {"_video_source_urls": [
            "https://cdn.example.com/first.mp4",
            "https://cdn.example.com/second.mp4",
        ]}
        assert XAIGrokProvider._extract_video_source_url(params) == "https://cdn.example.com/first.mp4"

    def test_ftp_url_rejected(self) -> None:
        params = {"_video_source_urls": ["ftp://files.example.com/video.mp4"]}
        assert XAIGrokProvider._extract_video_source_url(params) is None


class TestCapabilities:
    """Verify capabilities declarations include V2V support."""

    def test_supports_video_input(self) -> None:
        provider = XAIGrokProvider()
        caps = provider.capabilities
        assert caps.max_input_videos == 1

    def test_v2v_mode_declared(self) -> None:
        provider = XAIGrokProvider()
        caps = provider.capabilities
        assert caps.mode_capabilities is not None
        assert caps.mode_capabilities.video_to_video is not None
        assert caps.mode_capabilities.video_to_video.max_duration_seconds == 10

    def test_t2v_mode_max_duration(self) -> None:
        provider = XAIGrokProvider()
        caps = provider.capabilities
        assert caps.mode_capabilities is not None
        assert caps.mode_capabilities.generate is not None
        assert caps.mode_capabilities.generate.max_duration_seconds == 15

    def test_i2v_mode_max_duration(self) -> None:
        provider = XAIGrokProvider()
        caps = provider.capabilities
        assert caps.mode_capabilities is not None
        assert caps.mode_capabilities.image_to_video is not None
        assert caps.mode_capabilities.image_to_video.max_duration_seconds == 10

    def test_max_images_declared(self) -> None:
        provider = XAIGrokProvider()
        caps = provider.capabilities
        assert caps.max_input_images == 7


@pytest.mark.asyncio
class TestGenerateExtendEndpoint:
    """Integration test for extend mode hitting correct endpoint."""

    @respx.mock
    async def test_extend_calls_extensions_endpoint(self, xai_config: VideoGenerationConfig) -> None:
        submit_route = respx.post("https://api.x.ai/v1/videos/extensions").mock(
            return_value=Response(200, json={"request_id": "req-ext-001"})
        )
        respx.get("https://api.x.ai/v1/videos/req-ext-001").mock(
            return_value=Response(200, json={
                "status": "done",
                "video": {"url": "https://cdn.xai.com/out.mp4", "duration": 8},
                "model": "grok-imagine-video",
            })
        )
        respx.get("https://cdn.xai.com/out.mp4").mock(
            return_value=Response(200, content=b"\x00" * 100)
        )

        provider = XAIGrokProvider()
        result = await provider.generate(
            "continue the sunset scene",
            xai_config,
            duration_seconds=8,
            reference_videos=[b"dummy-video-bytes"],
            extra_params={"_video_source_urls": ["https://cdn.xai.com/prev.mp4"]},
        )

        assert submit_route.called
        req_body = json.loads(submit_route.calls[0].request.content)
        assert req_body["video"] == {"url": "https://cdn.xai.com/prev.mp4"}
        assert req_body["duration"] == 8
        assert req_body["prompt"] == "continue the sunset scene"
        assert len(result.assets) == 1
        assert result.assets[0].metadata["mode"] == "extend"

    @respx.mock
    async def test_edit_calls_edits_endpoint(self, xai_config: VideoGenerationConfig) -> None:
        submit_route = respx.post("https://api.x.ai/v1/videos/edits").mock(
            return_value=Response(200, json={"request_id": "req-edit-002"})
        )
        respx.get("https://api.x.ai/v1/videos/req-edit-002").mock(
            return_value=Response(200, json={
                "status": "done",
                "video": {"url": "https://cdn.xai.com/edited.mp4", "duration": 5},
                "model": "grok-imagine-video",
            })
        )
        respx.get("https://cdn.xai.com/edited.mp4").mock(
            return_value=Response(200, content=b"\x00" * 80)
        )

        provider = XAIGrokProvider()
        result = await provider.generate(
            "make the sky more purple",
            xai_config,
            reference_videos=[b"dummy-video-bytes"],
            extra_params={"_video_source_urls": ["https://cdn.xai.com/source.mp4"]},
        )

        assert submit_route.called
        req_body = json.loads(submit_route.calls[0].request.content)
        assert req_body["video"] == {"url": "https://cdn.xai.com/source.mp4"}
        assert "duration" not in req_body
        assert result.assets[0].metadata["mode"] == "edit"

    @respx.mock
    async def test_generate_without_video_input(self, xai_config: VideoGenerationConfig) -> None:
        submit_route = respx.post("https://api.x.ai/v1/videos/generations").mock(
            return_value=Response(200, json={"request_id": "req-gen-003"})
        )
        respx.get("https://api.x.ai/v1/videos/req-gen-003").mock(
            return_value=Response(200, json={
                "status": "done",
                "video": {"url": "https://cdn.xai.com/new.mp4", "duration": 12},
                "model": "grok-imagine-video",
            })
        )
        respx.get("https://cdn.xai.com/new.mp4").mock(
            return_value=Response(200, content=b"\x00" * 60)
        )

        provider = XAIGrokProvider()
        result = await provider.generate(
            "a beautiful sunset over mountains",
            xai_config,
            duration_seconds=12,
        )

        assert submit_route.called
        req_body = json.loads(submit_route.calls[0].request.content)
        assert "video" not in req_body
        assert req_body["duration"] == 12
        assert result.assets[0].metadata["mode"] == "generate"


@pytest.mark.asyncio
class TestErrorHandling:
    """Error paths: API failures, poll timeout, download size limit."""

    @respx.mock
    async def test_submit_api_error_raises(self, xai_config: VideoGenerationConfig) -> None:
        """Submit returning 4xx/5xx should raise httpx.HTTPStatusError."""
        respx.post("https://api.x.ai/v1/videos/generations").mock(
            return_value=Response(429, json={"error": {"message": "rate limit"}})
        )

        provider = XAIGrokProvider()
        with pytest.raises(httpx.HTTPStatusError):
            await provider.generate("test prompt", xai_config, duration_seconds=5)

    @respx.mock
    async def test_poll_timeout_raises(self, xai_config: VideoGenerationConfig) -> None:
        """Exceeding max_poll_attempts should raise TimeoutError."""
        respx.post("https://api.x.ai/v1/videos/generations").mock(
            return_value=Response(200, json={"request_id": "req-timeout"})
        )
        respx.get("https://api.x.ai/v1/videos/req-timeout").mock(
            return_value=Response(200, json={"status": "in_progress"})
        )

        provider = XAIGrokProvider()
        with pytest.raises(TimeoutError, match="did not finish in time"):
            await provider.generate("timeout prompt", xai_config, duration_seconds=5)

    @respx.mock
    async def test_poll_failed_status_raises(self, xai_config: VideoGenerationConfig) -> None:
        """Poll returning 'failed' status should raise RuntimeError."""
        respx.post("https://api.x.ai/v1/videos/extensions").mock(
            return_value=Response(200, json={"request_id": "req-fail"})
        )
        respx.get("https://api.x.ai/v1/videos/req-fail").mock(
            return_value=Response(200, json={
                "status": "failed",
                "error": {"message": "content policy violation"},
            })
        )

        provider = XAIGrokProvider()
        with pytest.raises(RuntimeError, match="content policy violation"):
            await provider.generate(
                "fail prompt",
                xai_config,
                duration_seconds=5,
                reference_videos=[b"data"],
                extra_params={"_video_source_urls": ["https://cdn/v.mp4"]},
            )

    @respx.mock
    async def test_download_exceeds_max_size_raises(self, xai_config: VideoGenerationConfig) -> None:
        """Video larger than max_download_bytes should raise ValueError."""
        xai_config_small = xai_config.model_copy(update={"max_download_bytes": 50})
        respx.post("https://api.x.ai/v1/videos/generations").mock(
            return_value=Response(200, json={"request_id": "req-big"})
        )
        respx.get("https://api.x.ai/v1/videos/req-big").mock(
            return_value=Response(200, json={
                "status": "done",
                "video": {"url": "https://cdn.xai.com/big.mp4", "duration": 5},
                "model": "grok-imagine-video",
            })
        )
        respx.get("https://cdn.xai.com/big.mp4").mock(
            return_value=Response(200, content=b"\x00" * 100)
        )

        provider = XAIGrokProvider()
        with pytest.raises(ValueError, match="exceeds max download size"):
            await provider.generate("big video", xai_config_small, duration_seconds=5)

    @respx.mock
    async def test_missing_request_id_raises(self, xai_config: VideoGenerationConfig) -> None:
        """Submit response without request_id should raise ValueError."""
        respx.post("https://api.x.ai/v1/videos/generations").mock(
            return_value=Response(200, json={"status": "accepted"})
        )

        provider = XAIGrokProvider()
        with pytest.raises(ValueError, match="missing request_id"):
            await provider.generate("no id prompt", xai_config, duration_seconds=5)

    @respx.mock
    async def test_missing_video_url_in_poll_raises(self, xai_config: VideoGenerationConfig) -> None:
        """Poll returning done but no video URL should raise ValueError."""
        respx.post("https://api.x.ai/v1/videos/generations").mock(
            return_value=Response(200, json={"request_id": "req-nourl"})
        )
        respx.get("https://api.x.ai/v1/videos/req-nourl").mock(
            return_value=Response(200, json={
                "status": "done",
                "video": {},
                "model": "grok-imagine-video",
            })
        )

        provider = XAIGrokProvider()
        with pytest.raises(ValueError, match="missing video URL"):
            await provider.generate("no url prompt", xai_config, duration_seconds=5)

    async def test_missing_api_key_raises(self) -> None:
        """Config without API key should raise ValueError."""
        config = VideoGenerationConfig(
            provider="xai",
            model="grok-imagine-video",
            api_key=None,
            base_url="https://api.x.ai/v1",
        )
        provider = XAIGrokProvider()
        with pytest.raises(ValueError, match="API key missing"):
            await provider.generate("test", config, duration_seconds=5)


@pytest.mark.asyncio
class TestDurationClamping:
    """Verify extend mode duration is correctly clamped to [2, 10]."""

    @respx.mock
    async def test_extend_duration_clamped_to_max_10(self, xai_config: VideoGenerationConfig) -> None:
        """duration_seconds=15 should be clamped to 10 in extend mode."""
        submit_route = respx.post("https://api.x.ai/v1/videos/extensions").mock(
            return_value=Response(200, json={"request_id": "req-clamp"})
        )
        respx.get("https://api.x.ai/v1/videos/req-clamp").mock(
            return_value=Response(200, json={
                "status": "done",
                "video": {"url": "https://cdn.xai.com/clamped.mp4", "duration": 10},
                "model": "grok-imagine-video",
            })
        )
        respx.get("https://cdn.xai.com/clamped.mp4").mock(
            return_value=Response(200, content=b"\x00" * 50)
        )

        provider = XAIGrokProvider()
        await provider.generate(
            "extend scene",
            xai_config,
            duration_seconds=15,
            reference_videos=[b"data"],
            extra_params={"_video_source_urls": ["https://cdn/src.mp4"]},
        )

        req_body = json.loads(submit_route.calls[0].request.content)
        assert req_body["duration"] == 10

    @respx.mock
    async def test_extend_duration_clamped_to_min_2(self, xai_config: VideoGenerationConfig) -> None:
        """duration_seconds=1 should be clamped to at least 2 in extend mode (min(10, max(2, 1)))."""
        submit_route = respx.post("https://api.x.ai/v1/videos/extensions").mock(
            return_value=Response(200, json={"request_id": "req-min"})
        )
        respx.get("https://api.x.ai/v1/videos/req-min").mock(
            return_value=Response(200, json={
                "status": "done",
                "video": {"url": "https://cdn.xai.com/min.mp4", "duration": 2},
                "model": "grok-imagine-video",
            })
        )
        respx.get("https://cdn.xai.com/min.mp4").mock(
            return_value=Response(200, content=b"\x00" * 30)
        )

        provider = XAIGrokProvider()
        await provider.generate(
            "short extend",
            xai_config,
            duration_seconds=1,
            reference_videos=[b"data"],
            extra_params={"_video_source_urls": ["https://cdn/src.mp4"]},
        )

        req_body = json.loads(submit_route.calls[0].request.content)
        assert req_body["duration"] == 2


@pytest.mark.asyncio
class TestIdempotencyAndHeaders:
    """Verify idempotency key header and auth header presence."""

    @respx.mock
    async def test_idempotency_key_present(self, xai_config: VideoGenerationConfig) -> None:
        """Every submit request should include x-idempotency-key header."""
        submit_route = respx.post("https://api.x.ai/v1/videos/generations").mock(
            return_value=Response(200, json={"request_id": "req-idem"})
        )
        respx.get("https://api.x.ai/v1/videos/req-idem").mock(
            return_value=Response(200, json={
                "status": "done",
                "video": {"url": "https://cdn.xai.com/idem.mp4", "duration": 5},
                "model": "grok-imagine-video",
            })
        )
        respx.get("https://cdn.xai.com/idem.mp4").mock(
            return_value=Response(200, content=b"\x00" * 20)
        )

        provider = XAIGrokProvider()
        await provider.generate("idem test", xai_config, duration_seconds=5)

        req_headers = submit_route.calls[0].request.headers
        assert "x-idempotency-key" in req_headers
        idem_key = req_headers["x-idempotency-key"]
        assert len(idem_key) == 36  # UUID format

    @respx.mock
    async def test_auth_header_correct(self, xai_config: VideoGenerationConfig) -> None:
        """Authorization header should contain Bearer token."""
        submit_route = respx.post("https://api.x.ai/v1/videos/generations").mock(
            return_value=Response(200, json={"request_id": "req-auth"})
        )
        respx.get("https://api.x.ai/v1/videos/req-auth").mock(
            return_value=Response(200, json={
                "status": "done",
                "video": {"url": "https://cdn.xai.com/auth.mp4", "duration": 5},
                "model": "grok-imagine-video",
            })
        )
        respx.get("https://cdn.xai.com/auth.mp4").mock(
            return_value=Response(200, content=b"\x00" * 20)
        )

        provider = XAIGrokProvider()
        await provider.generate("auth test", xai_config, duration_seconds=5)

        req_headers = submit_route.calls[0].request.headers
        assert req_headers["authorization"] == "Bearer test-key"


@pytest.mark.asyncio
class TestProgressCallback:
    """Verify progress_callback is invoked correctly in extend/edit modes."""

    @respx.mock
    async def test_extend_progress_callback_called(self, xai_config: VideoGenerationConfig) -> None:
        """progress_callback should be called with submit and download messages."""
        progress_messages: list[str] = []

        async def _cb(msg: str) -> None:
            progress_messages.append(msg)

        config = xai_config.model_copy(update={"progress_callback": _cb})

        respx.post("https://api.x.ai/v1/videos/extensions").mock(
            return_value=Response(200, json={"request_id": "req-prog"})
        )
        respx.get("https://api.x.ai/v1/videos/req-prog").mock(
            return_value=Response(200, json={
                "status": "done",
                "video": {"url": "https://cdn.xai.com/prog.mp4", "duration": 5},
                "model": "grok-imagine-video",
            })
        )
        respx.get("https://cdn.xai.com/prog.mp4").mock(
            return_value=Response(200, content=b"\x00" * 20)
        )

        provider = XAIGrokProvider()
        await provider.generate(
            "extend with progress",
            config,
            duration_seconds=5,
            reference_videos=[b"data"],
            extra_params={"_video_source_urls": ["https://cdn/v.mp4"]},
        )

        assert len(progress_messages) == 2
        assert "extend" in progress_messages[0].lower()
        assert "download" in progress_messages[1].lower()


@pytest.mark.asyncio
class TestMetadataOutput:
    """Verify output metadata contains expected fields."""

    @respx.mock
    async def test_extend_metadata_fields(self, xai_config: VideoGenerationConfig) -> None:
        respx.post("https://api.x.ai/v1/videos/extensions").mock(
            return_value=Response(200, json={"request_id": "req-meta-ext"})
        )
        respx.get("https://api.x.ai/v1/videos/req-meta-ext").mock(
            return_value=Response(200, json={
                "status": "done",
                "video": {"url": "https://cdn.xai.com/meta.mp4", "duration": 7},
                "model": "grok-imagine-video",
            })
        )
        respx.get("https://cdn.xai.com/meta.mp4").mock(
            return_value=Response(200, content=b"\x00" * 40)
        )

        provider = XAIGrokProvider()
        result = await provider.generate(
            "metadata test",
            xai_config,
            duration_seconds=7,
            reference_videos=[b"data"],
            extra_params={"_video_source_urls": ["https://cdn/v.mp4"]},
        )

        asset = result.assets[0]
        assert asset.mime_type == "video/mp4"
        assert asset.filename.startswith("video-xai-")
        assert asset.metadata["request_id"] == "req-meta-ext"
        assert asset.metadata["mode"] == "extend"
        assert asset.metadata["video_url"] == "https://cdn.xai.com/meta.mp4"
        assert asset.metadata["duration"] == 7
        assert asset.metadata["model"] == "grok-imagine-video"
        assert asset.data == b"\x00" * 40


@pytest.mark.asyncio
class TestHealthCheck:
    """Verify health_check endpoint behavior."""

    @respx.mock
    async def test_health_check_success(self, xai_config: VideoGenerationConfig) -> None:
        respx.get("https://api.x.ai/v1/models").mock(
            return_value=Response(200, json={"models": []})
        )
        provider = XAIGrokProvider()
        assert await provider.health_check(xai_config) is True

    @respx.mock
    async def test_health_check_failure(self, xai_config: VideoGenerationConfig) -> None:
        respx.get("https://api.x.ai/v1/models").mock(
            return_value=Response(401, json={"error": "unauthorized"})
        )
        provider = XAIGrokProvider()
        assert await provider.health_check(xai_config) is False

    async def test_health_check_no_key(self) -> None:
        config = VideoGenerationConfig(
            provider="xai", model="grok-imagine-video", api_key=None,
        )
        provider = XAIGrokProvider()
        assert await provider.health_check(config) is False
