"""Volcengine (ByteDance Ark) Seedance video generation provider.

Supports Seedance 2.0 / 2.0-mini / 2.0-fast models via the Ark
content generation tasks API. Uses the async submit → poll → download
pattern, mirroring the Qwen provider lifecycle.

[INPUT]
- toolkits.llms._media_shared.types::ModeCapabilities, ProviderModeCapabilities (POS: capability declarations consumed by the normalization engine)
- core.security.http.secure_fetch::secure_get (POS: SSRF-protected result video download with size cap)
- providers._image_utils.encode_image_data_url (POS: reference image bytes → base64 data URI)

[OUTPUT]
- VolcengineSeedanceProvider: Volcengine Seedance video generation provider.

[POS]
Volcengine Seedance video generation provider. First frame and
reference-image roles follow the Ark multi-image contract (first_frame
plus up to six reference images).
"""

from __future__ import annotations

import asyncio
import logging
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

_DEFAULT_MODEL = "seedance-2-0"
_DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com"
_DEFAULT_DURATION = 6
_MIN_DURATION = 4
_MAX_DURATION = 15
_MAX_REFERENCE_IMAGES = 7

# Public model ids map to Ark wire model ids.
_MODEL_WIRE_IDS: dict[str, str] = {
    "seedance-2-0": "doubao-seedance-2-0-260128",
    "seedance-2-0-mini": "doubao-seedance-2-0-mini-260615",
    "seedance-2-0-fast": "doubao-seedance-2-0-fast-260128",
}

# Per-model resolution ceiling: mini/fast variants cap at 720p.
_MAX_RESOLUTION_BY_MODEL: dict[str, str] = {
    "seedance-2-0": "1080p",
    "seedance-2-0-mini": "720p",
    "seedance-2-0-fast": "720p",
}

_RESOLUTION_RANK = {"480p": 0, "720p": 1, "1080p": 2}
_ASPECT_RATIO_TO_ARK_RATIO: dict[str, str] = {
    "16:9": "landscape",
    "9:16": "portrait",
    "1:1": "square",
}
_ARK_RATIO_TO_ASPECT_RATIO = {v: k for k, v in _ASPECT_RATIO_TO_ARK_RATIO.items()}

_TERMINAL_FAILED_STATUSES = frozenset({"failed", "cancelled", "expired", "canceled"})


def _clamp_resolution(model: str, resolution: str) -> str:
    """Clamp requested resolution to the model's ceiling (mini/fast cap at 720p)."""
    ceiling = _MAX_RESOLUTION_BY_MODEL.get(model, "1080p")
    if resolution not in _RESOLUTION_RANK or ceiling not in _RESOLUTION_RANK:
        return resolution
    if _RESOLUTION_RANK[resolution] > _RESOLUTION_RANK[ceiling]:
        return ceiling
    return resolution


