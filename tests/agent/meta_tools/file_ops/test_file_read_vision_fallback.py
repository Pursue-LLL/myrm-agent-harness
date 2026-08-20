import base64
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.runnables import RunnableConfig

from myrm_agent_harness.agent.meta_tools.file_ops.core.file_read_handlers import (
    build_multimodal_result as _build_multimodal_result,
)


_DUMMY_CONFIG = RunnableConfig()
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.mark.asyncio
async def test_build_multimodal_result_native_vision_success():
    """Vision-supported models receive native ImageContentBlock directly."""
    mock_executor = AsyncMock()
    mock_executor.read_file_bytes.return_value = _TINY_PNG

    blocks = await _build_multimodal_result(
        image_paths=["test.png"],
        pdf_paths=[],
        document_paths=[],
        text_paths=[],
        vault_paths=[],
        executor=mock_executor,
        skills=None,
        reason=None,
        url_errors=[],
        supports_vision=True,
        config=_DUMMY_CONFIG,
    )

    assert len(blocks) >= 1
    # Either returns text info block + image block or image block
    block_types = [
        getattr(b, "type", b.get("type") if isinstance(b, dict) else None)
        for b in blocks
    ]
    assert "image_url" in block_types or any("image" in str(b) for b in blocks)
    mock_executor.read_file_bytes.assert_called_once_with("test.png")


@pytest.mark.asyncio
async def test_build_multimodal_result_vision_fallback_success():
    """Text-only models fall back gracefully to structured text descriptions."""
    mock_executor = AsyncMock()
    mock_executor.read_file_bytes.return_value = b"dummy"

    vision_fallback_model_cfg = {"model": "gpt-4o-mini", "api_key": "test"}

    with patch(
        "myrm_agent_harness.toolkits.llms.vision.fallback_engine.VisionFallbackEngine.describe_local_image",
        new_callable=AsyncMock,
    ) as mock_describe:
        mock_describe.return_value = "A mock fallback text description"

        blocks = await _build_multimodal_result(
            image_paths=["test.png"],
            pdf_paths=[],
            document_paths=[],
            text_paths=[],
            vault_paths=[],
            executor=mock_executor,
            skills=None,
            reason=None,
            url_errors=[],
            supports_vision=False,
            vision_fallback_model_cfg=vision_fallback_model_cfg,
            config=_DUMMY_CONFIG,
        )

        assert len(blocks) == 1
        assert "A mock fallback text description" in blocks[0]["text"]
        mock_describe.assert_called_once_with("test.png", mock_executor)


@pytest.mark.asyncio
async def test_build_multimodal_result_vision_fallback_failure():
    """Fallback failure degrades gracefully without crashing."""
    mock_executor = AsyncMock()

    vision_fallback_model_cfg = {"model": "gpt-4o-mini", "api_key": "test"}

    with patch(
        "myrm_agent_harness.toolkits.llms.vision.fallback_engine.VisionFallbackEngine.describe_local_image",
        new_callable=AsyncMock,
    ) as mock_describe:
        mock_describe.side_effect = Exception("Fallback API Error")

        blocks = await _build_multimodal_result(
            image_paths=["test.png"],
            pdf_paths=[],
            document_paths=[],
            text_paths=[],
            vault_paths=[],
            executor=mock_executor,
            skills=None,
            reason=None,
            url_errors=[],
            supports_vision=False,
            vision_fallback_model_cfg=vision_fallback_model_cfg,
            config=_DUMMY_CONFIG,
        )

        assert len(blocks) == 1
        assert "Vision analysis unavailable" in blocks[0]["text"]


@pytest.mark.asyncio
async def test_build_multimodal_result_no_vision_no_fallback():
    """Text-only model without fallback configured returns path & metadata."""
    mock_executor = AsyncMock()
    mock_executor.read_file_bytes.return_value = _TINY_PNG

    blocks = await _build_multimodal_result(
        image_paths=["test.png"],
        pdf_paths=[],
        document_paths=[],
        text_paths=[],
        vault_paths=[],
        executor=mock_executor,
        skills=None,
        reason=None,
        url_errors=[],
        supports_vision=False,
        vision_fallback_model_cfg=None,
        vision_fallback_model_cfgs=None,
        config=_DUMMY_CONFIG,
    )

    assert len(blocks) == 1
    assert "Current model does not support vision" in blocks[0]["text"]
