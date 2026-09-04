"""Tests for FAL.ai video provider (FLUX.3 Video, Keyframes, and Continuation).

[POS]
Unit tests for FalVideoProvider: submit -> poll -> download flow with
T2V, Keyframes interpolation, and Video Continuation modes.
Pure AsyncMock-based tests without external respx dependency.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pydantic import SecretStr

from myrm_agent_harness.toolkits.llms.video.models import VideoGenerationConfig
from myrm_agent_harness.toolkits.llms.video.providers.fal_provider import FalVideoProvider
from myrm_agent_harness.toolkits.llms.video.providers.registry import get_registry


def _cfg(**kwargs: object) -> VideoGenerationConfig:
    defaults: dict[str, object] = {
        "provider": "fal",
        "model": "fal-ai/flux-3-video",
        "api_key": SecretStr("test-fal-key"),
        "api_base": "https://queue.fal.run",
        "timeout_seconds": 30.0,
    }
    defaults.update(kwargs)
    return VideoGenerationConfig(**defaults)


class TestFalVideoProviderMetadata:
    def test_provider_id_and_registration(self) -> None:
        provider = FalVideoProvider()
        assert provider.provider_id == "fal"
        assert "FLUX.3" in provider.display_name
        assert provider.default_model == "fal-ai/flux-3-video"

        # Check registry lazy load
        reg = get_registry()
        registered = reg.get("fal")
        assert registered is not None
        assert registered.provider_id == "fal"

    def test_capabilities(self) -> None:
        provider = FalVideoProvider()
        caps = provider.capabilities
        assert caps.supports_aspect_ratio is True
        assert caps.supports_audio is True
        assert caps.max_input_images >= 2
        assert caps.max_input_videos >= 1

    def test_supported_models(self) -> None:
        provider = FalVideoProvider()
        model_ids = [m.id for m in provider.supported_models]
        assert "fal-ai/flux-3-video" in model_ids
        assert any("kling" in mid for mid in model_ids)


class TestFalVideoProviderHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_no_api_key(self) -> None:
        provider = FalVideoProvider()
        cfg = VideoGenerationConfig(provider="fal", model="fal-ai/flux-3-video", api_key=None)
        assert await provider.health_check(cfg) is False

    @pytest.mark.asyncio
    async def test_health_check_success(self) -> None:
        provider = FalVideoProvider()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=httpx.Response(200, json={"status": "ok"}))
        mock_client.aclose = AsyncMock()

        with patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.create_httpx_client", return_value=mock_client):
            assert await provider.health_check(_cfg()) is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self) -> None:
        provider = FalVideoProvider()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=httpx.Response(401, json={"detail": "Unauthorized"}))
        mock_client.aclose = AsyncMock()

        with patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.create_httpx_client", return_value=mock_client):
            assert await provider.health_check(_cfg()) is False


class TestFalVideoProviderGenerate:
    @pytest.mark.asyncio
    async def test_generate_requires_api_key(self) -> None:
        provider = FalVideoProvider()
        cfg = VideoGenerationConfig(provider="fal", model="fal-ai/flux-3-video", api_key=None)
        with pytest.raises(ValueError, match="API key is required"):
            await provider.generate("test prompt", cfg)

    @pytest.mark.asyncio
    async def test_generate_t2v_flow(self) -> None:
        provider = FalVideoProvider()
        fake_video_bytes = b"\x00\x00\x00\x18ftypmp42" + b"fake-video-payload"

        mock_client = MagicMock()
        mock_client.post = AsyncMock(
            return_value=httpx.Response(
                200,
                json={
                    "request_id": "req-123",
                    "status_url": "https://queue.fal.run/fal-ai/flux-3-video/requests/req-123/status",
                    "response_url": "https://queue.fal.run/fal-ai/flux-3-video/requests/req-123",
                },
            )
        )
        # Polling status returns COMPLETED
        mock_client.get = AsyncMock(
            side_effect=[
                httpx.Response(200, json={"status": "COMPLETED"}),
                httpx.Response(200, json={"video": {"url": "https://media.fal.run/output.mp4"}}),
            ]
        )
        mock_client.aclose = AsyncMock()

        fake_resp = httpx.Response(200, content=fake_video_bytes)
        with (
            patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.create_httpx_client", return_value=mock_client),
            patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.secure_get", AsyncMock(return_value=fake_resp)),
            patch("asyncio.sleep", AsyncMock()),
        ):
            output = await provider.generate(
                "Cinematic space drone shot",
                _cfg(),
                duration_seconds=5,
                aspect_ratio="16:9",
            )

        assert mock_client.post.awaited
        assert len(output.assets) == 1
        assert output.assets[0].data == fake_video_bytes
        assert output.assets[0].mime_type == "video/mp4"

    @pytest.mark.asyncio
    async def test_generate_keyframes_mode(self) -> None:
        provider = FalVideoProvider()
        fake_video_bytes = b"\x00\x00\x00\x18ftypmp42" + b"keyframes-video"

        posted_payloads: list[dict[str, object]] = []

        async def _fake_post(url: str, headers: dict[str, str], json: dict[str, object]) -> httpx.Response:
            posted_payloads.append(json)
            return httpx.Response(
                200,
                json={
                    "request_id": "req-kf",
                    "status_url": "https://queue.fal.run/status/req-kf",
                    "response_url": "https://queue.fal.run/res/req-kf",
                },
            )

        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=_fake_post)
        mock_client.get = AsyncMock(
            side_effect=[
                httpx.Response(200, json={"status": "COMPLETED"}),
                httpx.Response(200, json={"video": {"url": "https://media.fal.run/kf-output.mp4"}}),
            ]
        )
        mock_client.aclose = AsyncMock()

        img_a = b"\x89PNG\r\n\x1a\nfake-start-frame"
        img_b = b"\x89PNG\r\n\x1a\nfake-end-frame"

        fake_resp = httpx.Response(200, content=fake_video_bytes)
        with (
            patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.create_httpx_client", return_value=mock_client),
            patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.secure_get", AsyncMock(return_value=fake_resp)),
            patch("asyncio.sleep", AsyncMock()),
        ):
            output = await provider.generate(
                "Smooth transition between keyframes",
                _cfg(),
                reference_images=[img_a, img_b],
            )

        assert len(posted_payloads) == 1
        assert posted_payloads[0].get("mode") == "keyframes"
        assert "image_url" in posted_payloads[0]
        assert "end_image_url" in posted_payloads[0]
        assert len(output.assets) == 1
        assert output.assets[0].data == fake_video_bytes

    @pytest.mark.asyncio
    async def test_generate_continuation_mode(self) -> None:
        provider = FalVideoProvider()
        fake_video_bytes = b"\x00\x00\x00\x18ftypmp42" + b"continued-video"

        posted_payloads: list[dict[str, object]] = []

        async def _fake_post(url: str, headers: dict[str, str], json: dict[str, object]) -> httpx.Response:
            posted_payloads.append(json)
            return httpx.Response(
                200,
                json={
                    "request_id": "req-cont",
                    "status_url": "https://queue.fal.run/status/req-cont",
                    "response_url": "https://queue.fal.run/res/req-cont",
                },
            )

        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=_fake_post)
        mock_client.get = AsyncMock(
            side_effect=[
                httpx.Response(200, json={"status": "COMPLETED"}),
                httpx.Response(200, json={"video": {"url": "https://media.fal.run/cont-output.mp4"}}),
            ]
        )
        mock_client.aclose = AsyncMock()

        ref_video = b"\x00\x00\x00\x18ftypmp42" + b"previous-clip"

        fake_resp = httpx.Response(200, content=fake_video_bytes)
        with (
            patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.create_httpx_client", return_value=mock_client),
            patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.secure_get", AsyncMock(return_value=fake_resp)),
            patch("asyncio.sleep", AsyncMock()),
        ):
            output = await provider.generate(
                "Continue following the spaceship flying into the storm",
                _cfg(),
                reference_videos=[ref_video],
            )

        assert len(posted_payloads) == 1
        assert posted_payloads[0].get("continuation") is True
        assert "video_url" in posted_payloads[0]
        assert len(output.assets) == 1
        assert output.assets[0].data == fake_video_bytes

    @pytest.mark.asyncio
    async def test_generate_continuation_prefers_remote_video_url(self) -> None:
        """Remote source URLs must be passed directly to avoid 413 Payload Too Large."""
        provider = FalVideoProvider()
        fake_video_bytes = b"\x00\x00\x00\x18ftypmp42" + b"continued-remote-video"

        posted_payloads: list[dict[str, object]] = []

        async def _fake_post(url: str, headers: dict[str, str], json: dict[str, object]) -> httpx.Response:
            posted_payloads.append(json)
            return httpx.Response(
                200,
                json={
                    "request_id": "req-remote-cont",
                    "status_url": "https://queue.fal.run/status/req-remote-cont",
                    "response_url": "https://queue.fal.run/res/req-remote-cont",
                },
            )

        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=_fake_post)
        mock_client.get = AsyncMock(
            side_effect=[
                httpx.Response(200, json={"status": "COMPLETED"}),
                httpx.Response(200, json={"video": {"url": "https://media.fal.run/cont-output.mp4"}}),
            ]
        )
        mock_client.aclose = AsyncMock()

        remote_url = "https://cdn.fal.media/uploads/clip_part1.mp4"
        fake_resp = httpx.Response(200, content=fake_video_bytes)
        with (
            patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.create_httpx_client", return_value=mock_client),
            patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.secure_get", AsyncMock(return_value=fake_resp)),
            patch("asyncio.sleep", AsyncMock()),
        ):
            output = await provider.generate(
                "Continue clip without re-encoding to base64",
                _cfg(),
                reference_videos=[b"raw-local-bytes"],
                extra_params={"_video_source_urls": [remote_url]},
            )

        assert len(posted_payloads) == 1
        payload = posted_payloads[0]
        assert payload.get("continuation") is True
        # Critical assertion: must use the remote URL directly, NOT data URI
        assert payload.get("video_url") == remote_url
        assert len(output.assets) == 1

    @pytest.mark.asyncio
    async def test_generate_explicit_mode_override(self) -> None:
        """Explicit mode in extra_params must not be overridden by implicit keyframes heuristic."""
        provider = FalVideoProvider()
        fake_video_bytes = b"\x00\x00\x00\x18ftypmp42" + b"custom-mode-video"

        posted_payloads: list[dict[str, object]] = []

        async def _fake_post(url: str, headers: dict[str, str], json: dict[str, object]) -> httpx.Response:
            posted_payloads.append(json)
            return httpx.Response(
                200,
                json={
                    "request_id": "req-mode-override",
                    "status_url": "https://queue.fal.run/status/req-mode-override",
                    "response_url": "https://queue.fal.run/res/req-mode-override",
                },
            )

        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=_fake_post)
        mock_client.get = AsyncMock(
            side_effect=[
                httpx.Response(200, json={"status": "COMPLETED"}),
                httpx.Response(200, json={"video": {"url": "https://media.fal.run/mode-output.mp4"}}),
            ]
        )
        mock_client.aclose = AsyncMock()

        fake_resp = httpx.Response(200, content=fake_video_bytes)
        with (
            patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.create_httpx_client", return_value=mock_client),
            patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.secure_get", AsyncMock(return_value=fake_resp)),
            patch("asyncio.sleep", AsyncMock()),
        ):
            await provider.generate(
                "Multi-image reference video with explicit mode",
                _cfg(),
                reference_images=[b"img1", b"img2"],
                extra_params={"mode": "multi_reference"},
            )

        assert len(posted_payloads) == 1
        assert posted_payloads[0].get("mode") == "multi_reference"

    @pytest.mark.asyncio
    async def test_generate_continuation_via_parent_request_id(self) -> None:
        """Continuation via parent_request_id must pass parent_request_id and require zero byte uploads."""
        provider = FalVideoProvider()
        fake_video_bytes = b"\x00\x00\x00\x18ftypmp42" + b"continued-video"

        posted_payloads: list[dict[str, object]] = []

        async def _fake_post(url: str, headers: dict[str, str], json: dict[str, object]) -> httpx.Response:
            posted_payloads.append(json)
            return httpx.Response(
                200,
                json={
                    "request_id": "req-cont-parent",
                    "status_url": "https://queue.fal.run/status/req-cont-parent",
                    "response_url": "https://queue.fal.run/res/req-cont-parent",
                },
            )

        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=_fake_post)
        mock_client.get = AsyncMock(
            side_effect=[
                httpx.Response(200, json={"status": "COMPLETED"}),
                httpx.Response(200, json={"video": {"url": "https://media.fal.run/cont-parent.mp4"}}),
            ]
        )
        mock_client.aclose = AsyncMock()

        fake_resp = httpx.Response(200, content=fake_video_bytes)
        with (
            patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.create_httpx_client", return_value=mock_client),
            patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.secure_get", AsyncMock(return_value=fake_resp)),
            patch("asyncio.sleep", AsyncMock()),
        ):
            output = await provider.generate(
                "Continue seamless action from parent clip",
                _cfg(),
                extra_params={"parent_request_id": "fal-parent-req-001"},
            )

        assert len(posted_payloads) == 1
        payload = posted_payloads[0]
        assert payload.get("continuation") is True
        assert payload.get("parent_request_id") == "fal-parent-req-001"
        assert "video_url" not in payload
        assert len(output.assets) == 1

    @pytest.mark.asyncio
    async def test_generate_continuation_large_video_payload_error(self) -> None:
        """Local reference video exceeding 5MB must raise ValueError to prevent HTTP 413."""
        provider = FalVideoProvider()
        oversized_bytes = b"0" * (6 * 1024 * 1024)  # 6MB

        with pytest.raises(ValueError, match="exceeds 5242880 bytes limit"):
            await provider.generate(
                "Oversized video continuation",
                _cfg(),
                reference_videos=[oversized_bytes],
            )

    @pytest.mark.asyncio
    async def test_generate_explicit_mode_i2v_no_end_image(self) -> None:
        """When generation_mode is explicitly i2v, multiple images must not trigger keyframes end_image_url."""
        provider = FalVideoProvider()
        fake_video_bytes = b"\x00\x00\x00\x18ftypmp42" + b"i2v-multi-img"

        posted_payloads: list[dict[str, object]] = []

        async def _fake_post(url: str, headers: dict[str, str], json: dict[str, object]) -> httpx.Response:
            posted_payloads.append(json)
            return httpx.Response(
                200,
                json={
                    "request_id": "req-i2v",
                    "status_url": "https://queue.fal.run/status/req-i2v",
                    "response_url": "https://queue.fal.run/res/req-i2v",
                },
            )

        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=_fake_post)
        mock_client.get = AsyncMock(
            side_effect=[
                httpx.Response(200, json={"status": "COMPLETED"}),
                httpx.Response(200, json={"video": {"url": "https://media.fal.run/i2v.mp4"}}),
            ]
        )
        mock_client.aclose = AsyncMock()

        fake_resp = httpx.Response(200, content=fake_video_bytes)
        with (
            patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.create_httpx_client", return_value=mock_client),
            patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.secure_get", AsyncMock(return_value=fake_resp)),
            patch("asyncio.sleep", AsyncMock()),
        ):
            await provider.generate(
                "Animate character with 2 reference images without keyframe interpolation",
                _cfg(),
                reference_images=[b"char-front", b"char-side"],
                extra_params={"generation_mode": "i2v"},
            )

        assert len(posted_payloads) == 1
        payload = posted_payloads[0]
        assert "image_url" in payload
        # Critical assertion: must NOT include end_image_url or mode=keyframes
        assert "end_image_url" not in payload
        assert payload.get("mode") != "keyframes"

    @pytest.mark.asyncio
    async def test_generate_direct_sync_response(self) -> None:
        """When FAL queue API returns direct video url without status_url, it should download directly."""
        provider = FalVideoProvider()
        fake_video_bytes = b"\x00\x00\x00\x18ftypmp42" + b"direct-sync"

        mock_client = MagicMock()
        mock_client.post = AsyncMock(
            return_value=httpx.Response(
                200,
                json={"video": {"url": "https://media.fal.run/direct-output.mp4"}},
            )
        )
        mock_client.aclose = AsyncMock()

        fake_resp = httpx.Response(200, content=fake_video_bytes)
        with (
            patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.create_httpx_client", return_value=mock_client),
            patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.secure_get", AsyncMock(return_value=fake_resp)),
        ):
            output = await provider.generate("direct sync prompt", _cfg(), enable_audio=True)

        assert len(output.assets) == 1
        assert output.assets[0].data == fake_video_bytes

    @pytest.mark.asyncio
    async def test_generate_polling_failure_raises(self) -> None:
        """When polling status returns FAILED, RuntimeError must be raised with error details."""
        provider = FalVideoProvider()

        mock_client = MagicMock()
        mock_client.post = AsyncMock(
            return_value=httpx.Response(
                200,
                json={"request_id": "req-fail", "status_url": "https://queue.fal.run/req-fail/status"},
            )
        )
        mock_client.get = AsyncMock(
            return_value=httpx.Response(
                200,
                json={"status": "FAILED", "error": "GPU cluster out of memory"},
            )
        )
        mock_client.aclose = AsyncMock()

        with (
            patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.create_httpx_client", return_value=mock_client),
            patch("asyncio.sleep", AsyncMock()),
            pytest.raises(RuntimeError, match="FAL video generation failed: GPU cluster out of memory"),
        ):
            await provider.generate("failure prompt", _cfg())

    @pytest.mark.asyncio
    async def test_generate_content_too_large_raises(self) -> None:
        """When secure_get raises ContentTooLargeError, RuntimeError must be raised gracefully."""
        from myrm_agent_harness.core.security.http.secure_fetch import ContentTooLargeError

        provider = FalVideoProvider()
        mock_client = MagicMock()
        mock_client.post = AsyncMock(
            return_value=httpx.Response(
                200,
                json={"video": {"url": "https://media.fal.run/huge-video.mp4"}},
            )
        )
        mock_client.aclose = AsyncMock()

        with (
            patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.create_httpx_client", return_value=mock_client),
            patch(
                "myrm_agent_harness.toolkits.llms.video.providers.fal_provider.secure_get",
                AsyncMock(side_effect=ContentTooLargeError("Video asset exceeds max download limit")),
            ),
            pytest.raises(ValueError, match="exceeds max download size"),
        ):
            await provider.generate("huge video prompt", _cfg())

    @pytest.mark.asyncio
    async def test_health_check_exception_handling(self) -> None:
        """When network exception occurs during health_check, it must log and return False."""
        provider = FalVideoProvider()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_client.aclose = AsyncMock()

        with patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.create_httpx_client", return_value=mock_client):
            healthy = await provider.health_check(_cfg())

        assert healthy is False

    @pytest.mark.asyncio
    async def test_generate_remote_video_url_from_source_urls(self) -> None:
        """When _video_source_urls is provided in extra_params, it should extract first URL for continuation."""
        provider = FalVideoProvider()
        fake_video_bytes = b"\x00\x00\x00\x18ftypmp42fake-cont"

        posted_payloads: list[dict[str, object]] = []

        async def _fake_post(url: str, headers: dict[str, str], json: dict[str, object]) -> httpx.Response:
            posted_payloads.append(json)
            return httpx.Response(200, json={"video": {"url": "https://media.fal.run/out.mp4"}})

        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=_fake_post)
        mock_client.aclose = AsyncMock()

        fake_resp = httpx.Response(200, content=fake_video_bytes)
        with (
            patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.create_httpx_client", return_value=mock_client),
            patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.secure_get", AsyncMock(return_value=fake_resp)),
        ):
            output = await provider.generate(
                "continue video",
                _cfg(),
                extra_params={"_video_source_urls": ["https://storage.example.com/input.mp4"]},
            )

        assert len(output.assets) == 1
        assert len(posted_payloads) == 1
        assert posted_payloads[0]["video_url"] == "https://storage.example.com/input.mp4"
        assert posted_payloads[0]["continuation"] is True

    @pytest.mark.asyncio
    async def test_generate_submit_failure_raises(self) -> None:
        """When queue submission returns non-200, RuntimeError must be raised with response text."""
        provider = FalVideoProvider()
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=httpx.Response(400, text="Bad Request: invalid aspect ratio"))
        mock_client.aclose = AsyncMock()

        with (
            patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.create_httpx_client", return_value=mock_client),
            pytest.raises(RuntimeError, match="FAL submission failed \\(400\\): Bad Request"),
        ):
            await provider.generate("test prompt", _cfg())

    @pytest.mark.asyncio
    async def test_generate_sync_download_http_error_raises(self) -> None:
        """When direct sync video download returns HTTP >= 400, RuntimeError must be raised."""
        provider = FalVideoProvider()
        mock_client = MagicMock()
        mock_client.post = AsyncMock(
            return_value=httpx.Response(
                200,
                json={"video": {"url": "https://media.fal.run/broken.mp4"}},
            )
        )
        mock_client.aclose = AsyncMock()

        bad_dl_resp = httpx.Response(404, text="Not Found")
        with (
            patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.create_httpx_client", return_value=mock_client),
            patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.secure_get", AsyncMock(return_value=bad_dl_resp)),
            pytest.raises(RuntimeError, match="Failed to download video from .* HTTP 404"),
        ):
            await provider.generate("test prompt", _cfg())

    @pytest.mark.asyncio
    async def test_generate_sync_unrecognized_response_raises(self) -> None:
        """When sync response contains neither status_url nor video, RuntimeError must be raised."""
        provider = FalVideoProvider()
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=httpx.Response(200, json={"unexpected": "payload"}))
        mock_client.aclose = AsyncMock()

        with (
            patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.create_httpx_client", return_value=mock_client),
            pytest.raises(RuntimeError, match="FAL returned unrecognized response"),
        ):
            await provider.generate("test prompt", _cfg())

    @pytest.mark.asyncio
    async def test_generate_poll_timeout_raises(self) -> None:
        """When polling loop exceeds max_attempts, TimeoutError must be raised."""
        provider = FalVideoProvider()
        mock_client = MagicMock()
        mock_client.post = AsyncMock(
            return_value=httpx.Response(
                200,
                json={"status_url": "https://queue.fal.run/status/req-timeout"},
            )
        )
        # Always return IN_PROGRESS
        mock_client.get = AsyncMock(
            return_value=httpx.Response(200, json={"status": "IN_PROGRESS"})
        )
        mock_client.aclose = AsyncMock()

        cfg = _cfg(timeout_seconds=6.0)
        with (
            patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.create_httpx_client", return_value=mock_client),
            patch("asyncio.sleep", AsyncMock()),
            pytest.raises(TimeoutError, match="timed out after 6"),
        ):
            await provider.generate("test prompt", cfg)

    @pytest.mark.asyncio
    async def test_generate_async_content_too_large_raises(self) -> None:
        """When secure_get raises ContentTooLargeError in async polling branch, ValueError must be raised."""
        from myrm_agent_harness.core.security.http.secure_fetch import ContentTooLargeError

        provider = FalVideoProvider()
        mock_client = MagicMock()
        mock_client.post = AsyncMock(
            return_value=httpx.Response(
                200,
                json={
                    "status_url": "https://queue.fal.run/status/req-large",
                    "response_url": "https://queue.fal.run/res/req-large",
                },
            )
        )
        mock_client.get = AsyncMock(
            side_effect=[
                httpx.Response(200, json={"status": "COMPLETED"}),
                httpx.Response(200, json={"video": {"url": "https://media.fal.run/large.mp4"}}),
            ]
        )
        mock_client.aclose = AsyncMock()

        with (
            patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.create_httpx_client", return_value=mock_client),
            patch(
                "myrm_agent_harness.toolkits.llms.video.providers.fal_provider.secure_get",
                AsyncMock(side_effect=ContentTooLargeError("Asset too large")),
            ),
            patch("asyncio.sleep", AsyncMock()),
            pytest.raises(ValueError, match="exceeds max download size"),
        ):
            await provider.generate("large video prompt", _cfg())

    @pytest.mark.asyncio
    async def test_generate_fallback_status_url_from_request_id(self) -> None:
        """When status_url and response_url are omitted in submit response, construct from request_id."""
        provider = FalVideoProvider()
        fake_video_bytes = b"\x00\x00\x00\x18ftypmp42req-id-flow"

        mock_client = MagicMock()
        mock_client.post = AsyncMock(
            return_value=httpx.Response(200, json={"request_id": "req-fallback-123"})
        )
        mock_client.get = AsyncMock(
            side_effect=[
                httpx.Response(200, json={"status": "COMPLETED"}),
                httpx.Response(200, json={"video": {"url": "https://media.fal.run/fallback.mp4"}}),
            ]
        )
        mock_client.aclose = AsyncMock()

        fake_resp = httpx.Response(200, content=fake_video_bytes)
        with (
            patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.create_httpx_client", return_value=mock_client),
            patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.secure_get", AsyncMock(return_value=fake_resp)),
            patch("asyncio.sleep", AsyncMock()),
        ):
            output = await provider.generate("fallback prompt", _cfg())

        assert len(output.assets) == 1
        assert output.assets[0].data == fake_video_bytes

    @pytest.mark.asyncio
    async def test_generate_poll_retry_on_non_200_status(self) -> None:
        """When polling status_url returns transient 502 then 200 COMPLETED, it should succeed."""
        provider = FalVideoProvider()
        fake_video_bytes = b"\x00\x00\x00\x18ftypmp42transient-ok"

        mock_client = MagicMock()
        mock_client.post = AsyncMock(
            return_value=httpx.Response(
                200,
                json={
                    "status_url": "https://queue.fal.run/status/req-retry",
                    "response_url": "https://queue.fal.run/res/req-retry",
                },
            )
        )
        mock_client.get = AsyncMock(
            side_effect=[
                httpx.Response(502, text="Bad Gateway"),
                httpx.Response(200, json={"status": "COMPLETED"}),
                httpx.Response(200, json={"video": {"url": "https://media.fal.run/video.mp4"}}),
            ]
        )
        mock_client.aclose = AsyncMock()

        fake_resp = httpx.Response(200, content=fake_video_bytes)
        with (
            patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.create_httpx_client", return_value=mock_client),
            patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.secure_get", AsyncMock(return_value=fake_resp)),
            patch("asyncio.sleep", AsyncMock()),
        ):
            output = await provider.generate("test prompt", _cfg())

        assert len(output.assets) == 1
        assert output.assets[0].data == fake_video_bytes

    @pytest.mark.asyncio
    async def test_generate_fetch_result_failure_raises(self) -> None:
        """When fetching final result fails with HTTP != 200, RuntimeError must be raised."""
        provider = FalVideoProvider()
        mock_client = MagicMock()
        mock_client.post = AsyncMock(
            return_value=httpx.Response(
                200,
                json={
                    "status_url": "https://queue.fal.run/status/req-res-fail",
                    "response_url": "https://queue.fal.run/res/req-res-fail",
                },
            )
        )
        mock_client.get = AsyncMock(
            side_effect=[
                httpx.Response(200, json={"status": "COMPLETED"}),
                httpx.Response(500, text="Internal storage fetch error"),
            ]
        )
        mock_client.aclose = AsyncMock()

        with (
            patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.create_httpx_client", return_value=mock_client),
            patch("asyncio.sleep", AsyncMock()),
            pytest.raises(RuntimeError, match="Failed to fetch FAL result: Internal storage fetch error"),
        ):
            await provider.generate("test prompt", _cfg())

    @pytest.mark.asyncio
    async def test_generate_result_missing_video_url_raises(self) -> None:
        """When final result is missing video.url, RuntimeError must be raised."""
        provider = FalVideoProvider()
        mock_client = MagicMock()
        mock_client.post = AsyncMock(
            return_value=httpx.Response(
                200,
                json={
                    "status_url": "https://queue.fal.run/status/req-no-url",
                    "response_url": "https://queue.fal.run/res/req-no-url",
                },
            )
        )
        mock_client.get = AsyncMock(
            side_effect=[
                httpx.Response(200, json={"status": "COMPLETED"}),
                httpx.Response(200, json={"video": {}}),
            ]
        )
        mock_client.aclose = AsyncMock()

        with (
            patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.create_httpx_client", return_value=mock_client),
            patch("asyncio.sleep", AsyncMock()),
            pytest.raises(RuntimeError, match="FAL result missing video url"),
        ):
            await provider.generate("test prompt", _cfg())

    @pytest.mark.asyncio
    async def test_generate_async_download_http_error_raises(self) -> None:
        """When final video download returns HTTP >= 400, RuntimeError must be raised."""
        provider = FalVideoProvider()
        mock_client = MagicMock()
        mock_client.post = AsyncMock(
            return_value=httpx.Response(
                200,
                json={
                    "status_url": "https://queue.fal.run/status/req-dl-fail",
                    "response_url": "https://queue.fal.run/res/req-dl-fail",
                },
            )
        )
        mock_client.get = AsyncMock(
            side_effect=[
                httpx.Response(200, json={"status": "COMPLETED"}),
                httpx.Response(200, json={"video": {"url": "https://media.fal.run/video.mp4"}}),
            ]
        )
        mock_client.aclose = AsyncMock()

        bad_dl_resp = httpx.Response(403, text="Forbidden")
        with (
            patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.create_httpx_client", return_value=mock_client),
            patch("myrm_agent_harness.toolkits.llms.video.providers.fal_provider.secure_get", AsyncMock(return_value=bad_dl_resp)),
            patch("asyncio.sleep", AsyncMock()),
            pytest.raises(RuntimeError, match="Failed to download video from .* HTTP 403"),
        ):
            await provider.generate("test prompt", _cfg())




