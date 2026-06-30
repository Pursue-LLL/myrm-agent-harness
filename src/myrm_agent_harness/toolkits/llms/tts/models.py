"""Data types for the TTS (Text-to-Speech) module.

[OUTPUT]
- TTSConfig: TTS service configuration
- TTSResult: Structured result from a TTS request
- TTSGenerationError: Exception raised when TTS fails

[POS]
Pure data types with no business logic. Separated from generator.py
to maintain single-responsibility and keep file sizes manageable.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic.alias_generators import to_camel

from myrm_agent_harness.core.config.gateway import ToolGatewayConfig


class MediaMeta:
    """Metadata passed alongside audio bytes during persistence."""

    __slots__ = ("model", "prompt", "provider")

    def __init__(
        self,
        prompt: str | None = None,
        model: str | None = None,
        provider: str | None = None,
    ) -> None:
        self.prompt = prompt
        self.model = model
        self.provider = provider


MediaCallback = Callable[[bytes, str, MediaMeta], Awaitable[str]]
"""Async callback: (audio_bytes, mime_type, metadata) -> persisted URL."""

logger = logging.getLogger(__name__)


class TTSConfig(BaseModel):
    """TTS service configuration."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    provider: str = Field(default="openai", description="TTS provider (openai, elevenlabs)")
    model: str = Field(default="tts-1", description="TTS model identifier")
    voice: str = Field(default="alloy", description="Voice identifier")
    speed: float = Field(default=1.0, ge=0.25, le=4.0, description="Speech speed multiplier (provider-dependent)")
    pitch: float = Field(default=0.0, ge=-20.0, le=20.0, description="Pitch adjustment in Hz (provider-dependent)")
    api_key: SecretStr | None = Field(default=None, description="API key (protected from logging)")
    base_url: str | None = Field(default=None, description="Custom API base URL")
    timeout_seconds: int = Field(default=60, description="Request timeout in seconds")
    max_retries: int = Field(default=1, ge=0, le=3, description="Max retry attempts on failure")
    gateway_config: ToolGatewayConfig | None = Field(
        default=None,
        description="Unified gateway configuration for proxying and billing",
    )
    media_callback: MediaCallback | None = Field(
        default=None,
        exclude=True,
        description="Async callback for persisting generated audio",
    )


@dataclass(frozen=True, slots=True)
class TTSResult:
    """Result from a TTS request."""

    audio_bytes: bytes
    mime_type: str
    provider: str
    model: str
    latency_ms: float = 0.0
    persisted_url: str | None = None


class TTSGenerationError(Exception):
    """Raised when TTS generation fails."""

    def __init__(self, message: str, *, latency_ms: float = 0.0) -> None:
        super().__init__(message)
        self.latency_ms = latency_ms