class VolcengineSeedanceProvider(VideoGenerationProvider):
    """Volcengine Seedance video generation provider (Ark tasks API)."""

    @property
    def provider_id(self) -> str:
        return "volcengine"

    @property
    def display_name(self) -> str:
        return "Volcengine Seedance"

    @property
    def default_model(self) -> str:
        return _DEFAULT_MODEL

    @property
    def supported_models(self) -> tuple[ModelInfo, ...]:
        return (
            ModelInfo(id="seedance-2-0", display_name="Seedance 2.0 (1080p)"),
            ModelInfo(id="seedance-2-0-mini", display_name="Seedance 2.0 Mini (720p)"),
            ModelInfo(id="seedance-2-0-fast", display_name="Seedance 2.0 Fast (720p)"),
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        _modes = ModeCapabilities(
            supported_aspect_ratios=("16:9", "9:16", "1:1"),
            max_duration_seconds=_MAX_DURATION,
            default_duration=_DEFAULT_DURATION,
        )
        return ProviderCapabilities(
            max_videos=1,
            max_input_images=_MAX_REFERENCE_IMAGES,
            max_input_videos=0,
            max_duration_seconds=_MAX_DURATION,
            supports_aspect_ratio=True,
            supports_resolution=True,
            supports_audio=True,
            supports_watermark=True,
            mode_capabilities=ProviderModeCapabilities(
                generate=_modes,
                image_to_video=_modes,
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
            raise ValueError("Volcengine ARK API key missing")

        effective_model = model or config.model or _DEFAULT_MODEL
        if effective_model not in _MODEL_WIRE_IDS:
            raise ValueError(
                f"Unknown Volcengine Seedance model '{effective_model}'. "
                f"Supported: {', '.join(_MODEL_WIRE_IDS)}"
            )

        base_url = (config.base_url or _DEFAULT_BASE_URL).rstrip("/")
        body = self._build_body(
            prompt,
            wire_model=_MODEL_WIRE_IDS[effective_model],
            duration_seconds=duration_seconds,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            public_model=effective_model,
            enable_audio=enable_audio,
            reference_images=reference_images,
            extra_params=extra_params,
        )

        timeout = httpx.Timeout(config.timeout_seconds, connect=30.0)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        async with create_httpx_client(timeout=timeout, headers=headers) as client:
            submit_url = f"{base_url}/api/v3/contents/generations/tasks"
            resp = await client.post(submit_url, json=body)
            resp.raise_for_status()
            submitted = resp.json()
            task_id = str(submitted.get("id", "")).strip()
            if not task_id:
                raise ValueError("Volcengine response missing task id")

            if config.progress_callback:
                await config.progress_callback(
                    f"Submitted to Volcengine Seedance (task={task_id}), polling..."
                )

            completed = await self._poll(client, base_url, task_id, config)

            if config.progress_callback:
                await config.progress_callback(
                    "Generation complete, downloading video..."
                )

            assets = await self._download_videos(client, completed, config)
            return ProviderOutput(assets=assets)

    def _build_body(
        self,
        prompt: str,
        *,
        wire_model: str,
        duration_seconds: int | None,
        aspect_ratio: str | None,
        resolution: str | None,
        public_model: str,
        enable_audio: bool | None,
        reference_images: list[bytes] | None,
        extra_params: dict[str, object] | None,
    ) -> dict[str, object]:
        from ._image_utils import encode_image_data_url

        content: list[dict[str, object]] = [{"type": "text", "text": prompt}]
        if reference_images:
            images = reference_images[:_MAX_REFERENCE_IMAGES]
            for index, image_data in enumerate(images):
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": encode_image_data_url(image_data)},
                        "role": "first_frame" if index == 0 else "reference_image",
                    }
                )

        dur = duration_seconds if duration_seconds is not None else _DEFAULT_DURATION
        body: dict[str, object] = {
            "model": wire_model,
            "content": content,
            "duration": max(_MIN_DURATION, min(_MAX_DURATION, dur)),
        }

        ratio = (
            _ASPECT_RATIO_TO_ARK_RATIO.get(aspect_ratio or "") if aspect_ratio else None
        )
        if ratio:
            body["ratio"] = ratio
        if resolution:
            body["resolution"] = _clamp_resolution(public_model, resolution.lower())
        if enable_audio is not None:
            body["generate_audio"] = enable_audio

        if extra_params:
            watermark = extra_params.get("watermark")
            if isinstance(watermark, bool):
                body["watermark"] = watermark
            seed = extra_params.get("seed")
            if isinstance(seed, int):
                body["seed"] = seed
            camera_fixed = extra_params.get("camera_fixed")
            if isinstance(camera_fixed, bool):
                body["camera_fixed"] = camera_fixed

        return body

    async def _poll(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        task_id: str,
        config: VideoGenerationConfig,
    ) -> dict[str, object]:
        for _ in range(config.max_poll_attempts):
            resp = await client.get(
                f"{base_url}/api/v3/contents/generations/tasks/{task_id}"
            )
            resp.raise_for_status()
            payload: dict[str, object] = resp.json()
            status = str(payload.get("status", "")).strip().lower()
            if status in ("succeeded", "success"):
                return payload
            if status in _TERMINAL_FAILED_STATUSES:
                error = payload.get("error") or payload.get("last_error") or {}
                message = (
                    error.get("message", "") if isinstance(error, dict) else str(error)
                ) or f"Volcengine task {task_id} {status}"
                raise RuntimeError(str(message))
            await asyncio.sleep(config.poll_interval_seconds)
        raise TimeoutError(f"Volcengine Seedance task {task_id} did not finish in time")

    async def _download_videos(
        self,
        client: httpx.AsyncClient,
        payload: dict[str, object],
        config: VideoGenerationConfig,
    ) -> list[VideoAsset]:
        from myrm_agent_harness.core.security.http.secure_fetch import (
            ContentTooLargeError,
            secure_get,
        )

        urls: list[str] = []
        content = payload.get("content")
        if isinstance(content, dict):
            video_url = content.get("video_url")
            if isinstance(video_url, str) and video_url.strip():
                urls.append(video_url.strip())
        urls = list(dict.fromkeys(urls))

        if not urls:
            raise ValueError("Volcengine task succeeded without a video URL")

        videos: list[VideoAsset] = []
        for index, url in enumerate(urls):
            try:
                resp = await secure_get(
                    url,
                    timeout=config.timeout_seconds,
                    max_content_length=config.max_download_bytes,
                )
            except ContentTooLargeError as exc:
                raise ValueError(
                    f"Video exceeds max download size (>{config.max_download_bytes} bytes): {url[:80]}"
                ) from exc
            resp.raise_for_status()
            mime = resp.headers.get("content-type", "video/mp4").strip()
            metadata: dict[str, object] = {"source_url": url}
            resolution = payload.get("resolution")
            if isinstance(resolution, str) and resolution.strip():
                ark_ratio = str(payload.get("ratio", "")).strip()
                metadata["resolution"] = resolution.strip()
                if ark_ratio in _ARK_RATIO_TO_ASPECT_RATIO:
                    metadata["aspect_ratio"] = _ARK_RATIO_TO_ASPECT_RATIO[ark_ratio]
            videos.append(
                VideoAsset(
                    data=resp.content,
                    mime_type=mime,
                    filename=f"video-{index + 1}.mp4",
                    metadata=metadata,
                )
            )
        return videos

    async def health_check(self, config: VideoGenerationConfig) -> bool:
        api_key = config.api_key.get_secret_value() if config.api_key else None
        if not api_key:
            return False
        try:
            async with create_httpx_client(
                timeout=httpx.Timeout(20.0),
                headers={"Authorization": f"Bearer {api_key}"},
            ) as client:
                base_url = (config.base_url or _DEFAULT_BASE_URL).rstrip("/")
                # Zero-cost credential probe: list one task without creating any.
                resp = await client.get(
                    f"{base_url}/api/v3/contents/generations/tasks?page_size=1"
                )
                return resp.status_code == 200
        except Exception:
            return False
