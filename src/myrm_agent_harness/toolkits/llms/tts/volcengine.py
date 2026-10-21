"""Volcengine speech synthesis (Doubao-TTS v1 + Seed-Audio v3).

Encapsulates the two Volcengine OpenSpeech protocols behind one provider id:

- ``doubao-tts`` (v1, ``/api/v1/tts``): app credentials (``appid:token``
  composite in ``TTSConfig.api_key``), cluster ``volcano_tts``, base64 MP3
  payload in the ``data`` field.
- ``seed-audio-1.0`` (v3, ``/api/v3/tts/create``): single ``X-Api-Key``,
  generative model that occasionally returns empty audio (server-side
  transient) — callers should retry.

The unified tool gateway does not proxy OpenSpeech endpoints; requests
always connect directly to Volcengine.

[INPUT]
- models::TTSConfig, TTSGenerationError (POS: shared data types and error contract)

[OUTPUT]
- VolcengineRequest: Built HTTP request parts + protocol kind tag.
- build_volcengine_request: Compose request for the configured model.
- parse_volcengine_response: Decode inline base64 / temp URL responses.
- resolve_volcengine_timeout: Per-model HTTP timeout floor.

[POS]
Volcengine speech protocol adapter. Style directives and the read-aloud
instruction wrapping are Seed-Audio prompt engineering and live here, not
in callers.
"""

from __future__ import annotations

import base64
import logging
import uuid
from dataclasses import dataclass

import httpx

from myrm_agent_harness.core.security.http.secure_fetch import secure_get

from .models import TTSConfig, TTSGenerationError

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://openspeech.bytedance.com"
_DEFAULT_VOICE = "zh_female_vv_uranus_bigtts"
_DEFAULT_SEED_MODEL = "seed-audio-1.0"
_SEED_AUDIO_TIMEOUT_FLOOR_SECONDS = 120.0
_SEED_TEXT_PROMPT_LIMIT = 3000
_OPENAI_DEFAULT_VOICE = "alloy"

_READ_ALOUD_TEMPLATE = (
    "请用自然清晰的普通话朗读以下内容，不要添加额外的字词：\n「{spoken}」"
)


@dataclass(frozen=True, slots=True)
class VolcengineRequest:
    """Built HTTP request parts plus the protocol kind for response parsing."""

    url: str
    headers: dict[str, str]
    payload: dict[str, object]
    kind: str  # "doubao" | "seed_audio"


def is_seed_audio_model(model: str) -> bool:
    """Whether the configured model targets the generative Seed-Audio v3 API."""
    return "seed" in model.lower()


def resolve_volcengine_timeout(config: TTSConfig) -> httpx.Timeout:
    """Seed-Audio is generative and slow; enforce a 120s floor for it."""
    seconds = float(config.timeout_seconds)
    if (
        is_seed_audio_model(config.model)
        and seconds < _SEED_AUDIO_TIMEOUT_FLOOR_SECONDS
    ):
        seconds = _SEED_AUDIO_TIMEOUT_FLOOR_SECONDS
    return httpx.Timeout(seconds, connect=30.0)


def _resolve_voice(config: TTSConfig) -> str:
    """Map config voice onto a Volcengine voice type.

    The shared ``TTSConfig.voice`` defaults to OpenAI's ``alloy``; that value
    is meaningless to Volcengine, so it falls back to the Volcengine default.
    """
    voice = (config.voice or "").strip()
    if not voice or voice == _OPENAI_DEFAULT_VOICE:
        return _DEFAULT_VOICE
    return voice


def _read_aloud_prompt(text: str, style: str | None) -> str:
    """Wrap spoken text with the read-aloud instruction (Seed-Audio prompt format)."""
    spoken_part = _READ_ALOUD_TEMPLATE.format(spoken=text)
    if style and style.strip():
        return f"{style.strip()}。\n\n{spoken_part}"
    return spoken_part


def _resolve_doubao_credentials(api_key: str) -> tuple[str, str]:
    """Split the ``appid:token`` composite key into app credentials."""
    app_id, _, token = api_key.partition(":")
    if not app_id.strip() or not token.strip():
        raise TTSGenerationError(
            "Doubao-TTS requires the composite credential format 'appid:access_token' "
            "in the API key field (Volcengine console: 语音技术 → 应用详情)."
        )
    return app_id.strip(), token.strip()


