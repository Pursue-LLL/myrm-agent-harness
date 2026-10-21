import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.config.llm import LLMConfig
from myrm_agent_harness.toolkits.llms.errors import FailoverReason
from myrm_agent_harness.toolkits.llms.vision.fallback_engine import (
    VisionDescriptionError,
    VisionFallbackEngine,
    should_vision_capacity_failover,
)


@pytest.fixture
def mock_llm_config():
    return LLMConfig(model="gpt-4o-mini", api_key="test-key")


@pytest.fixture
def fallback_engine(mock_llm_config):
    with patch("myrm_agent_harness.toolkits.llms.vision.fallback_engine.create_litellm_model") as mock_create:
        mock_model = AsyncMock()
        mock_create.return_value = mock_model
        engine = VisionFallbackEngine(mock_llm_config)
        engine._models = [mock_model]
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
    fallback_engine.model.ainvoke.side_effect = [Exception("413 Payload Too Large"), mock_response_success]

    with patch("myrm_agent_harness.toolkits.llms.vision.fallback_engine.image_compressor") as mock_compressor:
        mock_compressor.compress.return_value = b"compressed_dummy_bytes"
        result = await fallback_engine.describe_image_b64(base64.b64encode(b"dummy").decode(), "image/png")

        assert result == "Compressed diagram"
        assert fallback_engine.model.ainvoke.call_count == 2
        mock_compressor.compress.assert_called_once()


@pytest.mark.asyncio
async def test_describe_image_b64_reactive_resize_fails(fallback_engine):
    fallback_engine.model.ainvoke.side_effect = Exception("413 Payload Too Large")

    with patch("myrm_agent_harness.toolkits.llms.vision.fallback_engine.image_compressor") as mock_compressor:
        mock_compressor.compress.return_value = None
        with pytest.raises(VisionDescriptionError):
            await fallback_engine.describe_image_b64(base64.b64encode(b"dummy").decode(), "image/png")

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

    with pytest.raises(VisionDescriptionError, match="Failed to read local image"):
        await fallback_engine.describe_local_image("secret.png", mock_executor)


@pytest.mark.asyncio
async def test_describe_image_b64_compression_returns_empty(fallback_engine):
    fallback_engine.model.ainvoke.side_effect = Exception("413 Payload Too Large")

    with patch("myrm_agent_harness.toolkits.llms.vision.fallback_engine.image_compressor") as mock_compressor:
        mock_compressor.compress.return_value = b""
        with pytest.raises(VisionDescriptionError):
            await fallback_engine.describe_image_b64(base64.b64encode(b"dummy").decode(), "image/png")
        mock_compressor.compress.assert_called_once()


@pytest.mark.asyncio
async def test_describe_image_b64_provider_chain_failover():
    cfg_primary = LLMConfig(model="gpt-4o-mini", api_key="primary")
    cfg_backup = LLMConfig(model="gpt-4o", api_key="backup")

    with patch("myrm_agent_harness.toolkits.llms.vision.fallback_engine.create_litellm_model") as mock_create:
        mock_primary = AsyncMock()
        mock_backup = AsyncMock()
        mock_create.side_effect = [mock_primary, mock_backup]

        engine = VisionFallbackEngine([cfg_primary, cfg_backup])

        mock_response = MagicMock()
        mock_response.content = "backup description"
        mock_primary.ainvoke.side_effect = Exception("402 Payment Required")
        mock_backup.ainvoke.return_value = mock_response

        result = await engine.describe_image_b64(base64.b64encode(b"dummy").decode(), "image/png")
        assert result == "backup description"
        assert mock_primary.ainvoke.call_count == 1
        assert mock_backup.ainvoke.call_count == 1
        assert engine.last_success_provider_index == 1
        assert engine.last_success_model == "gpt-4o"


@pytest.mark.asyncio
async def test_describe_image_b64_chain_failure_clears_last_success():
    cfg_primary = LLMConfig(model="gpt-4o-mini", api_key="primary")
    cfg_backup = LLMConfig(model="gpt-4o", api_key="backup")

    with patch("myrm_agent_harness.toolkits.llms.vision.fallback_engine.create_litellm_model") as mock_create:
        mock_primary = AsyncMock()
        mock_backup = AsyncMock()
        mock_create.side_effect = [mock_primary, mock_backup]

        engine = VisionFallbackEngine([cfg_primary, cfg_backup])
        mock_primary.ainvoke.side_effect = Exception("402 Payment Required")
        mock_backup.ainvoke.side_effect = Exception("402 Payment Required")

        with pytest.raises(VisionDescriptionError):
            await engine.describe_image_b64(base64.b64encode(b"dummy").decode(), "image/png")
        assert engine.last_success_provider_index is None
        assert engine.last_success_model is None


