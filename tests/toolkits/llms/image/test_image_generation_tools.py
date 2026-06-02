"""Tests for ImageGenerationTools: generate, edit, list, SSRF validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.llms.image.image_engine import (
    ImageGenerationTools,
    _format_result,
)
from myrm_agent_harness.toolkits.llms.image.models import (
    FailoverAttempt,
    ImageGenerationConfig,
    ImageResult,
)


@dataclass
class _FakeImageData:
    url: str | None = "https://example.com/img.png"
    b64_json: str | None = None
    revised_prompt: str | None = "revised"


@dataclass
class _FakeResponse:
    data: list[_FakeImageData]


class TestGenerateImage:
    @pytest.mark.asyncio()
    async def test_successful_generation(self) -> None:
        config = ImageGenerationConfig(model="dall-e-3")
        tools = ImageGenerationTools(config)

        with patch("litellm.aimage_generation", new_callable=AsyncMock) as mock:
            mock.return_value = _FakeResponse(data=[_FakeImageData()])
            result_str = await tools.generate_image("a cat")

        result = json.loads(result_str)
        assert "image_url" in result
        assert result["model"] == "dall-e-3"

    @pytest.mark.asyncio()
    async def test_empty_prompt_rejected(self) -> None:
        config = ImageGenerationConfig(model="dall-e-3")
        tools = ImageGenerationTools(config)

        result_str = await tools.generate_image("")
        result = json.loads(result_str)
        assert "error" in result
        assert "empty" in result["error"].lower()

    @pytest.mark.asyncio()
    async def test_reference_url_ssrf_rejected(self) -> None:
        config = ImageGenerationConfig(model="dall-e-3")
        tools = ImageGenerationTools(config, ssrf_protection=True)

        result_str = await tools.generate_image(
            "a cat",
            reference_image_urls=["http://localhost/evil.png"],
        )
        result = json.loads(result_str)
        assert "error" in result
        assert "not allowed" in result["error"]

    @pytest.mark.asyncio()
    async def test_generation_error_handled(self) -> None:
        config = ImageGenerationConfig(model="dall-e-3", max_retries=0)
        tools = ImageGenerationTools(config)

        with patch("litellm.aimage_generation", new_callable=AsyncMock) as mock:
            mock.side_effect = RuntimeError("API error")
            result_str = await tools.generate_image("test")

        result = json.loads(result_str)
        assert "error" in result


class TestEditImage:
    @pytest.mark.asyncio()
    async def test_edit_not_supported(self) -> None:
        config = ImageGenerationConfig(model="dall-e-3")
        tools = ImageGenerationTools(config)

        result_str = await tools.edit_image(b"png-bytes", "edit it")
        result = json.loads(result_str)
        assert "error" in result
        assert "not support" in result["error"].lower()

    @pytest.mark.asyncio()
    async def test_edit_success(self) -> None:
        config = ImageGenerationConfig(model="gpt-image-1")
        tools = ImageGenerationTools(config)

        with patch("litellm.aimage_edit", new_callable=AsyncMock) as mock:
            mock.return_value = _FakeResponse(data=[_FakeImageData()])
            result_str = await tools.edit_image(b"png-bytes", "edit it")

        result = json.loads(result_str)
        assert "image_url" in result


class TestListModels:
    def test_list_models(self) -> None:
        config = ImageGenerationConfig(model="dall-e-3", fallback_models=["dall-e-2"])
        tools = ImageGenerationTools(config)

        result_str = tools.list_models()
        result = json.loads(result_str)
        assert "models" in result
        assert len(result["models"]) >= 7
        assert result["active_model"] == "dall-e-3"
        assert result["fallback_models"] == ["dall-e-2"]


class TestFormatResult:
    def test_url_result(self) -> None:
        result = ImageResult(
            url="https://example.com/img.png",
            b64_json=None,
            revised_prompt="revised",
            model="dall-e-3",
            latency_ms=1500.0,
        )
        output = json.loads(_format_result(result))
        assert output["image_url"] == "https://example.com/img.png"
        assert output["model"] == "dall-e-3"
        assert output["revised_prompt"] == "revised"
        assert output["latency_ms"] == 1500

    def test_persisted_url_preferred(self) -> None:
        result = ImageResult(
            url="https://temp.com/img.png",
            b64_json=None,
            revised_prompt=None,
            model="dall-e-3",
            persisted_url="https://storage.com/img.png",
        )
        output = json.loads(_format_result(result))
        assert output["image_url"] == "https://storage.com/img.png"

    def test_failover_attempts_included(self) -> None:
        result = ImageResult(
            url="https://x.com/img.png",
            b64_json=None,
            revised_prompt=None,
            model="dall-e-2",
            attempts=[FailoverAttempt(model="dall-e-3", error="failed", latency_ms=100)],
        )
        output = json.loads(_format_result(result))
        assert "failover_attempts" in output
        assert output["failover_attempts"][0]["model"] == "dall-e-3"


class TestToolMetadata:
    def test_tool_name(self) -> None:
        config = ImageGenerationConfig(model="dall-e-3")
        tools = ImageGenerationTools(config)
        assert tools.tool_name == "image_tool"

    def test_tool_description_contains_reference(self) -> None:
        config = ImageGenerationConfig(model="dall-e-3")
        tools = ImageGenerationTools(config)
        desc = tools.tool_description
        assert "reference_image_urls" in desc
        assert "dall-e-3" in desc
