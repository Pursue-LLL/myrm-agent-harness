"""Tests for OpenAI Sora provider (metadata + mocked HTTP paths).

[POS]
Unit tests for OpenAISoraProvider: submit -> poll -> download flow. The
download step uses secure_request (SSRF shield + streaming size cap), so the
SSRF DNS pinning is short-circuited to let respx intercept the content fetch.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

respx = pytest.importorskip("respx")
from httpx import Response
from pydantic import SecretStr

from myrm_agent_harness.toolkits.llms.video.models import VideoGenerationConfig
from myrm_agent_harness.toolkits.llms.video.providers.openai_provider import (
    OpenAISoraProvider,
    _resolve_duration,
    _resolve_size,
)


def _cfg(**kwargs: object) -> VideoGenerationConfig:
    defaults: dict[str, object] = {
        "provider": "openai",
        "model": "sora",
        "api_key": SecretStr("test-key"),
        "base_url": "https://api.openai.com/v1",
        "max_poll_attempts": 3,
        "poll_interval_seconds": 0.0,
    }
    defaults.update(kwargs)
    return VideoGenerationConfig(**defaults)


@pytest.fixture(autouse=True)
def _no_dns_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Short-circuit SSRF DNS pinning so respx can intercept secure_request downloads."""

    async def _no_pin(url: str, allowed_internal_hosts: list[str] | None = None) -> tuple[str, dict[str, str]]:
        return url, {}

    monkeypatch.setattr(
        "myrm_agent_harness.core.security.http.secure_fetch.async_pin_url",
        _no_pin,
    )


@pytest.fixture
def no_async_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())


class TestOpenAISoraProviderMetadata:
    def test_provider_id_is_openai(self) -> None:
        p = OpenAISoraProvider()
        assert p.provider_id == "openai"

    def test_default_model(self) -> None:
        p = OpenAISoraProvider()
        assert p.default_model == "sora"

    def test_capabilities(self) -> None:
        caps = OpenAISoraProvider().capabilities
        assert caps.max_videos == 1
        assert caps.max_duration_seconds == 12


class TestOpenAISoraHelpers:
    def test_resolve_duration_clamp_to_nearest(self) -> None:
        assert _resolve_duration(6) == "4"

    def test_resolve_duration_none(self) -> None:
        assert _resolve_duration(None) is None

    def test_resolve_size_9_16(self) -> None:
        assert _resolve_size("9:16", None) == "720x1280"


class TestOpenAISoraDownload:
    @pytest.mark.asyncio
    @respx.mock
    async def test_generate_downloads_video(self, no_async_sleep: None) -> None:
        cfg = _cfg()
        base = cfg.base_url or "https://api.openai.com/v1"
        respx.post(f"{base}/videos").mock(return_value=Response(200, json={"id": "vid-1"}))
        respx.get(f"{base}/videos/vid-1").mock(return_value=Response(200, json={"id": "vid-1", "status": "completed"}))
        respx.get(f"{base}/videos/vid-1/content", params={"variant": "video"}).mock(
            return_value=Response(200, content=b"\x00\x01\x02")
        )

        provider = OpenAISoraProvider()
        out = await provider.generate("hello sora", cfg)

        assert len(out.assets) == 1
        assert out.assets[0].data == b"\x00\x01\x02"
        assert out.assets[0].filename == "video-vid-1.mp4"

    @pytest.mark.asyncio
    @respx.mock
    async def test_download_exceeds_max_size_raises(self, no_async_sleep: None) -> None:
        cfg = _cfg(max_download_bytes=50)
        base = cfg.base_url or "https://api.openai.com/v1"
        respx.post(f"{base}/videos").mock(return_value=Response(200, json={"id": "vid-big"}))
        respx.get(f"{base}/videos/vid-big").mock(
            return_value=Response(200, json={"id": "vid-big", "status": "completed"})
        )
        respx.get(f"{base}/videos/vid-big/content", params={"variant": "video"}).mock(
            return_value=Response(200, content=b"\x00" * 100)
        )

        provider = OpenAISoraProvider()
        with pytest.raises(ValueError, match="exceeds max download size"):
            await provider.generate("big video", cfg)