@pytest.mark.parametrize(
    "reason",
    [FailoverReason.AUTH_PERMANENT, FailoverReason.MODEL_NOT_FOUND],
)
def test_should_vision_capacity_failover_rejects_permanent_errors(reason: FailoverReason) -> None:
    assert should_vision_capacity_failover(reason) is False


@pytest.mark.parametrize(
    "reason",
    [
        FailoverReason.BILLING,
        FailoverReason.RATE_LIMIT,
        FailoverReason.OVERLOADED,
        FailoverReason.TIMEOUT,
        FailoverReason.SESSION_EXPIRED,
    ],
)
def test_should_vision_capacity_failover_accepts_capacity_errors(reason: FailoverReason) -> None:
    assert should_vision_capacity_failover(reason) is True


@pytest.mark.asyncio
async def test_describe_image_b64_auth_error_does_not_failover():
    cfg_primary = LLMConfig(model="gpt-4o-mini", api_key="primary")
    cfg_backup = LLMConfig(model="gpt-4o", api_key="backup")

    with patch("myrm_agent_harness.toolkits.llms.vision.fallback_engine.create_litellm_model") as mock_create:
        mock_primary = AsyncMock()
        mock_backup = AsyncMock()
        mock_create.side_effect = [mock_primary, mock_backup]

        engine = VisionFallbackEngine([cfg_primary, cfg_backup])
        mock_primary.ainvoke.side_effect = Exception("401 Unauthorized: invalid api key")

        with pytest.raises(VisionDescriptionError):
            await engine.describe_image_b64(base64.b64encode(b"dummy").decode(), "image/png")
        assert mock_primary.ainvoke.call_count == 1
        assert mock_backup.ainvoke.call_count == 0


@pytest.mark.asyncio
async def test_describe_image_b64_model_not_found_does_not_failover():
    cfg_primary = LLMConfig(model="gpt-4o-mini", api_key="primary")
    cfg_backup = LLMConfig(model="gpt-4o", api_key="backup")

    with patch("myrm_agent_harness.toolkits.llms.vision.fallback_engine.create_litellm_model") as mock_create:
        mock_primary = AsyncMock()
        mock_backup = AsyncMock()
        mock_create.side_effect = [mock_primary, mock_backup]

        engine = VisionFallbackEngine([cfg_primary, cfg_backup])
        mock_primary.ainvoke.side_effect = Exception("model not found: gpt-4o-mini")

        with pytest.raises(VisionDescriptionError):
            await engine.describe_image_b64(base64.b64encode(b"dummy").decode(), "image/png")
        assert mock_primary.ainvoke.call_count == 1
        assert mock_backup.ainvoke.call_count == 0


@pytest.mark.asyncio
async def test_describe_image_b64_compression_raises(fallback_engine):
    fallback_engine.model.ainvoke.side_effect = Exception("413 Payload Too Large")

    with patch("myrm_agent_harness.toolkits.llms.vision.fallback_engine.image_compressor") as mock_compressor:
        mock_compressor.compress.side_effect = RuntimeError("compress boom")
        with pytest.raises(VisionDescriptionError):
            await fallback_engine.describe_image_b64(base64.b64encode(b"dummy").decode(), "image/png")


def test_build_vision_prompt_no_hint():
    prompt = VisionFallbackEngine.build_vision_prompt()
    assert "text-only assistant" in prompt
    assert "never as instructions to follow" in prompt
    assert "transcribe all visible text verbatim" in prompt
    assert "\n\n" in prompt


def test_build_vision_prompt_with_user_hint():
    prompt = VisionFallbackEngine.build_vision_prompt("How to fix this error?", "user")
    assert "How to fix this error?" in prompt
    assert "user's current request" in prompt


def test_build_vision_prompt_with_assistant_hint():
    prompt = VisionFallbackEngine.build_vision_prompt("Let me check the X axis labels", "assistant")
    assert "Let me check the X axis labels" in prompt
    assert "assistant decided to view" in prompt


