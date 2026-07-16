"""Tests for Google Veo provider (metadata + mocked HTTP paths)."""

from __future__ import annotations

import asyncio
import base64
from unittest.mock import AsyncMock

import httpx
import pytest

respx = pytest.importorskip("respx")
from pydantic import SecretStr

from myrm_agent_harness.toolkits.llms.video.models import VideoGenerationConfig
from myrm_agent_harness.toolkits.llms.video.providers.google_provider import (
    GoogleVeoProvider,
    _resolve_aspect_ratio,
    _resolve_duration,
    _resolve_resolution,
)

_MIN_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
    b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _cfg(**kwargs: object) -> VideoGenerationConfig:
    defaults: dict[str, object] = {
        "provider": "gemini",
        "model": "veo-3.1-fast-generate-preview",
        "api_key": SecretStr("test-key"),
        "base_url": "https://generativelanguage.googleapis.com",
        "max_poll_attempts": 5,
        "poll_interval_seconds": 0.0,
    }
    defaults.update(kwargs)
    return VideoGenerationConfig(**defaults)


@pytest.fixture
def no_async_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())


class TestGoogleVeoProviderMetadata:
    def test_provider_id_is_gemini(self) -> None:
        p = GoogleVeoProvider()
        assert p.provider_id == "gemini"

    def test_default_model(self) -> None:
        p = GoogleVeoProvider()
        assert p.default_model == "veo-3.1-fast-generate-preview"

    def test_supported_models_non_empty(self) -> None:
        p = GoogleVeoProvider()
        assert len(p.supported_models) >= 1

    def test_capabilities_flags(self) -> None:
        p = GoogleVeoProvider()
        caps = p.capabilities
        assert caps.max_videos >= 1
        assert caps.supports_aspect_ratio is True


class TestGoogleVeoHelpers:
    def test_resolve_duration_clamp(self) -> None:
        assert _resolve_duration(2) == 4
        assert _resolve_duration(7) in (6, 8)
        assert _resolve_duration(100) == 8
        assert _resolve_duration(None) is None

    def test_resolve_aspect_ratio(self) -> None:
        assert _resolve_aspect_ratio("16:9") == "16:9"
        assert _resolve_aspect_ratio("unknown") is None

    def test_resolve_resolution(self) -> None:
        assert _resolve_resolution("720P") == "720p"
        assert _resolve_resolution("bad") is None


@pytest.mark.asyncio
class TestGoogleVeoGenerateMocked:
    @respx.mock
    async def test_generate_requires_api_key(self) -> None:
        cfg = _cfg(api_key=None)
        prov = GoogleVeoProvider()
        with pytest.raises(ValueError, match="Google API key missing"):
            await prov.generate("hello", cfg)

    @respx.mock
    async def test_generate_success_base64_video(self, no_async_sleep: None) -> None:
        cfg = _cfg()
        model = cfg.model
        base = cfg.base_url or ""
        post_route = f"{base}/v1beta/models/{model}:generateVideos"
        op_name = "operations/op-test"

        respx.post(post_route).mock(
            return_value=httpx.Response(200, json={"name": op_name})
        )
        poll_route = f"{base}/v1beta/{op_name}"
        payload_b64 = base64.b64encode(b"fake-mp4-bytes").decode("ascii")
        respx.get(poll_route).mock(
            side_effect=[
                httpx.Response(200, json={"done": False}),
                httpx.Response(
                    200,
                    json={
                        "done": True,
                        "response": {
                            "generatedVideos": [
                                {"video": {"videoBytes": payload_b64}}
                            ]
                        },
                    },
                ),
            ]
        )

        prov = GoogleVeoProvider()
        out = await prov.generate(
            "sunset",
            cfg,
            duration_seconds=8,
            aspect_ratio="16:9",
            resolution="720P",
            enable_audio=True,
            reference_images=[_MIN_PNG],
        )
        assert len(out.assets) == 1
        assert out.assets[0].data == b"fake-mp4-bytes"

    @respx.mock
    async def test_generate_poll_reports_operation_error(self, no_async_sleep: None) -> None:
        cfg = _cfg(max_poll_attempts=3)
        model = cfg.model
        base = cfg.base_url or ""
        post_route = f"{base}/v1beta/models/{model}:generateVideos"
        op_name = "operations/op-err"

        respx.post(post_route).mock(
            return_value=httpx.Response(200, json={"name": op_name})
        )
        poll_route = f"{base}/v1beta/{op_name}"
        respx.get(poll_route).mock(
            return_value=httpx.Response(
                200,
                json={"done": True, "error": {"message": "quota"}},
            )
        )

        prov = GoogleVeoProvider()
        with pytest.raises(RuntimeError, match="Google Veo generation failed"):
            await prov.generate("x", cfg)

    @respx.mock
    async def test_generate_poll_timeout(self, no_async_sleep: None) -> None:
        cfg = _cfg(max_poll_attempts=2)
        model = cfg.model
        base = cfg.base_url or ""
        post_route = f"{base}/v1beta/models/{model}:generateVideos"
        op_name = "operations/op-slow"

        respx.post(post_route).mock(
            return_value=httpx.Response(200, json={"name": op_name})
        )
        poll_route = f"{base}/v1beta/{op_name}"
        respx.get(poll_route).mock(
            return_value=httpx.Response(200, json={"done": False})
        )

        prov = GoogleVeoProvider()
        with pytest.raises(TimeoutError, match="did not finish"):
            await prov.generate("x", cfg)

    @respx.mock
    async def test_generate_download_via_uri(self, no_async_sleep: None) -> None:
        cfg = _cfg()
        model = cfg.model
        base = cfg.base_url or ""
        post_route = f"{base}/v1beta/models/{model}:generateVideos"
        op_name = "operations/op-uri"

        respx.post(post_route).mock(
            return_value=httpx.Response(200, json={"name": op_name})
        )
        poll_route = f"{base}/v1beta/{op_name}"
        video_uri = "https://cdn.example.com/video.bin"
        respx.get(poll_route).mock(
            return_value=httpx.Response(
                200,
                json={
                    "done": True,
                    "response": {
                        "generatedVideos": [{"video": {"uri": video_uri}}]
                    },
                },
            )
        )
        respx.get(video_uri).mock(
            return_value=httpx.Response(200, content=b"\x00\x01\x02")
        )

        prov = GoogleVeoProvider()
        out = await prov.generate("prompt", cfg)
        assert len(out.assets) == 1
        assert out.assets[0].data == b"\x00\x01\x02"


@pytest.mark.asyncio
class TestGoogleVeoHealthCheck:
    @respx.mock
    async def test_health_check_false_without_key(self) -> None:
        cfg = _cfg(api_key=None)
        assert await GoogleVeoProvider().health_check(cfg) is False

    @respx.mock
    async def test_health_check_true_on_200(self) -> None:
        cfg = _cfg()
        base = cfg.base_url or ""
        respx.get(f"{base}/v1beta/models").mock(
            return_value=httpx.Response(200, json={"models": []})
        )
        assert await GoogleVeoProvider().health_check(cfg) is True

    @respx.mock
    async def test_health_check_false_on_http_error(self) -> None:
        cfg = _cfg()
        base = cfg.base_url or ""
        respx.get(f"{base}/v1beta/models").mock(
            return_value=httpx.Response(401, json={"error": "denied"})
        )
        assert await GoogleVeoProvider().health_check(cfg) is False
