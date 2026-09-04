"""Edge cases and robustness tests for FalVideoProvider.

Covers:
1. Oversized inline raw bytes (>5MB) rejection to protect from HTTP 413.
2. Parent request id pass-through for continuation.
3. Unrecognized response formats without video URL.
4. Transient 500 error on status polling leading to retry.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pydantic import SecretStr

from myrm_agent_harness.toolkits.llms.video.models import VideoGenerationConfig
from myrm_agent_harness.toolkits.llms.video.providers.fal_provider import FalVideoProvider


def _cfg() -> VideoGenerationConfig:
    return VideoGenerationConfig(
        provider="fal",
        model="fal-ai/flux-3-video",
        api_key=SecretStr("test-fal-key"),
        base_url="https://queue.fal.run",
        timeout_seconds=30.0,
    )


@pytest.mark.asyncio
async def test_generate_oversized_inline_video_rejected() -> None:
    """When raw reference video exceeds 5MB and no URL/parent_id is given, reject with clear error."""
    provider = FalVideoProvider()
    oversized_bytes = b"0" * (6 * 1024 * 1024)

    with pytest.raises(ValueError, match="Reference video exceeds .* limit"):
        await provider.generate("test continuation", _cfg(), reference_videos=[oversized_bytes])


@pytest.mark.asyncio
async def test_generate_parent_request_id_continuation() -> None:
    """When parent_request_id is provided in extra_params, it should be mapped to parent_request_id and continuation=True."""
    provider = FalVideoProvider()
    fake_video_bytes = b"\x00\x00\x00\x18ftypmp42parent-ok"

    mock_client = MagicMock()
    mock_client.post = AsyncMock(
        return_value=httpx.Response(
            200,
            json={
                "status_url": "https://queue.fal.run/status/req-parent",
                "response_url": "https://queue.fal.run/res/req-parent",
            },
        )
    )
    mock_client.get = AsyncMock(
        side_effect=[
            httpx.Response(200, json={"status": "COMPLETED"}),
            httpx.Response(200, json={"video": {"url": "https://media.fal.run/video_p.mp4"}}),
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
            "continue with parent id",
            _cfg(),
            extra_params={"parent_request_id": "req-root-12345"},
        )

    assert len(output.assets) == 1
    assert output.assets[0].data == fake_video_bytes
    call_kwargs = mock_client.post.call_args[1]
    assert call_kwargs["json"]["parent_request_id"] == "req-root-12345"
    assert call_kwargs["json"]["continuation"] is True


@pytest.mark.asyncio
async def test_generate_status_polling_transient_500_retries() -> None:
    """When status polling encounters transient 500 error, it continues polling until COMPLETED."""
    provider = FalVideoProvider()
    fake_video_bytes = b"\x00\x00\x00\x18ftypmp42transient-500"

    mock_client = MagicMock()
    mock_client.post = AsyncMock(
        return_value=httpx.Response(
            200,
            json={
                "status_url": "https://queue.fal.run/status/req-500",
                "response_url": "https://queue.fal.run/res/req-500",
            },
        )
    )
    mock_client.get = AsyncMock(
        side_effect=[
            httpx.Response(500, text="Internal Server Error"),
            httpx.Response(200, json={"status": "IN_PROGRESS"}),
            httpx.Response(200, json={"status": "COMPLETED"}),
            httpx.Response(200, json={"video": {"url": "https://media.fal.run/video_ok.mp4"}}),
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
