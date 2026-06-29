import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.config.llm import LLMConfig
from myrm_agent_harness.toolkits.llms.vision.fallback_engine import VisionFallbackEngine


@pytest.fixture
def mock_llm_config():
    return LLMConfig(
        model="gpt-4o-mini",
        api_key="test-key"
    )

@pytest.fixture
def fallback_engine(mock_llm_config):
    with patch("myrm_agent_harness.toolkits.llms.vision.fallback_engine.create_litellm_model") as mock_create:
        mock_model = AsyncMock()
        mock_create.return_value = mock_model
        engine = VisionFallbackEngine(mock_llm_config)
        engine.model = mock_model
        yield engine

@pytest.mark.asyncio
async def test_describe_image_b64_success(fallback_engine):
    # Setup mock response
    mock_response = MagicMock()
    mock_response.content = "A beautiful diagram"
    fallback_engine.model.ainvoke.return_value = mock_response

    result = await fallback_engine.describe_image_b64("dummyb64", "image/png")
    assert result == "A beautiful diagram"
    fallback_engine.model.ainvoke.assert_called_once()

@pytest.mark.asyncio
async def test_describe_image_b64_reactive_resize(fallback_engine):
    # Setup mock response to fail with 413, then succeed
    mock_response_success = MagicMock()
    mock_response_success.content = "Compressed diagram"

    # 第一次报错 413，第二次成功
    fallback_engine.model.ainvoke.side_effect = [
        Exception("413 Payload Too Large"),
        mock_response_success
    ]

    with patch("myrm_agent_harness.toolkits.llms.vision.fallback_engine.image_compressor") as mock_compressor:
        mock_compressor.compress.return_value = b"compressed_dummy_bytes"
        result = await fallback_engine.describe_image_b64(base64.b64encode(b"dummy").decode(), "image/png")

        assert result == "Compressed diagram"
        assert fallback_engine.model.ainvoke.call_count == 2
        mock_compressor.compress.assert_called_once()

@pytest.mark.asyncio
async def test_describe_image_b64_reactive_resize_fails(fallback_engine):
    # Setup mock response to fail with 413, and compression returns None
    fallback_engine.model.ainvoke.side_effect = Exception("413 Payload Too Large")

    with patch("myrm_agent_harness.toolkits.llms.vision.fallback_engine.image_compressor") as mock_compressor:
        mock_compressor.compress.return_value = None
        result = await fallback_engine.describe_image_b64(base64.b64encode(b"dummy").decode(), "image/png")

        assert "Vision Analysis Failed" in result
        assert fallback_engine.model.ainvoke.call_count == 1

@pytest.mark.asyncio
async def test_describe_images_b64(fallback_engine):
    mock_response1 = MagicMock()
    mock_response1.content = "img1"
    mock_response2 = MagicMock()
    mock_response2.content = "img2"

    fallback_engine.model.ainvoke.side_effect = [mock_response1, mock_response2]

    images = [("b64_1", "image/jpeg"), ("b64_2", "image/png")]
    results = await fallback_engine.describe_images_b64(images)

    assert results == ["img1", "img2"]

@pytest.mark.asyncio
async def test_describe_local_image(fallback_engine):
    mock_response = MagicMock()
    mock_response.content = "local img"
    fallback_engine.model.ainvoke.return_value = mock_response

    mock_executor = AsyncMock()
    mock_executor.read_file_bytes.return_value = b"filebytes"

    result = await fallback_engine.describe_local_image("test.png", mock_executor)

    assert result == "local img"
    mock_executor.read_file_bytes.assert_called_once_with("test.png")

@pytest.mark.asyncio
async def test_describe_local_image_read_failure(fallback_engine):
    mock_executor = AsyncMock()
    mock_executor.read_file_bytes.side_effect = OSError("Permission denied")

    result = await fallback_engine.describe_local_image("secret.png", mock_executor)

    assert "Failed to read local image" in result

@pytest.mark.asyncio
async def test_describe_image_b64_compression_returns_empty(fallback_engine):
    fallback_engine.model.ainvoke.side_effect = Exception("413 Payload Too Large")

    with patch("myrm_agent_harness.toolkits.llms.vision.fallback_engine.image_compressor") as mock_compressor:
        mock_compressor.compress.return_value = b""
        result = await fallback_engine.describe_image_b64(base64.b64encode(b"dummy").decode(), "image/png")

        assert "Vision Analysis Failed" in result
        mock_compressor.compress.assert_called_once()

@pytest.mark.asyncio
async def test_describe_image_b64_compression_raises(fallback_engine):
    fallback_engine.model.ainvoke.side_effect = Exception("413 Payload Too Large")

    with patch("myrm_agent_harness.toolkits.llms.vision.fallback_engine.image_compressor") as mock_compressor:
        mock_compressor.compress.side_effect = RuntimeError("compress boom")
        result = await fallback_engine.describe_image_b64(base64.b64encode(b"dummy").decode(), "image/png")

        assert "Vision Analysis Failed" in result
