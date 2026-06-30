"""Unit tests for AsyncTTSEngine."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.llms.tts.generator import AsyncTTSEngine
from myrm_agent_harness.toolkits.llms.tts.models import TTSConfig, TTSGenerationError


@pytest.mark.asyncio
async def test_unsupported_provider_raises_generation_error() -> None:
    engine = AsyncTTSEngine(TTSConfig(provider="unknown", api_key="test-key"))
    with pytest.raises(TTSGenerationError, match="Unsupported TTS provider"):
        await engine.generate("hello")
