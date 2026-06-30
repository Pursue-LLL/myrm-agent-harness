"""Unit tests for llms/tts data models."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.llms.tts.models import (
    MediaMeta,
    TTSConfig,
    TTSGenerationError,
    TTSResult,
)


def test_media_meta_fields() -> None:
    meta = MediaMeta(prompt="hello", model="tts-1", provider="openai")
    assert meta.prompt == "hello"
    assert meta.model == "tts-1"
    assert meta.provider == "openai"


def test_tts_generation_error_stores_latency() -> None:
    err = TTSGenerationError("failed", latency_ms=42.5)
    assert str(err) == "failed"
    assert err.latency_ms == 42.5


def test_tts_result_frozen() -> None:
    result = TTSResult(
        audio_bytes=b"x",
        mime_type="audio/mpeg",
        provider="openai",
        model="tts-1",
    )
    with pytest.raises(AttributeError):
        result.provider = "elevenlabs"  # type: ignore[misc]


def test_tts_config_defaults() -> None:
    cfg = TTSConfig()
    assert cfg.provider == "openai"
    assert cfg.model == "tts-1"
    assert cfg.voice == "alloy"
