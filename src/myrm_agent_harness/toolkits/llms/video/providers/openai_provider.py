"""OpenAI Sora video generation provider.

Supports Sora 2 / Sora 2 Pro via the /v1/videos endpoint.
Uses the submit → poll → download pattern.

[INPUT]
- toolkits.llms._media_shared.types::ModeCapabilities, ProviderModeCapabilities (POS: These types are imported by video/models.py, normalization.py, and task_store.py. They define the contract between provider declarations and the normalization engine.)

[OUTPUT]
- OpenAISoraProvider: class — Open A I Sora Provider

[POS]
OpenAI Sora video generation provider.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import httpx

from myrm_agent_harness.toolkits.llms._media_shared.types import (
    ModeCapabilities,
    ProviderModeCapabilities,
)

from ..models import ProviderCapabilities, VideoAsset
from .base import ModelInfo, ProviderOutput, VideoGenerationProvider

if TYPE_CHECKING:
    from ..models import VideoGenerationConfig

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "sora"
_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_SUPPORTED_DURATIONS = (4, 8, 12)
_SUPPORTED_SIZES = frozenset({"720x1280", "1280x720", "1024x1792", "1792x1024"})


def _resolve_duration(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    clamped = max(_SUPPORTED_DURATIONS[0], seconds)
    nearest = min(_SUPPORTED_DURATIONS, key=lambda d: abs(d - clamped))
    return str(nearest)


def _build_image_reference(image_data: bytes) -> dict[str, str]:
    """Build OpenAI input_reference from raw image bytes as base64 data URL."""
    from ._image_utils import encode_image_data_url

    return {"image_url": encode_image_data_url(image_data)}


def _resolve_size(
    aspect_ratio: str | None,
    resolution: str | None,
) -> str | None:
    if aspect_ratio == "9:16":
        return "720x1280"
    if aspect_ratio == "16:9":
        return "1280x720"
    if resolution == "1080P":
        return "1792x1024"
    return None


class OpenAISoraProvider(VideoGenerationProvider):
    """OpenAI Sora video generation provider."""

    @property
    def provider_id(self) -> str:
        return "openai"

    @property
    def display_name(self) -> str:
        return "OpenAI Sora"

    @property
    def default_model(self) -> str:
        return _DEFAULT_MODEL

    @property
    def supported_models(self) -> tuple[ModelInfo, ...]:
        return (
            ModelInfo(id="sora", display_name="Sora"),
            ModelInfo(id="sora-2", display_name="Sora 2"),
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        _t2v = ModeCapabilities(
            supported_durations=_SUPPORTED_DURATIONS,
            max_duration_seconds=12,
        )
        return ProviderCapabilities(
            max_videos=1,
            max_input_images=1,
            max_input_videos=1,
            max_duration_seconds=12,
            supported_durations=_SUPPORTED_DURATIONS,
            supports_size=True,
            mode_capabilities=ProviderModeCapabilities(
                generate=_t2v,
                image_to_video=_t2v,
            ),
        )

    async def generate(
        self,
        prompt: str,
        config: VideoGenerationConfig,
        *,
        model: str | None = None,
        duration_seconds: int | None = None,
        aspect_ratio: str | None = None,
        resolution: str | None = None,
        enable_audio: bool | None = None,
        reference_images: list[bytes] | None = None,
        reference_videos: list[bytes] | None = None,
        extra_params: dict[str, object] | None = None,
    ) -> ProviderOutput:
        api_key = config.api_key.get_secret_value() if config.api_key else None
        if not api_key:
            raise ValueError("OpenAI API key missing")

        effective_model = model or config.model or _DEFAULT_MODEL
        base_url = (config.base_url or _DEFAULT_BASE_URL).rstrip("/")
        seconds = _resolve_duration(duration_seconds or config.default_duration_seconds)
        size = _resolve_size(
            aspect_ratio or config.default_aspect_ratio,
            resolution or config.default_resolution,
        )

        timeout = httpx.Timeout(config.timeout_seconds, connect=30.0)
        headers = {"Authorization": f"Bearer {api_key}"}

        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            body: dict[str, object] = {"prompt": prompt, "model": effective_model}
            if seconds:
                body["seconds"] = seconds
            if size:
                body["size"] = size
            if reference_images:
                body["input_reference"] = _build_image_reference(reference_images[0])

            resp = await client.post(f"{base_url}/videos", json=body)
            resp.raise_for_status()
            submitted = resp.json()
            video_id = submitted.get("id", "").strip()
            if not video_id:
                raise ValueError("OpenAI response missing video id")

            if config.progress_callback:
                await config.progress_callback(f"Submitted to OpenAI (id={video_id}), polling...")

            completed = await self._poll(client, base_url, video_id, config)

            if config.progress_callback:
                await config.progress_callback("Generation complete, downloading video...")

            video = await self._download(client, base_url, video_id, config)
            video_meta: dict[str, object] = {
                "video_id": video_id,
                "status": completed.get("status"),
                "seconds": completed.get("seconds"),
                "size": completed.get("size"),
            }
            assets = [
                VideoAsset(
                    data=video,
                    mime_type="video/mp4",
                    filename=f"video-{video_id[:8]}.mp4",
                    metadata=video_meta,
                )
            ]
            return ProviderOutput(assets=assets)

    async def _poll(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        video_id: str,
        config: VideoGenerationConfig,
    ) -> dict[str, object]:
        for _attempt in range(config.max_poll_attempts):
            resp = await client.get(f"{base_url}/videos/{video_id}")
            resp.raise_for_status()
            payload = resp.json()
            status = str(payload.get("status", "")).strip()
            if status == "completed":
                return payload
            if status == "failed":
                err = payload.get("error", {})
                raise RuntimeError(str(err.get("message", "")) or "OpenAI video generation failed")
            await asyncio.sleep(config.poll_interval_seconds)
        raise TimeoutError(f"OpenAI video generation {video_id} did not finish in time")

    async def _download(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        video_id: str,
        config: VideoGenerationConfig,
    ) -> bytes:
        resp = await client.get(
            f"{base_url}/videos/{video_id}/content",
            params={"variant": "video"},
            headers={"Accept": "application/binary"},
        )
        resp.raise_for_status()
        data = resp.content
        if len(data) > config.max_download_bytes:
            raise ValueError(f"Video exceeds max download size ({len(data)} > {config.max_download_bytes} bytes)")
        return data

    async def health_check(self, config: VideoGenerationConfig) -> bool:
        api_key = config.api_key.get_secret_value() if config.api_key else None
        if not api_key:
            return False
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(10.0),
                headers={"Authorization": f"Bearer {api_key}"},
            ) as client:
                base_url = (config.base_url or _DEFAULT_BASE_URL).rstrip("/")
                resp = await client.get(f"{base_url}/models")
                return resp.status_code == 200
        except Exception:
            return False
