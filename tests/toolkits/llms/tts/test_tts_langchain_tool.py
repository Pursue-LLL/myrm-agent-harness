import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.core.artifacts.constants import ArtifactType
from myrm_agent_harness.toolkits.llms.tts import TTSConfig, TTSTool, create_tts_tool


@pytest.fixture
def mock_config():
    return TTSConfig(provider="openai", api_key="test-key")


@pytest.fixture
def mock_engine_generate():
    with patch(
        "myrm_agent_harness.toolkits.llms.tts.tts_langchain_tool.AsyncTTSEngine.generate",
        new_callable=AsyncMock,
    ) as mock:
        yield mock


def test_tts_tool_init(mock_config):
    """Test TTSTool initialization."""
    mock_callback = MagicMock()
    tool = TTSTool(config=mock_config, on_artifact_created=mock_callback)

    assert tool.name == "tts_generate"
    assert tool.config == mock_config
    assert tool._on_artifact_created == mock_callback


def test_create_tts_tool_factory(mock_config):
    """Test create_tts_tool factory."""
    tool = create_tts_tool(mock_config)
    assert isinstance(tool, TTSTool)
    assert tool.name == "tts_generate"


def test_tts_tool_run_raises_not_implemented(mock_config):
    """Test synchronous run raises NotImplementedError."""
    tool = TTSTool(config=mock_config)
    with pytest.raises(NotImplementedError, match="TTSTool only supports async execution"):
        tool._run(text="hello")


@pytest.mark.asyncio
async def test_tts_tool_arun_success_with_artifact(mock_config, mock_engine_generate):
    """Test async run success with artifact push."""
    mock_callback = MagicMock()
    tool = TTSTool(config=mock_config, on_artifact_created=mock_callback)

    mock_result = MagicMock()
    mock_result.provider = "openai"
    mock_result.model = "tts-1"
    mock_result.latency_ms = 150.5
    mock_result.persisted_url = "s3://bucket/audio.mp3"
    mock_result.mime_type = "audio/mpeg"
    mock_engine_generate.return_value = mock_result

    result_str = await tool._arun(text="hello world")

    mock_engine_generate.assert_called_once_with("hello world")

    mock_callback.assert_called_once()
    args = mock_callback.call_args[0]
    assert args[0].startswith("generated_tts-1.mp3")
    assert args[1] == "s3://bucket/audio.mp3"
    assert args[2] == ArtifactType.AUDIO
    assert args[3] == "audio/mpeg"

    result_dict = json.loads(result_str)
    assert result_dict["status"] == "success"
    assert result_dict["audio_url"] == "s3://bucket/audio.mp3"


@pytest.mark.asyncio
async def test_tts_tool_arun_success_no_url(mock_config, mock_engine_generate):
    """Test async run success when no URL is returned."""
    mock_callback = MagicMock()
    tool = TTSTool(config=mock_config, on_artifact_created=mock_callback)

    mock_result = MagicMock()
    mock_result.provider = "openai"
    mock_result.model = "tts-1"
    mock_result.latency_ms = 150.5
    mock_result.persisted_url = None
    mock_engine_generate.return_value = mock_result

    result_str = await tool._arun(text="hello world")

    mock_callback.assert_not_called()

    result_dict = json.loads(result_str)
    assert result_dict["status"] == "success"
    assert "audio_url" not in result_dict
    assert "failed to persist" in result_dict["message"]


@pytest.mark.asyncio
async def test_tts_tool_arun_error(mock_config, mock_engine_generate):
    """Test async run error handling."""
    tool = TTSTool(config=mock_config)

    mock_engine_generate.side_effect = Exception("API Error")

    result_str = await tool._arun(text="hello world")

    result_dict = json.loads(result_str)
    assert result_dict["status"] == "error"
    assert "API Error" in result_dict["error"]


@pytest.mark.asyncio
async def test_tts_tool_push_artifact_callback_failure(mock_config, mock_engine_generate):
    """Artifact callback exceptions are swallowed."""
    mock_callback = MagicMock(side_effect=RuntimeError("push failed"))
    tool = TTSTool(config=mock_config, on_artifact_created=mock_callback)

    mock_result = MagicMock()
    mock_result.provider = "openai"
    mock_result.model = "tts-1"
    mock_result.latency_ms = 10.0
    mock_result.persisted_url = "https://cdn.example/a.mp3"
    mock_result.mime_type = "audio/mpeg"
    mock_engine_generate.return_value = mock_result

    result_str = await tool._arun(text="hello")
    result_dict = json.loads(result_str)
    assert result_dict["status"] == "success"
    mock_callback.assert_called_once()
