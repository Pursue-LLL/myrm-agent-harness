"""xAI Grok Imagine video generation provider.

Supports text-to-video (T2V) and image-to-video (I2V) via the
xAI /v1/videos/generations async endpoint.  Uses the submit → poll → download
pattern consistent with other providers.

[INPUT]
- toolkits.llms._media_shared.types::ModeCapabilities, ProviderModeCapabilities (POS: These types are imported by video/models.py, normalization.py, and task_store.py. They define the contract between provider declarations and the normalization engine.)

[OUTPUT]
- XAIGrokProvider: class — xAI Grok video generation provider

[POS]
xAI Grok Imagine video generation provider.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING

import httpx

from myrm_agent_harness.infra.tls_compat import create_httpx_client

from myrm_agent_harness.toolkits.llms._media_shared.types import (
    ModeCapabilities,
    ProviderModeCapabilities,
)

from ..models import ProviderCapabilities, VideoAsset
from .base import ModelInfo, ProviderOutput, VideoGenerationProvider

if TYPE_CHECKING:
    from ..models import VideoGenerationConfig

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "grok-imagine-video"
_DEFAULT_BASE_URL = "https://api.x.ai/v1"
_I2V_MODEL = "grok-imagine-video-1.5"
_MAX_DURATION = 15
_SUPPORTED_ASPECT_RATIOS = ("1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3")
_SUPPORTED_RESOLUTIONS = ("480p", "720p")
_MAX_REFERENCE_IMAGES = 7


def _clamp_duration(
    seconds: int | None,
    *,
    has_image_input: bool = False,
) -> int:
    """Clamp requested duration to xAI limits (1–15s, 1–10s with image)."""
    value = seconds if seconds is not None else 8
    value = max(1, min(_MAX_DURATION, value))
    if has_image_input and value > 10:
        value = 10
    return value


def _resolve_aspect_ratio(aspect_ratio: str | None) -> str:
    if aspect_ratio and aspect_ratio in _SUPPORTED_ASPECT_RATIOS:
        return aspect_ratio
    return "16:9"


def _resolve_resolution(resolution: str | None) -> str:
    if not resolution:
        return "720p"
    normalized = resolution.lower().rstrip("p") + "p"
    if normalized in _SUPPORTED_RESOLUTIONS:
        return normalized
    return "720p"


def _build_image_input(image_data: bytes) -> dict[str, str]:
    """Build xAI single-image input from raw image bytes as base64 data URL."""
    from ._image_utils import encode_image_data_url

    return {"url": encode_image_data_url(image_data)}


def _build_reference_images_input(images: list[bytes]) -> list[dict[str, str]]:
    """Build xAI reference_images array for T2V style reference mode."""
    from ._image_utils import encode_image_data_url

    return [{"url": encode_image_data_url(img)} for img in images]


class XAIGrokProvider(VideoGenerationProvider):
    """xAI Grok Imagine video generation provider."""

    @property
    def provider_id(self) -> str:
        return "xai"

    @property
    def display_name(self) -> str:
        return "xAI Grok"

    @property
    def default_model(self) -> str:
        return _DEFAULT_MODEL

    @property
    def supported_models(self) -> tuple[ModelInfo, ...]:
        return (
            ModelInfo(id="grok-imagine-video", display_name="Grok Imagine Video"),
            ModelInfo(id="grok-imagine-video-1.5", display_name="Grok Imagine Video 1.5"),
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        _t2v = ModeCapabilities(
            supported_aspect_ratios=_SUPPORTED_ASPECT_RATIOS,
            max_duration_seconds=_MAX_DURATION,
        )
        _i2v = ModeCapabilities(
            supported_aspect_ratios=_SUPPORTED_ASPECT_RATIOS,
            max_duration_seconds=10,
        )
        return ProviderCapabilities(
            max_videos=1,
            max_input_images=_MAX_REFERENCE_IMAGES,
            max_input_videos=0,
            max_duration_seconds=_MAX_DURATION,
            supports_aspect_ratio=True,
            supports_resolution=True,
            supports_audio=False,
            mode_capabilities=ProviderModeCapabilities(
                generate=_t2v,
                image_to_video=_i2v,
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
            raise ValueError("xAI API key missing")

        is_single_image = bool(reference_images) and len(reference_images) == 1
        is_multi_ref = bool(reference_images) and len(reference_images) > 1
        if model:
            effective_model = model
        elif config.model:
            effective_model = config.model
        elif is_single_image:
            effective_model = _I2V_MODEL
        else:
            effective_model = _DEFAULT_MODEL
        base_url = (config.base_url or _DEFAULT_BASE_URL).rstrip("/")

        clamped_duration = _clamp_duration(
            duration_seconds or config.default_duration_seconds,
            has_image_input=is_single_image,
        )
        resolved_ar = _resolve_aspect_ratio(aspect_ratio or config.default_aspect_ratio)
        resolved_res = _resolve_resolution(resolution or config.default_resolution)

        timeout = httpx.Timeout(config.timeout_seconds, connect=30.0)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        async with create_httpx_client(timeout=timeout, headers=headers) as client:
            body: dict[str, object] = {
                "model": effective_model,
                "prompt": prompt,
                "duration": clamped_duration,
                "aspect_ratio": resolved_ar,
                "resolution": resolved_res,
            }
            if is_single_image:
                body["image"] = _build_image_input(reference_images[0])
            elif is_multi_ref:
                body["reference_images"] = _build_reference_images_input(reference_images)

            resp = await client.post(
                f"{base_url}/videos/generations",
                json=body,
                headers={"x-idempotency-key": str(uuid.uuid4())},
            )
            resp.raise_for_status()
            submitted = resp.json()
            request_id = str(submitted.get("request_id", "")).strip()
            if not request_id:
                raise ValueError("xAI response missing request_id")

            if config.progress_callback:
                await config.progress_callback(f"Submitted to xAI (id={request_id}), polling...")

            completed = await self._poll(client, base_url, request_id, config)

            video_data = completed.get("video", {})
            if not isinstance(video_data, dict):
                video_data = {}
            video_url = str(video_data.get("url", "")).strip()
            if not video_url:
                raise ValueError("xAI video response missing video URL")

            if config.progress_callback:
                await config.progress_callback("Generation complete, downloading video...")

            video_bytes = await self._download(client, video_url, config)

            video_meta: dict[str, object] = {
                "request_id": request_id,
                "model": completed.get("model", effective_model),
                "duration": video_data.get("duration", clamped_duration),
            }
            assets = [
                VideoAsset(
                    data=video_bytes,
                    mime_type="video/mp4",
                    filename=f"video-xai-{request_id[:8]}.mp4",
                    metadata=video_meta,
                )
            ]
            return ProviderOutput(assets=assets)

    async def _poll(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        request_id: str,
        config: VideoGenerationConfig,
    ) -> dict[str, object]:
        for _attempt in range(config.max_poll_attempts):
            resp = await client.get(f"{base_url}/videos/{request_id}")
            resp.raise_for_status()
            payload = resp.json()
            status = str(payload.get("status", "")).lower().strip()
            if status == "done":
                return payload
            if status in ("failed", "error", "expired", "cancelled"):
                err_obj = payload.get("error")
                err_msg = ""
                if isinstance(err_obj, dict):
                    err_msg = str(err_obj.get("message", ""))
                raise RuntimeError(err_msg or f"xAI video generation {status}")
            await asyncio.sleep(config.poll_interval_seconds)
        raise TimeoutError(f"xAI video generation {request_id} did not finish in time")

    async def _download(
        self,
        client: httpx.AsyncClient,
        video_url: str,
        config: VideoGenerationConfig,
    ) -> bytes:
        resp = await client.get(video_url)
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
            async with create_httpx_client(
                timeout=httpx.Timeout(10.0),
                headers={"Authorization": f"Bearer {api_key}"},
            ) as client:
                base_url = (config.base_url or _DEFAULT_BASE_URL).rstrip("/")
                resp = await client.get(f"{base_url}/models")
                return resp.status_code == 200
        except Exception:
            return False
