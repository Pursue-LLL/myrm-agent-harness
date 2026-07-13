"""Tests for reference image support: download, routing, warning, SSRF validation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.llms.image.generator import (
    ImageGenerationConfig,
    ImageGenerator,
    _download_reference_images,
)
from myrm_agent_harness.toolkits.llms.image.models import ImageResult


@dataclass
class _FakeImageData:
    url: str | None = "https://example.com/result.png"
    b64_json: str | None = None
    revised_prompt: str | None = None


@dataclass
class _FakeResponse:
    data: list[_FakeImageData]


class TestDownloadReferenceImages:
    @pytest.mark.asyncio()
    async def test_successful_download(self) -> None:
        fake_data = b"PNG-image-content"
        mock_resp = MagicMock()
        mock_resp.content = fake_data
        mock_resp.raise_for_status = MagicMock()

        with patch(
            "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            result = await _download_reference_images(["https://example.com/ref.png"])

        assert len(result) == 1
        assert result[0] == fake_data

    @pytest.mark.asyncio()
    async def test_oversized_image_skipped(self, caplog: pytest.LogCaptureFixture) -> None:
        huge_data = b"x" * (11 * 1024 * 1024)
        mock_resp = MagicMock()
        mock_resp.content = huge_data
        mock_resp.raise_for_status = MagicMock()

        with (
            patch(
                "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ),
            caplog.at_level(logging.WARNING, logger="myrm_agent_harness.toolkits.llms.image.generator"),
        ):
            result = await _download_reference_images(["https://example.com/huge.png"])

        assert len(result) == 0
        assert "too large" in caplog.text

    @pytest.mark.asyncio()
    async def test_download_failure_skipped(self, caplog: pytest.LogCaptureFixture) -> None:
        """secure_get raises → logged and skipped."""
        with (
            patch(
                "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
                new_callable=AsyncMock,
                side_effect=Exception("Connection refused"),
            ),
            caplog.at_level(logging.WARNING, logger="myrm_agent_harness.toolkits.llms.image.generator"),
        ):
            result = await _download_reference_images(["https://example.com/missing.png"])

        assert len(result) == 0
        assert "Failed to download" in caplog.text

    @pytest.mark.asyncio()
    async def test_empty_urls_returns_empty(self) -> None:
        result = await _download_reference_images([])
        assert result == []


class TestGenerateWithReferences:
    @pytest.mark.asyncio()
    async def test_routes_to_edit(self) -> None:
        config = ImageGenerationConfig(model="gpt-image-1", max_retries=0)
        gen = ImageGenerator(config)

        with (
            patch.object(gen, "edit", new_callable=AsyncMock) as mock_edit,
            patch(
                "myrm_agent_harness.toolkits.llms.image.generator._download_reference_images",
                new_callable=AsyncMock,
                return_value=[b"ref-image-bytes"],
            ),
        ):
            mock_edit.return_value = ImageResult(
                url="https://example.com/edited.png",
                b64_json=None,
                revised_prompt=None,
                model="gpt-image-1",
                latency_ms=500.0,
            )
            result = await gen.generate(
                "edit the image",
                reference_image_urls=["https://example.com/ref.png"],
            )

        assert result.url == "https://example.com/edited.png"
        mock_edit.assert_called_once_with(
            image=b"ref-image-bytes",
            prompt="edit the image",
            size=None,
            n=1,
            cancellation_event=None,
        )

    @pytest.mark.asyncio()
    async def test_multi_ref_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        config = ImageGenerationConfig(model="gpt-image-1", max_retries=0)
        gen = ImageGenerator(config)

        with (
            patch.object(gen, "edit", new_callable=AsyncMock) as mock_edit,
            patch(
                "myrm_agent_harness.toolkits.llms.image.generator._download_reference_images",
                new_callable=AsyncMock,
                return_value=[b"ref1", b"ref2", b"ref3"],
            ),
            caplog.at_level(logging.WARNING, logger="myrm_agent_harness.toolkits.llms.image.generator"),
        ):
            mock_edit.return_value = ImageResult(
                url="https://example.com/edited.png",
                b64_json=None,
                revised_prompt=None,
                model="gpt-image-1",
            )
            await gen.generate(
                "test",
                reference_image_urls=["url1", "url2", "url3"],
            )

        assert "Only 1 reference image supported" in caplog.text
        assert "3" in caplog.text
        mock_edit.assert_called_once()
        assert mock_edit.call_args.kwargs.get("image") == b"ref1" or mock_edit.call_args[1].get("image") == b"ref1"

    @pytest.mark.asyncio()
    async def test_fallback_when_download_fails(self) -> None:
        """When all reference images fail to download, falls back to regular generate."""
        config = ImageGenerationConfig(model="dall-e-3", max_retries=0)
        gen = ImageGenerator(config)

        with (
            patch(
                "myrm_agent_harness.toolkits.llms.image.generator._download_reference_images",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch("litellm.aimage_generation", new_callable=AsyncMock) as mock_gen,
        ):
            mock_gen.return_value = _FakeResponse(data=[_FakeImageData()])
            result = await gen.generate(
                "test",
                reference_image_urls=["https://example.com/bad.png"],
            )

        assert result.url == "https://example.com/result.png"
        mock_gen.assert_called_once()
