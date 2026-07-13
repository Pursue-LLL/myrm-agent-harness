"""Qwen (Tongyi Wanxiang) video generation provider.

Supports Wan 2.6 / 2.7 models via the DashScope AIGC API.
Uses the async submit → poll → download pattern.

[INPUT]
- toolkits.llms._media_shared.types::ModeCapabilities, ProviderModeCapabilities (POS: These types are imported by video/models.py, normalization.py, and task_store.py. They define the contract between provider declarations and the normalization engine.)

[OUTPUT]
- QwenVideoProvider: Qwen (Tongyi Wanxiang) video generation provider.

[POS]
Qwen (Tongyi Wanxiang) video generation provider.
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

_DEFAULT_MODEL = "wan2.6-t2v"
_DEFAULT_BASE_URL = "https://dashscope-intl.aliyuncs.com"
_DEFAULT_DURATION = 5
_MAX_DURATION = 10
_RESOLUTION_TO_SIZE: dict[str, str] = {
    "480P": "832*480",
    "720P": "1280*720",
    "1080P": "1920*1080",
}


_T2V_TO_I2V: dict[str, str] = {
    "wan2.6-t2v": "wan2.6-i2v",
    "wan2.7-t2v": "wan2.7-i2v",
}


def _resolve_i2v_model(model: str) -> str:
    """Auto-switch T2V model to I2V variant when reference images are provided."""
    return _T2V_TO_I2V.get(model, model)


class QwenVideoProvider(VideoGenerationProvider):
    """Qwen (Tongyi Wanxiang) video generation provider."""

    @property
    def provider_id(self) -> str:
        return "qwen"

    @property
    def display_name(self) -> str:
        return "Qwen Cloud (Tongyi Wanxiang)"

    @property
    def default_model(self) -> str:
        return _DEFAULT_MODEL

    @property
    def supported_models(self) -> tuple[ModelInfo, ...]:
        return (
            ModelInfo(id="wan2.6-t2v", display_name="Wan 2.6 T2V"),
            ModelInfo(id="wan2.1-t2v-plus", display_name="Wan 2.1 T2V Plus"),
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        _t2v = ModeCapabilities(
            supported_aspect_ratios=("16:9", "9:16", "1:1", "4:3", "3:4"),
            supported_durations=(5, 10),
            max_duration_seconds=_MAX_DURATION,
        )
        return ProviderCapabilities(
            max_videos=1,
            max_input_images=1,
            max_input_videos=4,
            max_duration_seconds=_MAX_DURATION,
            supports_size=True,
            supports_aspect_ratio=True,
            supports_resolution=True,
            supports_audio=True,
            supports_watermark=True,
            mode_capabilities=ProviderModeCapabilities(
                generate=_t2v,
                image_to_video=ModeCapabilities(
                    supported_durations=(5, 10),
                    max_duration_seconds=_MAX_DURATION,
                ),
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
            raise ValueError("Qwen API key missing")

        effective_model = model or config.model or _DEFAULT_MODEL
        if reference_images:
            effective_model = _resolve_i2v_model(effective_model)
        base_url = (config.base_url or _DEFAULT_BASE_URL).rstrip("/")

        parameters = self._build_parameters(
            duration_seconds=duration_seconds or config.default_duration_seconds,
            aspect_ratio=aspect_ratio or config.default_aspect_ratio,
            resolution=resolution or config.default_resolution,
            enable_audio=enable_audio,
            extra_params=extra_params,
        )
        input_payload: dict[str, object] = {"prompt": prompt}
        if reference_images:
            from ._image_utils import encode_image_data_url

            input_payload["img_url"] = encode_image_data_url(reference_images[0])
        body: dict[str, object] = {
            "model": effective_model,
            "input": input_payload,
        }
        if parameters:
            body["parameters"] = parameters

        timeout = httpx.Timeout(config.timeout_seconds, connect=30.0)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        }

        async with create_httpx_client(timeout=timeout, headers=headers) as client:
            submit_url = f"{base_url}/api/v1/services/aigc/video-generation/video-synthesis"
            resp = await client.post(submit_url, json=body)
            resp.raise_for_status()
            submitted = resp.json()
            task_id = (submitted.get("output", {}).get("task_id") or "").strip()
            if not task_id:
                raise ValueError("Qwen response missing task_id")

            if config.progress_callback:
                await config.progress_callback(f"Submitted to Qwen (task={task_id}), polling...")

            completed = await self._poll(client, base_url, task_id, config)

            if config.progress_callback:
                await config.progress_callback("Generation complete, downloading video...")

            assets = await self._download_videos(client, completed, config)
            return ProviderOutput(assets=assets)

    def _build_parameters(
        self,
        *,
        duration_seconds: int | None,
        aspect_ratio: str | None,
        resolution: str | None,
        enable_audio: bool | None,
        extra_params: dict[str, object] | None,
    ) -> dict[str, object] | None:
        params: dict[str, object] = {}
        dur = duration_seconds or _DEFAULT_DURATION
        params["duration"] = max(1, min(_MAX_DURATION, dur))

        if resolution and resolution in _RESOLUTION_TO_SIZE:
            params["size"] = _RESOLUTION_TO_SIZE[resolution]
        if aspect_ratio:
            params["aspect_ratio"] = aspect_ratio
        if enable_audio is not None:
            params["enable_audio"] = enable_audio
        if extra_params:
            watermark = extra_params.get("watermark")
            if isinstance(watermark, bool):
                params["watermark"] = watermark
        return params or None

    async def _poll(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        task_id: str,
        config: VideoGenerationConfig,
    ) -> dict[str, object]:
        for _ in range(config.max_poll_attempts):
            resp = await client.get(f"{base_url}/api/v1/tasks/{task_id}")
            resp.raise_for_status()
            payload = resp.json()
            status = (payload.get("output", {}).get("task_status") or "").strip().upper()
            if status == "SUCCEEDED":
                return payload
            if status in ("FAILED", "CANCELED"):
                msg = (
                    payload.get("output", {}).get("message")
                    or payload.get("message")
                    or f"Qwen task {task_id} {status.lower()}"
                )
                raise RuntimeError(str(msg))
            await asyncio.sleep(config.poll_interval_seconds)
        raise TimeoutError(f"Qwen video generation task {task_id} did not finish in time")

    async def _download_videos(
        self,
        client: httpx.AsyncClient,
        payload: dict[str, object],
        config: VideoGenerationConfig,
    ) -> list[VideoAsset]:
        output = payload.get("output", {})
        if not isinstance(output, dict):
            raise ValueError("Qwen response missing output data")

        urls: list[str] = []
        results = output.get("results", [])
        if isinstance(results, list):
            for r in results:
                if isinstance(r, dict):
                    url = r.get("video_url")
                    if isinstance(url, str) and url.strip():
                        urls.append(url.strip())
        single_url = output.get("video_url")
        if isinstance(single_url, str) and single_url.strip():
            urls.append(single_url.strip())
        urls = list(dict.fromkeys(urls))

        if not urls:
            raise ValueError("Qwen completed without output video URLs")

        videos: list[VideoAsset] = []
        dl_timeout = config.timeout_seconds
        from myrm_agent_harness.core.security.http.secure_fetch import secure_get

        for i, url in enumerate(urls):
            resp = await secure_get(url, timeout=dl_timeout)
            resp.raise_for_status()
            data = resp.content
            if len(data) > config.max_download_bytes:
                raise ValueError("Video exceeds max download size")
            mime = resp.headers.get("content-type", "video/mp4").strip()
            videos.append(
                VideoAsset(
                    data=data,
                    mime_type=mime,
                    filename=f"video-{i + 1}.mp4",
                    metadata={"source_url": url},
                )
            )
        return videos

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
                resp = await client.get(f"{base_url}/api/v1/tasks/none")
                return resp.status_code in (200, 400, 404)
        except Exception:
            return False
