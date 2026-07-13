"""MiniMax (Hailuo Hailuo) video generation provider.

Supports Hailuo 2.3 / 02 / I2V models via the MiniMax API.
Uses the submit → poll → download pattern with file_id or direct URL.

[INPUT]
- toolkits.llms._media_shared.types::ModeCapabilities, ProviderModeCapabilities (POS: These types are imported by video/models.py, normalization.py, and task_store.py. They define the contract between provider declarations and the normalization engine.)

[OUTPUT]
- MiniMaxVideoProvider: class — Mini Max Video Provider

[POS]
MiniMax (Hailuo Hailuo) video generation provider.
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

_DEFAULT_MODEL = "MiniMax-Hailuo-2.3"
_DEFAULT_BASE_URL = "https://api.minimax.io"
_MODEL_DURATIONS: dict[str, tuple[int, ...]] = {
    "MiniMax-Hailuo-2.3": (6, 10),
    "MiniMax-Hailuo-02": (6, 10),
}


def _resolve_duration(model: str, seconds: int | None) -> int | None:
    if seconds is None:
        return None
    rounded = max(1, seconds)
    allowed = _MODEL_DURATIONS.get(model)
    if not allowed:
        return rounded
    return min(allowed, key=lambda d: abs(d - rounded))


def _assert_base_resp(base_resp: dict[str, object] | None, context: str) -> None:
    if not base_resp or not isinstance(base_resp, dict):
        return
    code = base_resp.get("status_code")
    if isinstance(code, int) and code != 0:
        msg = base_resp.get("status_msg", "unknown error")
        raise RuntimeError(f"{context} ({code}): {msg}")


class MiniMaxVideoProvider(VideoGenerationProvider):
    """MiniMax (Hailuo) video generation provider."""

    @property
    def provider_id(self) -> str:
        return "minimax"

    @property
    def display_name(self) -> str:
        return "MiniMax Hailuo (Hailuo)"

    @property
    def default_model(self) -> str:
        return _DEFAULT_MODEL

    @property
    def supported_models(self) -> tuple[ModelInfo, ...]:
        return (
            ModelInfo(id="MiniMax-Hailuo-2.3", display_name="Hailuo 2.3"),
            ModelInfo(id="MiniMax-Hailuo-2.0", display_name="Hailuo 2.0"),
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            max_videos=1,
            max_input_images=1,
            max_input_videos=1,
            max_duration_seconds=10,
            supported_durations_by_model=_MODEL_DURATIONS,
            supports_resolution=True,
            mode_capabilities=ProviderModeCapabilities(
                generate=ModeCapabilities(
                    supported_durations=(6, 10),
                    max_duration_seconds=10,
                ),
                image_to_video=ModeCapabilities(
                    supported_durations=(6, 10),
                    max_duration_seconds=10,
                ),
                video_to_video=ModeCapabilities(
                    supported_durations=(6, 10),
                    max_duration_seconds=10,
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
            raise ValueError("MiniMax API key missing")

        effective_model = model or config.model or _DEFAULT_MODEL
        base_url = (config.base_url or _DEFAULT_BASE_URL).rstrip("/")

        body: dict[str, object] = {
            "model": effective_model,
            "prompt": prompt,
        }
        dur = _resolve_duration(
            effective_model,
            duration_seconds or config.default_duration_seconds,
        )
        if dur is not None:
            body["duration"] = dur
        effective_resolution = resolution or config.default_resolution
        if effective_resolution:
            body["resolution"] = effective_resolution

        if reference_videos:
            import base64 as b64

            body["first_frame_video"] = b64.b64encode(reference_videos[0]).decode()
        elif reference_images:
            from ._image_utils import encode_image_data_url

            body["first_frame_image"] = encode_image_data_url(reference_images[0])

        timeout = httpx.Timeout(config.timeout_seconds, connect=30.0)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        async with create_httpx_client(timeout=timeout, headers=headers) as client:
            resp = await client.post(f"{base_url}/v1/video_generation", json=body)
            resp.raise_for_status()
            submitted = resp.json()
            _assert_base_resp(submitted.get("base_resp"), "MiniMax video generation failed")
            task_id = (submitted.get("task_id") or "").strip()
            if not task_id:
                raise ValueError("MiniMax response missing task_id")

            if config.progress_callback:
                await config.progress_callback(f"Submitted to MiniMax (task={task_id}), polling...")

            completed = await self._poll(client, base_url, task_id, config)

            if config.progress_callback:
                await config.progress_callback("Generation complete, downloading video...")

            assets = await self._download(client, base_url, completed, config)
            return ProviderOutput(assets=assets)

    async def _poll(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        task_id: str,
        config: VideoGenerationConfig,
    ) -> dict[str, object]:
        for _ in range(config.max_poll_attempts):
            resp = await client.get(
                f"{base_url}/v1/query/video_generation",
                params={"task_id": task_id},
            )
            resp.raise_for_status()
            payload = resp.json()
            _assert_base_resp(payload.get("base_resp"), "MiniMax video generation failed")
            status = (payload.get("status") or "").strip()
            if status == "Success":
                return payload
            if status == "Fail":
                msg = payload.get("base_resp", {}).get("status_msg") or "MiniMax video generation failed"
                raise RuntimeError(str(msg))
            await asyncio.sleep(config.poll_interval_seconds)
        raise TimeoutError(f"MiniMax task {task_id} did not finish in time")

    async def _download(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        completed: dict[str, object],
        config: VideoGenerationConfig,
    ) -> list[VideoAsset]:
        video_url = completed.get("video_url")
        file_id = completed.get("file_id")

        if isinstance(video_url, str) and video_url.strip():
            return [await self._download_from_url(client, video_url.strip(), config)]

        if isinstance(file_id, str) and file_id.strip():
            return [await self._download_from_file_id(client, base_url, file_id.strip(), config)]

        raise ValueError("MiniMax completed without video URL or file_id")

    async def _download_from_url(
        self,
        client: httpx.AsyncClient,
        url: str,
        config: VideoGenerationConfig,
    ) -> VideoAsset:
        from myrm_agent_harness.core.security.http.secure_fetch import secure_get

        resp = await secure_get(url, timeout=config.timeout_seconds)
        resp.raise_for_status()
        data = resp.content
        if len(data) > config.max_download_bytes:
            raise ValueError("Video exceeds max download size")
        mime = resp.headers.get("content-type", "video/mp4").strip()
        ext = "webm" if "webm" in mime else "mp4"
        return VideoAsset(data=data, mime_type=mime, filename=f"video-1.{ext}")

    async def _download_from_file_id(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        file_id: str,
        config: VideoGenerationConfig,
    ) -> VideoAsset:
        resp = await client.get(
            f"{base_url}/v1/files/retrieve",
            params={"file_id": file_id},
        )
        resp.raise_for_status()
        metadata = resp.json()
        _assert_base_resp(metadata.get("base_resp"), "MiniMax file metadata failed")
        dl_url = (metadata.get("file", {}).get("download_url") or "").strip()
        if not dl_url:
            raise ValueError("MiniMax file metadata missing download_url")
        return await self._download_from_url(client, dl_url, config)

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
                resp = await client.get(f"{base_url}/v1/files/list")
                return resp.status_code == 200
        except Exception:
            return False
