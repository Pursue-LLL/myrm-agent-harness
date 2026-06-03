"""Tests for ImageGenerator: failover, metrics, cancellation, SecretStr, truncation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import SecretStr

from myrm_agent_harness.toolkits.llms.image.generator import (
    ImageGenerationConfig,
    ImageGenerationError,
    ImageGenerator,
    _safe_truncate,
)


@dataclass
class _FakeImageData:
    url: str | None = "https://example.com/img.png"
    b64_json: str | None = None
    revised_prompt: str | None = "revised prompt"


@dataclass
class _FakeResponse:
    data: list[_FakeImageData]


class TestSafeTruncate:
    def test_short_message(self) -> None:
        assert _safe_truncate("hello") == "hello"

    def test_long_message(self) -> None:
        msg = "x" * 600
        result = _safe_truncate(msg, max_len=100)
        assert len(result) < 120
        assert result.endswith("... [truncated]")


class TestSecretStr:
    def test_api_key_is_secret(self) -> None:
        config = ImageGenerationConfig(api_key=SecretStr("sk-secret-key"))
        assert "sk-secret-key" not in repr(config)
        assert "sk-secret-key" not in str(config)

    def test_api_key_none(self) -> None:
        config = ImageGenerationConfig()
        assert config.api_key is None


class TestImageGeneratorMetrics:
    @pytest.mark.asyncio()
    async def test_metrics_increment_on_success(self) -> None:
        config = ImageGenerationConfig(model="dall-e-3")
        gen = ImageGenerator(config)

        assert gen.call_count == 0
        assert gen.error_count == 0
        assert gen.total_latency_ms == 0.0

        with patch("litellm.aimage_generation", new_callable=AsyncMock) as mock:
            mock.return_value = _FakeResponse(data=[_FakeImageData()])
            await gen.generate("test prompt")

        assert gen.call_count == 1
        assert gen.error_count == 0
        assert gen.total_latency_ms > 0

    @pytest.mark.asyncio()
    async def test_metrics_error_count(self) -> None:
        config = ImageGenerationConfig(model="dall-e-3", max_retries=0)
        gen = ImageGenerator(config)

        with patch("litellm.aimage_generation", new_callable=AsyncMock) as mock:
            mock.side_effect = RuntimeError("API down")
            with pytest.raises(ImageGenerationError):
                await gen.generate("test prompt")

        assert gen.call_count == 1
        assert gen.error_count == 1


class TestFailover:
    @pytest.mark.asyncio()
    async def test_failover_to_second_model(self) -> None:
        config = ImageGenerationConfig(
            model="primary-model",
            fallback_models=["fallback-model"],
            max_retries=0,
        )
        gen = ImageGenerator(config)

        call_count = 0

        async def mock_generate(**kwargs: object) -> _FakeResponse:
            nonlocal call_count
            call_count += 1
            model = kwargs.get("model", "")
            if model == "primary-model":
                raise RuntimeError("Primary failed")
            return _FakeResponse(data=[_FakeImageData(url=f"https://img/{model}")])

        with patch("litellm.aimage_generation", side_effect=mock_generate):
            result = await gen.generate("test prompt")

        assert result.model == "fallback-model"
        assert result.url == "https://img/fallback-model"
        assert len(result.attempts) == 1
        assert result.attempts[0].model == "primary-model"

    @pytest.mark.asyncio()
    async def test_all_models_fail(self) -> None:
        config = ImageGenerationConfig(
            model="m1",
            fallback_models=["m2", "m3"],
            max_retries=0,
        )
        gen = ImageGenerator(config)

        with patch("litellm.aimage_generation", new_callable=AsyncMock) as mock:
            mock.side_effect = RuntimeError("all fail")
            with pytest.raises(ImageGenerationError, match="All 3 models failed"):
                await gen.generate("test")

    @pytest.mark.asyncio()
    async def test_primary_success_no_failover(self) -> None:
        config = ImageGenerationConfig(
            model="primary",
            fallback_models=["fallback"],
        )
        gen = ImageGenerator(config)

        with patch("litellm.aimage_generation", new_callable=AsyncMock) as mock:
            mock.return_value = _FakeResponse(data=[_FakeImageData()])
            result = await gen.generate("test")

        assert result.model == "primary"
        assert result.attempts == []


class TestEditFailover:
    """Verify BinaryIO data is preserved across failover retries."""

    @pytest.mark.asyncio()
    async def test_edit_failover_preserves_image_data(self) -> None:
        config = ImageGenerationConfig(
            model="primary",
            fallback_models=["fallback"],
            max_retries=0,
        )
        gen = ImageGenerator(config)
        image_data = b"PNG-image-content-here"
        received_images: list[bytes] = []

        async def mock_edit(**kwargs: object) -> _FakeResponse:
            img_io = kwargs.get("image")
            if img_io is not None:
                received_images.append(img_io.read())  # type: ignore[union-attr]
            model = kwargs.get("model", "")
            if model == "primary":
                raise RuntimeError("Primary edit failed")
            return _FakeResponse(data=[_FakeImageData()])

        with patch("litellm.aimage_edit", side_effect=mock_edit):
            result = await gen.edit(image_data, "edit prompt")

        assert result.model == "fallback"
        assert len(received_images) == 2
        assert received_images[0] == image_data
        assert received_images[1] == image_data


class TestCancellation:
    @pytest.mark.asyncio()
    async def test_cancellation_before_call(self) -> None:
        config = ImageGenerationConfig(model="dall-e-3", max_retries=0)
        gen = ImageGenerator(config)

        cancel = asyncio.Event()
        cancel.set()

        with pytest.raises(ImageGenerationError, match="cancelled"):
            await gen.generate("test", cancellation_event=cancel)


class TestMediaCallback:
    @pytest.mark.asyncio()
    async def test_callback_invoked_on_b64(self) -> None:
        import base64

        callback = AsyncMock(return_value="https://storage/persisted.png")
        config = ImageGenerationConfig(
            model="dall-e-3",
            media_callback=callback,
        )
        gen = ImageGenerator(config)

        b64_data = base64.b64encode(b"fake-image-bytes").decode()

        try:
            import litellm
            with patch.object(litellm, "aimage_generation", new_callable=AsyncMock) as mock:
                mock.return_value = _FakeResponse(data=[_FakeImageData(url=None, b64_json=b64_data)])
                result = await gen.generate("test")
                assert result.persisted_url == "https://storage/persisted.png"
                callback.assert_called_once()
        except (ImportError, AttributeError):
            with patch("myrm_agent_harness.toolkits.llms.image.generator.litellm") as mock_litellm:
                mock_litellm.aimage_generation = AsyncMock(return_value=_FakeResponse(data=[_FakeImageData(url=None, b64_json=b64_data)]))
                result = await gen.generate("test")
                assert result.persisted_url == "https://storage/persisted.png"
                callback.assert_called_once()

    @pytest.mark.asyncio()
    async def test_callback_invoked_on_url_result(self) -> None:
        """URL results are downloaded then persisted via callback."""
        callback = AsyncMock(return_value="https://storage/persisted.png")
        config = ImageGenerationConfig(
            model="dall-e-3",
            media_callback=callback,
        )
        gen = ImageGenerator(config)

        fake_image_bytes = b"downloaded-image-content"

        try:
            import litellm
            with (
                patch.object(litellm, "aimage_generation", new_callable=AsyncMock) as mock_gen,
                patch(
                    "myrm_agent_harness.toolkits.llms.image.models.ImageResult.to_bytes_with_mime",
                    new_callable=AsyncMock,
                    return_value=(fake_image_bytes, "image/png"),
                ),
            ):
                mock_gen.return_value = _FakeResponse(data=[_FakeImageData(url="https://api/img.png", b64_json=None)])
                result = await gen.generate("test")

                assert result.persisted_url == "https://storage/persisted.png"
                assert result.mime_type == "image/png"
                callback.assert_called_once()
                call_args = callback.call_args
                assert call_args[0][0] == fake_image_bytes
                assert call_args[0][1] == "image/png"
        except (ImportError, AttributeError):
            with (
                patch("myrm_agent_harness.toolkits.llms.image.generator.litellm") as mock_litellm,
                patch(
                    "myrm_agent_harness.toolkits.llms.image.models.ImageResult.to_bytes_with_mime",
                    new_callable=AsyncMock,
                    return_value=(fake_image_bytes, "image/png"),
                ),
            ):
                mock_litellm.aimage_generation = AsyncMock(return_value=_FakeResponse(data=[_FakeImageData(url="https://api/img.png", b64_json=None)]))
                result = await gen.generate("test")

                assert result.persisted_url == "https://storage/persisted.png"
                assert result.mime_type == "image/png"
                callback.assert_called_once()
                call_args = callback.call_args
                assert call_args[0][0] == fake_image_bytes
                assert call_args[0][1] == "image/png"

    @pytest.mark.asyncio()
    async def test_no_callback_without_config(self) -> None:
        """No persistence when media_callback is not configured."""
        config = ImageGenerationConfig(model="dall-e-3")
        gen = ImageGenerator(config)

        try:
            import litellm
            with patch.object(litellm, "aimage_generation", new_callable=AsyncMock) as mock:
                mock.return_value = _FakeResponse(data=[_FakeImageData(url="https://api/img.png", b64_json=None)])
                result = await gen.generate("test")
                assert result.persisted_url is None
        except (ImportError, AttributeError):
            with patch("myrm_agent_harness.toolkits.llms.image.generator.litellm") as mock_litellm:
                mock_litellm.aimage_generation = AsyncMock(return_value=_FakeResponse(data=[_FakeImageData(url="https://api/img.png", b64_json=None)]))
                result = await gen.generate("test")
                assert result.persisted_url is None

    @pytest.mark.asyncio()
    async def test_callback_failure_does_not_break_generation(self) -> None:
        """Persistence failure is swallowed — generation result still returned."""
        callback = AsyncMock(side_effect=OSError("storage unavailable"))
        config = ImageGenerationConfig(
            model="dall-e-3",
            media_callback=callback,
        )
        gen = ImageGenerator(config)

        try:
            import litellm
            with (
                patch.object(litellm, "aimage_generation", new_callable=AsyncMock) as mock_gen,
                patch(
                    "myrm_agent_harness.toolkits.llms.image.models.ImageResult.to_bytes_with_mime",
                    new_callable=AsyncMock,
                    return_value=(b"image-bytes", "image/png"),
                ),
            ):
                mock_gen.return_value = _FakeResponse(data=[_FakeImageData(url="https://api/img.png")])
                result = await gen.generate("test")

                assert result.url == "https://api/img.png"
                assert result.persisted_url is None
                assert gen.call_count == 1
                assert gen.error_count == 0
        except (ImportError, AttributeError):
            with (
                patch("myrm_agent_harness.toolkits.llms.image.generator.litellm") as mock_litellm,
                patch(
                    "myrm_agent_harness.toolkits.llms.image.models.ImageResult.to_bytes_with_mime",
                    new_callable=AsyncMock,
                    return_value=(b"image-bytes", "image/png"),
                ),
            ):
                mock_litellm.aimage_generation = AsyncMock(return_value=_FakeResponse(data=[_FakeImageData(url="https://api/img.png")]))
                result = await gen.generate("test")

                assert result.url == "https://api/img.png"
                assert result.persisted_url is None
                assert gen.call_count == 1
                assert gen.error_count == 0