def build_volcengine_request(
    config: TTSConfig,
    text: str,
    style: str | None = None,
) -> VolcengineRequest:
    """Compose the HTTP request for Doubao-TTS (v1) or Seed-Audio (v3)."""
    api_key = config.api_key.get_secret_value() if config.api_key else ""
    if not api_key:
        raise TTSGenerationError("Volcengine speech API key missing")
    base_url = (config.base_url or _DEFAULT_BASE_URL).rstrip("/")

    if is_seed_audio_model(config.model):
        text_prompt = _read_aloud_prompt(text, style)
        if len(text_prompt) > _SEED_TEXT_PROMPT_LIMIT:
            raise TTSGenerationError(
                f"Seed-Audio text prompt ({len(text_prompt)} chars) exceeds the "
                f"{_SEED_TEXT_PROMPT_LIMIT} character limit; shorten the text or style."
            )
        return VolcengineRequest(
            url=f"{base_url}/api/v3/tts/create",
            headers={
                "X-Api-Key": api_key,
                "Content-Type": "application/json",
            },
            payload={
                "model": config.model or _DEFAULT_SEED_MODEL,
                "text_prompt": text_prompt,
                "references": [{"speaker": _resolve_voice(config)}],
                "audio_config": {
                    "format": "mp3",
                    "sample_rate": 48000,
                    "enable_subtitle": True,
                },
                "watermark": {},
            },
            kind="seed_audio",
        )

    app_id, token = _resolve_doubao_credentials(api_key)
    return VolcengineRequest(
        url=f"{base_url}/api/v1/tts",
        headers={
            # OpenSpeech v1 uses the non-standard "Bearer;{token}" scheme.
            "Authorization": f"Bearer;{token}",
            "Content-Type": "application/json",
        },
        payload={
            "app": {"appid": app_id, "token": token, "cluster": "volcano_tts"},
            "user": {"uid": "myrm-agent"},
            "audio": {
                "voice_type": _resolve_voice(config),
                "encoding": "mp3",
                "speed_ratio": max(0.2, min(3.0, config.speed)),
                "sample_rate": 48000,
            },
            "request": {
                "reqid": f"myrm-{uuid.uuid4().hex[:16]}",
                "text": text,
                "operation": "query",
            },
        },
        kind="doubao",
    )


async def parse_volcengine_response(
    request: VolcengineRequest,
    response: httpx.Response,
    config: TTSConfig,
) -> tuple[bytes, str, float | None]:
    """Decode a Volcengine speech response into (audio, mime, duration).

    Raises ``TTSGenerationError`` on protocol errors and on empty audio so
    the engine's retry loop can recover from the known Seed-Audio transient.
    """
    try:
        payload: dict[str, object] = response.json()
    except ValueError as exc:
        raise TTSGenerationError(
            f"Volcengine returned non-JSON response: {exc}"
        ) from exc

    if request.kind == "doubao":
        return _parse_doubao_payload(payload)
    return await _parse_seed_audio_payload(payload, config)


def _parse_doubao_payload(
    payload: dict[str, object],
) -> tuple[bytes, str, float | None]:
    code = payload.get("code")
    if code != 3000:
        message = str(payload.get("message", "")) or f"error code {code}"
        raise TTSGenerationError(f"Doubao-TTS failed ({code}): {message}")

    data = payload.get("data")
    if not isinstance(data, str) or not data.strip():
        raise TTSGenerationError("Doubao-TTS returned empty audio data")

    audio = base64.b64decode(data)
    if not audio:
        raise TTSGenerationError("Doubao-TTS decoded to empty audio")
    return audio, "audio/mpeg", None


async def _parse_seed_audio_payload(
    payload: dict[str, object],
    config: TTSConfig,
) -> tuple[bytes, str, float | None]:
    # Error envelope: {"status_code": ..., "status_message": ...}
    status_code = payload.get("status_code")
    if isinstance(status_code, int) and status_code >= 400:
        message = str(payload.get("status_message", "")) or f"HTTP {status_code}"
        raise TTSGenerationError(f"Seed-Audio failed ({status_code}): {message}")

    audio_b64 = payload.get("audio")
    if isinstance(audio_b64, str) and audio_b64.strip():
        audio = base64.b64decode(audio_b64)
        if not audio:
            raise TTSGenerationError(
                "Seed-Audio returned empty audio data (transient; retrying may help)"
            )
        return audio, "audio/mpeg", _extract_duration(payload)

    temp_url = payload.get("url")
    if isinstance(temp_url, str) and temp_url.strip():
        try:
            resp = await secure_get(
                temp_url.strip(), timeout=float(config.timeout_seconds)
            )
        except Exception as exc:
            raise TTSGenerationError(
                f"Seed-Audio temp URL download failed: {exc}"
            ) from exc
        resp.raise_for_status()
        if not resp.content:
            raise TTSGenerationError("Seed-Audio temp URL contained empty audio")
        mime = resp.headers.get("content-type", "audio/mpeg").split(";")[0].strip()
        return resp.content, mime, _extract_duration(payload)

    raise TTSGenerationError(
        "Seed-Audio response contained neither inline audio nor a URL (transient; retrying may help)"
    )


def _extract_duration(payload: dict[str, object]) -> float | None:
    for key in ("original_duration", "duration"):
        value = payload.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    return None
