import os
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.huggingface.huggingface_agent_tools import create_huggingface_inference_tool
from myrm_agent_harness.utils.errors import ToolError


@pytest.fixture
def hf_tool():
    return create_huggingface_inference_tool()


@pytest.mark.asyncio
async def test_hf_tool_missing_token(hf_tool):
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ToolError, match="HF_TOKEN environment variable is not set"):
            await hf_tool.ainvoke(
                {"model_id": "test", "task": "test", "inputs": "test"}
            )


@pytest.mark.asyncio
async def test_hf_tool_image_response(hf_tool):
    with patch.dict(os.environ, {"HF_TOKEN": "test_token"}):
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "image/jpeg"}
        mock_response.content = b"fake_image_data"
        mock_response.raise_for_status = lambda: None

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_client):
            # httpx.AsyncClient used as context manager returns the client itself
            mock_client.__aenter__.return_value = mock_client

            result = await hf_tool.ainvoke(
                {"model_id": "model", "task": "text-to-image", "inputs": "cat"}
            )

            assert "![Generated Image](data:image/jpeg;base64," in result


@pytest.mark.asyncio
async def test_hf_tool_503_loading(hf_tool):
    with patch.dict(os.environ, {"HF_TOKEN": "test_token"}):
        mock_response = AsyncMock()
        mock_response.status_code = 503
        mock_response.json = lambda: {"estimated_time": 42.5}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_client):
            mock_client.__aenter__.return_value = mock_client

            with pytest.raises(ToolError, match="Estimated time: 42.5s"):
                await hf_tool.ainvoke(
                    {"model_id": "model", "task": "text-to-image", "inputs": "cat"}
                )
