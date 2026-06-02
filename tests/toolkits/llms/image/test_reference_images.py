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
from myrm_agent_harness.toolkits.llms.image.validator import (
    ImageValidator,
    ValidationError,
)


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
        mock_resp = AsyncMock()
        mock_resp.read = AsyncMock(return_value=fake_data)
        mock_resp.raise_for_status = MagicMock()
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock()

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await _download_reference_images(["https://example.com/ref.png"])

        assert len(result) == 1
        assert result[0] == fake_data

    @pytest.mark.asyncio()
    async def test_oversized_image_skipped(self, caplog: pytest.LogCaptureFixture) -> None:
        huge_data = b"x" * (11 * 1024 * 1024)
        mock_resp = AsyncMock()
        mock_resp.read = AsyncMock(return_value=huge_data)
        mock_resp.raise_for_status = MagicMock()
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock()

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        with (
            patch("aiohttp.ClientSession", return_value=mock_session),
            caplog.at_level(logging.WARNING, logger="myrm_agent_harness.toolkits.llms.image.generator"),
        ):
            result = await _download_reference_images(["https://example.com/huge.png"])

        assert len(result) == 0
        assert "too large" in caplog.text

    @pytest.mark.asyncio()
    async def test_download_failure_skipped(self, caplog: pytest.LogCaptureFixture) -> None:
        """session.get raises on context entry → logged and skipped."""
        mock_session = AsyncMock()
        mock_session.get = MagicMock(side_effect=Exception("Connection refused"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        with (
            patch("aiohttp.ClientSession", return_value=mock_session),
            caplog.at_level(logging.WARNING, logger="myrm_agent_harness.toolkits.llms.image.generator"),
        ):
            result = await _download_reference_images(["https://example.com/missing.png"])

        assert len(result) == 0
        assert "Failed to download" in caplog.text

    @pytest.mark.asyncio()
    async def test_empty_urls_returns_empty(self) -> None:
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        with patch("aiohttp.ClientSession", return_value=mock_session):
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


class TestValidateReferenceUrl:
    def test_ssrf_blocks_localhost(self) -> None:
        validator = ImageValidator(ssrf_protection=True)
        with pytest.raises(ValidationError, match="not allowed"):
            validator.validate_reference_url("http://localhost/image.png")

    def test_ssrf_blocks_private_ip(self) -> None:
        validator = ImageValidator(ssrf_protection=True)
        with pytest.raises(ValidationError, match="private"):
            validator.validate_reference_url("http://192.168.1.1/image.png")

    def test_ssrf_allows_public(self) -> None:
        validator = ImageValidator(ssrf_protection=True)
        validator.validate_reference_url("https://example.com/image.png")

    def test_ssrf_disabled_allows_anything(self) -> None:
        validator = ImageValidator(ssrf_protection=False)
        validator.validate_reference_url("http://localhost/image.png")
