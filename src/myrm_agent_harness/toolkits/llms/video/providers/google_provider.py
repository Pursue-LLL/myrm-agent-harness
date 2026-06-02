"""Google Veo video generation provider.

Supports Veo 2.0 / 3.0 / 3.1 via the Gemini generateVideos API.
Uses the Google GenAI SDK's operation-based polling pattern.

[INPUT]
- toolkits.llms._media_shared.types::ModeCapabilities, ProviderModeCapabilities (POS: These types are imported by video/models.py, normalization.py, and task_store.py. They define the contract between provider declarations and the normalization engine.)

[OUTPUT]
- GoogleVeoProvider: class — Google Veo Provider

[POS]
Google Veo video generation provider.
"""

from __future__ import annotations

import asyncio
import base64
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

_DEFAULT_MODEL = "veo-3.1-fast-generate-preview"
_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"
_SUPPORTED_DURATIONS = (4, 6, 8)
_ASPECT_RATIO_MAP: dict[str, str] = {
    "16:9": "16:9",
    "9:16": "9:16",
}
_RESOLUTION_MAP: dict[str, str] = {
    "720P": "720p",
    "1080P": "1080p",
}


def _build_image_payload(image_data: bytes) -> dict[str, str]:
    """Build Google Veo image field from raw bytes."""
    from ._image_utils import detect_image_mime, encode_image_base64

    return {
        "bytesBase64Encoded": encode_image_base64(image_data),
        "mimeType": detect_image_mime(image_data),
    }


def _resolve_duration(seconds: int | None) -> int | None:
    if seconds is None:
        return None
    clamped = max(_SUPPORTED_DURATIONS[0], min(_SUPPORTED_DURATIONS[-1], seconds))
    return min(_SUPPORTED_DURATIONS, key=lambda d: abs(d - clamped))


def _resolve_aspect_ratio(aspect_ratio: str | None) -> str | None:
    if not aspect_ratio:
        return None
    return _ASPECT_RATIO_MAP.get(aspect_ratio)


def _resolve_resolution(resolution: str | None) -> str | None:
    if not resolution:
        return None
    return _RESOLUTION_MAP.get(resolution)


class GoogleVeoProvider(VideoGenerationProvider):
    """Google Veo video generation provider using REST API."""

    @property
    def provider_id(self) -> str:
        return "gemini"

    @property
    def display_name(self) -> str:
        return "Google Veo"

    @property
    def default_model(self) -> str:
        return _DEFAULT_MODEL

    @property
    def supported_models(self) -> tuple[ModelInfo, ...]:
        return (
            ModelInfo(id="veo-3.1-fast-generate-preview", display_name="Veo 3.1 Fast"),
            ModelInfo(id="veo-3.0-generate-preview", display_name="Veo 3.0"),
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        _t2v = ModeCapabilities(
            supported_aspect_ratios=("16:9", "9:16"),
            supported_durations=_SUPPORTED_DURATIONS,
            max_duration_seconds=8,
        )
        return ProviderCapabilities(
            max_videos=1,
            max_input_images=1,
            max_input_videos=1,
            max_duration_seconds=8,
            supported_durations=_SUPPORTED_DURATIONS,
            supports_aspect_ratio=True,
            supports_resolution=True,
            supports_audio=True,
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
            raise ValueError("Google API key missing")

        effective_model = model or config.model or _DEFAULT_MODEL
        base_url = (config.base_url or _DEFAULT_BASE_URL).rstrip("/")

        gen_config: dict[str, object] = {"numberOfVideos": 1}
        dur = _resolve_duration(duration_seconds or config.default_duration_seconds)
        if dur is not None:
            gen_config["durationSeconds"] = dur
        ar = _resolve_aspect_ratio(aspect_ratio or config.default_aspect_ratio)
        if ar:
            gen_config["aspectRatio"] = ar
        res = _resolve_resolution(resolution or config.default_resolution)
        if res:
            gen_config["resolution"] = res
        if enable_audio is True:
            gen_config["generateAudio"] = True

        body: dict[str, object] = {
            "model": f"models/{effective_model}",
            "prompt": prompt,
            "config": gen_config,
        }
        if reference_images:
            body["image"] = _build_image_payload(reference_images[0])

        timeout = httpx.Timeout(config.timeout_seconds, connect=30.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            url = f"{base_url}/v1beta/models/{effective_model}:generateVideos?key={api_key}"
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            operation = resp.json()
            op_name = operation.get("name", "")

            if config.progress_callback:
                await config.progress_callback("Submitted to Google Veo, polling operation...")

            completed = await self._poll_operation(client, base_url, op_name, api_key, config)

            if config.progress_callback:
                await config.progress_callback("Generation complete, downloading video...")

            assets = await self._extract_videos(client, completed, config)
            return ProviderOutput(assets=assets)

    async def _poll_operation(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        op_name: str,
        api_key: str,
        config: VideoGenerationConfig,
    ) -> dict[str, object]:
        for _ in range(config.max_poll_attempts):
            resp = await client.get(
                f"{base_url}/v1beta/{op_name}",
                params={"key": api_key},
            )
            resp.raise_for_status()
            op = resp.json()
            if op.get("done"):
                if op.get("error"):
                    raise RuntimeError(f"Google Veo generation failed: {op['error']}")
                return op
            await asyncio.sleep(config.poll_interval_seconds)
        raise TimeoutError("Google Veo video generation did not finish in time")

    async def _extract_videos(
        self,
        client: httpx.AsyncClient,
        operation: dict[str, object],
        config: VideoGenerationConfig,
    ) -> list[VideoAsset]:
        response = operation.get("response", {})
        if not isinstance(response, dict):
            raise ValueError("Google Veo response missing result data")
        generated = response.get("generatedVideos", [])
        if not generated:
            raise ValueError("Google Veo response has no generated videos")

        videos: list[VideoAsset] = []
        for i, entry in enumerate(generated):
            if not isinstance(entry, dict):
                continue
            video = entry.get("video", {})
            if not isinstance(video, dict):
                continue

            video_bytes_b64 = video.get("videoBytes")
            if video_bytes_b64:
                data = base64.b64decode(video_bytes_b64)
                if len(data) > config.max_download_bytes:
                    raise ValueError("Video exceeds max download size")
                videos.append(
                    VideoAsset(
                        data=data,
                        mime_type="video/mp4",
                        filename=f"video-{i + 1}.mp4",
                    )
                )
            else:
                uri = video.get("uri")
                if uri:
                    resp = await client.get(str(uri))
                    resp.raise_for_status()
                    data = resp.content
                    if len(data) > config.max_download_bytes:
                        raise ValueError("Video exceeds max download size")
                    videos.append(
                        VideoAsset(
                            data=data,
                            mime_type="video/mp4",
                            filename=f"video-{i + 1}.mp4",
                        )
                    )

        if not videos:
            raise ValueError("Google Veo: no downloadable videos in response")
        return videos

    async def health_check(self, config: VideoGenerationConfig) -> bool:
        api_key = config.api_key.get_secret_value() if config.api_key else None
        if not api_key:
            return False
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                base_url = (config.base_url or _DEFAULT_BASE_URL).rstrip("/")
                resp = await client.get(
                    f"{base_url}/v1beta/models",
                    params={"key": api_key},
                )
                return resp.status_code == 200
        except Exception:
            return False
