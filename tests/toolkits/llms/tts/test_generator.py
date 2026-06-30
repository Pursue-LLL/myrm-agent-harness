"""Unit tests for AsyncTTSEngine."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pydantic import SecretStr

from myrm_agent_harness.core.config.gateway import ToolGatewayConfig
from myrm_agent_harness.toolkits.llms.tts.generator import AsyncTTSEngine
from myrm_agent_harness.toolkits.llms.tts.models import TTSConfig, TTSGenerationError


@pytest.fixture
def gateway_config() -> ToolGatewayConfig:
    return ToolGatewayConfig(
        use_gateway=True,
        gateway_url="https://gateway.example/tool-relay",
        auth_token="gateway-token",
    )


def _mock_http_response(*, content: bytes = b"audio-bytes", content_type: str = "audio/mpeg") -> MagicMock:
    response = MagicMock()
    response.content = content
    response.headers = {"content-type": content_type}
    response.raise_for_status = MagicMock()
    return response


def _patch_async_client(post_return: MagicMock | Exception) -> tuple[MagicMock, AsyncMock]:
    mock_client = AsyncMock()
    if isinstance(post_return, Exception):
        mock_client.post = AsyncMock(side_effect=post_return)
    else:
        mock_client.post = AsyncMock(return_value=post_return)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client, patch(
        "myrm_agent_harness.toolkits.llms.tts.generator.httpx.AsyncClient",
        return_value=mock_client,
    )


def test_build_request_openai_direct() -> None:
    engine = AsyncTTSEngine(TTSConfig(provider="openai", api_key=SecretStr("sk-test"), voice="nova"))
    url, headers, body = engine._build_request("hello", bypass_gateway=True)

    assert url == "https://api.openai.com/v1/audio/speech"
    assert headers["Authorization"] == "Bearer sk-test"
    assert body == {"model": "tts-1", "input": "hello", "voice": "nova", "speed": 1.0}


def test_build_request_elevenlabs_direct() -> None:
    engine = AsyncTTSEngine(
        TTSConfig(provider="elevenlabs", api_key=SecretStr("el-key"), voice="voice-123", model="eleven_v2"),
    )
    url, headers, body = engine._build_request("hi", bypass_gateway=True)

    assert url == "https://api.elevenlabs.io/v1/text-to-speech/voice-123"
    assert headers["xi-api-key"] == "el-key"
    assert body == {"model_id": "eleven_v2", "text": "hi"}


def test_build_request_openai_gateway(gateway_config: ToolGatewayConfig) -> None:
    engine = AsyncTTSEngine(
        TTSConfig(provider="openai", model="gpt-4o-mini-tts", gateway_config=gateway_config),
    )
    url, headers, _body = engine._build_request("hello", bypass_gateway=False)

    assert url == "https://gateway.example/tool-relay/tts/openai/gpt-4o-mini-tts"
    assert headers["Authorization"] == "Bearer gateway-token"


def test_build_request_elevenlabs_gateway(gateway_config: ToolGatewayConfig) -> None:
    engine = AsyncTTSEngine(
        TTSConfig(provider="elevenlabs", voice="v1", gateway_config=gateway_config),
    )
    url, _, _ = engine._build_request("hello", bypass_gateway=False)
    assert url == "https://gateway.example/tool-relay/tts/elevenlabs/v1"


def test_build_request_gateway_generic_provider(gateway_config: ToolGatewayConfig) -> None:
    engine = AsyncTTSEngine(
        TTSConfig(provider="fish_audio", model="s1", gateway_config=gateway_config),
    )
    url, _, body = engine._build_request("hello", bypass_gateway=False)
    assert url == "https://gateway.example/tool-relay/tts/fish_audio/s1"
    assert body == {"text": "hello"}


def test_build_request_unsupported_provider_direct() -> None:
    engine = AsyncTTSEngine(TTSConfig(provider="unknown", api_key=SecretStr("k")))
    with pytest.raises(ValueError, match="Unsupported TTS provider"):
        engine._build_request("hello", bypass_gateway=True)


@pytest.mark.asyncio
async def test_generate_openai_success() -> None:
    engine = AsyncTTSEngine(TTSConfig(provider="openai", api_key=SecretStr("sk-test")))
    mock_client, client_patch = _patch_async_client(_mock_http_response())

    with client_patch:
        result = await engine.generate("hello")

    assert result.audio_bytes == b"audio-bytes"
    assert result.mime_type == "audio/mpeg"
    assert result.provider == "openai"
    mock_client.post.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_persists_via_media_callback() -> None:
    callback = AsyncMock(return_value="https://cdn.example/audio.mp3")
    engine = AsyncTTSEngine(
        TTSConfig(provider="openai", api_key=SecretStr("sk-test"), media_callback=callback),
    )
    _, client_patch = _patch_async_client(_mock_http_response())

    with client_patch:
        result = await engine.generate("persist me")

    assert result.persisted_url == "https://cdn.example/audio.mp3"
    callback.assert_awaited_once()
    args = callback.await_args.args
    assert args[0] == b"audio-bytes"
    assert args[1] == "audio/mpeg"
    assert args[2].prompt == "persist me"


@pytest.mark.asyncio
async def test_generate_media_callback_failure_still_returns_audio() -> None:
    callback = AsyncMock(side_effect=RuntimeError("storage down"))
    engine = AsyncTTSEngine(
        TTSConfig(provider="openai", api_key=SecretStr("sk-test"), media_callback=callback),
    )
    _, client_patch = _patch_async_client(_mock_http_response())

    with client_patch:
        result = await engine.generate("hello")

    assert result.persisted_url is None
    assert result.audio_bytes == b"audio-bytes"


@pytest.mark.asyncio
async def test_generate_gateway_failover_to_byok(gateway_config: ToolGatewayConfig) -> None:
    engine = AsyncTTSEngine(
        TTSConfig(
            provider="openai",
            api_key=SecretStr("sk-byok"),
            gateway_config=gateway_config,
            max_retries=1,
        ),
    )
    success = _mock_http_response(content=b"direct-audio")
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(
        side_effect=[
            httpx.HTTPStatusError(
                "502 Bad Gateway",
                request=MagicMock(),
                response=MagicMock(status_code=502, text="502"),
            ),
            success,
        ],
    )
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("myrm_agent_harness.toolkits.llms.tts.generator.httpx.AsyncClient", return_value=mock_client),
        patch(
            "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
            new_callable=AsyncMock,
        ) as dispatch_event,
    ):
        result = await engine.generate("failover")

    assert result.audio_bytes == b"direct-audio"
    assert mock_client.post.await_count == 2
    dispatch_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_retries_then_raises() -> None:
    engine = AsyncTTSEngine(
        TTSConfig(provider="openai", api_key=SecretStr("sk-test"), max_retries=1),
    )
    _, client_patch = _patch_async_client(RuntimeError("network down"))

    with client_patch, patch("myrm_agent_harness.toolkits.llms.tts.generator.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(TTSGenerationError, match="network down"):
            await engine.generate("retry")


@pytest.mark.asyncio
async def test_unsupported_provider_raises_generation_error() -> None:
    engine = AsyncTTSEngine(TTSConfig(provider="unknown", api_key=SecretStr("test-key")))
    with pytest.raises(TTSGenerationError, match="Unsupported TTS provider"):
        await engine.generate("hello")