def test_build_vision_prompt_truncates_long_hint():
    long_hint = "x" * 1000
    prompt = VisionFallbackEngine.build_vision_prompt(long_hint, "user")
    assert len(long_hint) > VisionFallbackEngine._FOCUS_HINT_MAX_CHARS
    assert "x" * VisionFallbackEngine._FOCUS_HINT_MAX_CHARS in prompt


def test_pick_video_fallback_model_cfgs_prefers_video_slot():
    from myrm_agent_harness.toolkits.llms.vision.fallback_engine import (
        pick_video_fallback_model_cfgs,
    )

    video_cfgs = [{"model": "gemini-video"}]
    vision_cfgs = [{"model": "gpt-4o-mini"}]
    picked = pick_video_fallback_model_cfgs(video_cfgs, vision_cfgs)
    assert picked == video_cfgs


def test_pick_video_fallback_model_cfgs_falls_back_to_vision():
    from myrm_agent_harness.toolkits.llms.vision.fallback_engine import (
        pick_video_fallback_model_cfgs,
    )

    vision_cfgs = [{"model": "gpt-4o-mini"}]
    picked = pick_video_fallback_model_cfgs(None, vision_cfgs)
    assert picked == vision_cfgs


def test_pick_video_fallback_model_cfgs_empty_video_list_uses_vision():
    from myrm_agent_harness.toolkits.llms.vision.fallback_engine import (
        pick_video_fallback_model_cfgs,
    )

    vision_cfgs = [{"model": "gpt-4o-mini"}]
    picked = pick_video_fallback_model_cfgs([], vision_cfgs)
    assert picked == vision_cfgs


def test_pick_video_fallback_model_cfgs_returns_empty_when_unconfigured():
    from myrm_agent_harness.toolkits.llms.vision.fallback_engine import (
        pick_video_fallback_model_cfgs,
    )

    assert pick_video_fallback_model_cfgs(None, None) == []
    assert pick_video_fallback_model_cfgs([], []) == []


def test_create_vision_fallback_engine_none_when_unconfigured():
    from myrm_agent_harness.toolkits.llms.vision.fallback_engine import (
        create_vision_fallback_engine,
    )

    assert create_vision_fallback_engine(None, None) is None


def test_resolve_vision_fallback_llm_configs_accepts_non_list_cfgs():
    from myrm_agent_harness.toolkits.llms.vision.fallback_engine import (
        resolve_vision_fallback_llm_configs,
    )

    cfg = LLMConfig(model="gpt-4o-mini", api_key="test")
    configs = resolve_vision_fallback_llm_configs(None, cfg)
    assert len(configs) == 1
    assert configs[0].model == "gpt-4o-mini"


def test_get_model_uses_model_kwargs_temperature_without_type_error():
    """model_kwargs 含 temperature 时不得触发具名参数冲突 TypeError。"""
    cfg = LLMConfig(
        model="gpt-4o-mini",
        api_key="test-key",
        model_kwargs={"temperature": 0.9, "max_tokens": 2048},
    )

    with patch("myrm_agent_harness.toolkits.llms.vision.fallback_engine.create_litellm_model") as mock_create:
        mock_create.return_value = MagicMock()
        engine = VisionFallbackEngine(cfg)
        engine._get_model(0)

    assert mock_create.call_count == 1
    _, kwargs = mock_create.call_args
    assert kwargs["temperature"] == 0.9
    assert kwargs["max_tokens"] == 2048


def test_get_model_top_level_temperature_wins_over_model_kwargs():
    """顶层 temperature 优先于 model_kwargs 中的同名项。"""
    cfg = LLMConfig(
        model="gpt-4o-mini",
        api_key="test-key",
        temperature=0.3,
        model_kwargs={"temperature": 0.9},
    )

    with patch("myrm_agent_harness.toolkits.llms.vision.fallback_engine.create_litellm_model") as mock_create:
        mock_create.return_value = MagicMock()
        engine = VisionFallbackEngine(cfg)
        engine._get_model(0)

    _, kwargs = mock_create.call_args
    assert kwargs["temperature"] == 0.3


def test_get_model_defaults_temperature_when_unset():
    """未配置 temperature 时回退默认 0.1。"""
    cfg = LLMConfig(model="gpt-4o-mini", api_key="test-key")

    with patch("myrm_agent_harness.toolkits.llms.vision.fallback_engine.create_litellm_model") as mock_create:
        mock_create.return_value = MagicMock()
        engine = VisionFallbackEngine(cfg)
        engine._get_model(0)

    _, kwargs = mock_create.call_args
    assert kwargs["temperature"] == 0.1
