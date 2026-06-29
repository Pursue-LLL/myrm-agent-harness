"""Core TTS generation engine.

[INPUT]
- httpx (POS: Async HTTP client)
- models::TTSConfig, TTSResult, TTSGenerationError, MediaMeta (POS: Data models)

[OUTPUT]
- AsyncTTSEngine: Core TTS generation engine

[POS]
Handles HTTP requests to TTS providers (OpenAI, ElevenLabs) with
Try-Catch flexible fallback for gateway routing.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from myrm_agent_harness.toolkits.tts.models import (
    MediaMeta,
    TTSConfig,
    TTSGenerationError,
    TTSResult,
)

logger = logging.getLogger(__name__)


class AsyncTTSEngine:
    """Async TTS generation engine."""

    def __init__(self, config: TTSConfig) -> None:
        self.config = config

    async def generate(self, text: str) -> TTSResult:
        """Generate speech from text."""
        max_attempts = self.config.max_retries + 1
        bypass_gateway = False
        last_error: Exception | None = None
        start_time = time.time()

        for attempt in range(max_attempts):
            try:
                return await self._call_provider(text, bypass_gateway=bypass_gateway)
            except Exception as e:
                last_error = e
                error_msg = str(e).lower()

                # Gateway Flexible Fallback Logic
                if (
                    not bypass_gateway
                    and self.config.gateway_config
                    and self.config.gateway_config.use_gateway
                    and self.config.api_key
                ) and (
                    "502" in error_msg
                    or "503" in error_msg
                    or "504" in error_msg
                    or "402" in error_msg
                    or "insufficient" in error_msg
                    or "timeout" in error_msg
                ):
                    logger.warning(f"Gateway TTS failed ({error_msg}), falling back to direct provider API (BYOK)")
                    try:
                        from myrm_agent_harness.utils.event_utils import dispatch_custom_event

                        await dispatch_custom_event(
                            "agent_status",
                            {
                                "event": "tool_fallback",
                                "tool": "tts_tool",
                                "fallback_type": "gateway_failover",
                                "message": f"统一网关异常，正在无缝回退至本地直连 ({self.config.provider})...",
                            },
                        )
                    except Exception:
                        pass
                    bypass_gateway = True
                    continue  # Retry immediately with direct connection

                if attempt < max_attempts - 1:
                    await asyncio.sleep(1.0 * (2**attempt))

        latency_ms = (time.time() - start_time) * 1000
        raise TTSGenerationError(
            f"TTS generation failed after {max_attempts} attempts. Last error: {last_error}",
            latency_ms=latency_ms,
        )

    async def _call_provider(self, text: str, bypass_gateway: bool) -> TTSResult:
        start_time = time.time()
        provider = self.config.provider

        url, headers, payload = self._build_request(text, bypass_gateway)

        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            audio_bytes = response.content

        latency_ms = (time.time() - start_time) * 1000
        mime_type = response.headers.get("content-type", "audio/mpeg")

        persisted_url = None
        if self.config.media_callback:
            meta = MediaMeta(prompt=text, model=self.config.model, provider=provider)
            try:
                persisted_url = await self.config.media_callback(audio_bytes, mime_type, meta)
            except Exception as e:
                logger.warning(f"Failed to persist TTS audio: {e}")

        return TTSResult(
            audio_bytes=audio_bytes,
            mime_type=mime_type,
            provider=provider,
            model=self.config.model,
            latency_ms=latency_ms,
            persisted_url=persisted_url,
        )

    def _build_request(self, text: str, bypass_gateway: bool) -> tuple[str, dict[str, str], dict[str, Any]]:
        provider = self.config.provider

        if not bypass_gateway and self.config.gateway_config and self.config.gateway_config.use_gateway:
            # Use Gateway
            base_url = self.config.gateway_config.gateway_url.rstrip("/")
            if provider == "openai":
                url = f"{base_url}/tts/openai/{self.config.model}"
            elif provider == "elevenlabs":
                url = f"{base_url}/tts/elevenlabs/{self.config.voice}"
            else:
                url = f"{base_url}/tts/{provider}/{self.config.model}"

            headers = {
                "Authorization": f"Bearer {self.config.gateway_config.auth_token}",
                "Content-Type": "application/json",
            }
        else:
            # Direct Connection
            api_key = self.config.api_key.get_secret_value() if self.config.api_key else ""
            if provider == "openai":
                url = self.config.base_url or "https://api.openai.com/v1/audio/speech"
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }
            elif provider == "elevenlabs":
                url = self.config.base_url or f"https://api.elevenlabs.io/v1/text-to-speech/{self.config.voice}"
                headers = {
                    "xi-api-key": api_key,
                    "Content-Type": "application/json",
                }
            else:
                raise ValueError(f"Unsupported TTS provider: {provider}")

        # Build Payload
        if provider == "openai":
            payload = {
                "model": self.config.model,
                "input": text,
                "voice": self.config.voice,
                "speed": self.config.speed,
            }
        elif provider == "elevenlabs":
            payload = {
                "model_id": self.config.model,
                "text": text,
            }
        else:
            payload = {"text": text}

        return url, headers, payload
