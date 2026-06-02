from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool import (
    _build_multimodal_result,
)


@pytest.mark.asyncio
async def test_build_multimodal_result_vision_fallback_success():
    mock_executor = AsyncMock()
    mock_executor.read_file_bytes.return_value = b"dummy"

    vision_fallback_model_cfg = {"model": "gpt-4o-mini", "api_key": "test"}

    with patch(
        "myrm_agent_harness.toolkits.vision.fallback_engine.VisionFallbackEngine.describe_local_image",
        new_callable=AsyncMock,
    ) as mock_describe:
        mock_describe.return_value = "A mock fallback text description"

        blocks = await _build_multimodal_result(
            image_paths=["test.png"],
            pdf_paths=[],
            document_paths=[],
            text_paths=[],
            executor=mock_executor,
            skills=None,
            reason=None,
            url_errors=[],
            supports_vision=False,
            vision_fallback_model_cfg=vision_fallback_model_cfg,
        )

        assert len(blocks) == 1
        assert "A mock fallback text description" in blocks[0]["text"]
        mock_describe.assert_called_once_with("test.png", mock_executor)


@pytest.mark.asyncio
async def test_build_multimodal_result_vision_fallback_failure():
    mock_executor = AsyncMock()

    vision_fallback_model_cfg = {"model": "gpt-4o-mini", "api_key": "test"}

    with patch(
        "myrm_agent_harness.toolkits.vision.fallback_engine.VisionFallbackEngine.describe_local_image",
        new_callable=AsyncMock,
    ) as mock_describe:
        mock_describe.side_effect = Exception("Fallback API Error")

        blocks = await _build_multimodal_result(
            image_paths=["test.png"],
            pdf_paths=[],
            document_paths=[],
            text_paths=[],
            executor=mock_executor,
            skills=None,
            reason=None,
            url_errors=[],
            supports_vision=False,
            vision_fallback_model_cfg=vision_fallback_model_cfg,
        )

        assert len(blocks) == 1
        assert "Vision fallback failed" in blocks[0]["text"]
        assert "Fallback API Error" in blocks[0]["text"]
