"""FAL.ai video generation provider (Black Forest Labs FLUX.3 Video, Kling, Luma).

Supports T2V, I2V, Keyframes-to-Video interpolation, and Video Continuation
via FAL.ai unified queue and submission API endpoints.

[INPUT]
- toolkits.llms._media_shared.types::ModeCapabilities, ProviderModeCapabilities
- core.security.http.secure_fetch::secure_get (SSRF-protected video asset downloads)

[OUTPUT]
- FalVideoProvider: class — FAL.ai Video Provider

[POS]
FAL.ai video generation provider supporting FLUX.3 Video, Keyframes, and Continuation.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import TYPE_CHECKING

import httpx

from myrm_agent_harness.core.security.http.secure_fetch import secure_get
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

_DEFAULT_MODEL = "fal-ai/flux-3-video"
_DEFAULT_BASE_URL = "https://queue.fal.run"
_SUPPORTED_DURATIONS = (5, 10)
_ASPECT_RATIO_MAP: dict[str, str] = {
    "16:9": "16:9",
    "9:16": "9:16",
    "1:1": "1:1",
    "4:3": "4:3",
    "3:4": "3:4",
}


def _encode_data_uri(image_bytes: bytes, mime_type: str = "image/png") -> str:
    """Encode image bytes into data URI scheme for FAL API."""
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


class FalVideoProvider(VideoGenerationProvider):
    """FAL.ai video generation provider with Keyframes and Continuation support."""

    @property
    def provider_id(self) -> str:
        return "fal"

    @property
    def display_name(self) -> str:
        return "FAL.ai (FLUX.3 Video & Kling)"

    @property
    def default_model(self) -> str:
        return _DEFAULT_MODEL

    @property
    def supported_models(self) -> tuple[ModelInfo, ...]:
        return (
            ModelInfo(id="fal-ai/flux-3-video", display_name="BFL FLUX.3 Video"),
            ModelInfo(id="fal-ai/kling-video/v1.6/pro", display_name="Kling 1.6 Pro (Keyframes/Continuation)"),
            ModelInfo(id="fal-ai/luma-dream-machine", display_name="Luma Dream Machine"),
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        t2v = ModeCapabilities(
            aspect_ratios=tuple(_ASPECT_RATIO_MAP.keys()),
            durations=_SUPPORTED_DURATIONS,
        )
        i2v = ModeCapabilities(
            aspect_ratios=tuple(_ASPECT_RATIO_MAP.keys()),
            durations=_SUPPORTED_DURATIONS,
        )
        v2v = ModeCapabilities(
            aspect_ratios=tuple(_ASPECT_RATIO_MAP.keys()),
            durations=_SUPPORTED_DURATIONS,
        )
        return ProviderCapabilities(
            max_videos=1,
            max_input_images=4,
            max_input_videos=1,
            max_duration_seconds=10,
            supported_durations=_SUPPORTED_DURATIONS,
            supports_aspect_ratio=True,
            supports_audio=True,
            mode_capabilities=ProviderModeCapabilities(
                text_to_video=t2v,
                image_to_video=i2v,
                video_to_video=v2v,
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
        """Submit generation request to FAL queue, poll for completion, and download assets."""
        selected_model = model or self.default_model
        api_key = config.api_key.get_secret_value() if config.api_key else ""
        if not api_key:
            raise ValueError("FAL.ai API key is required")

        base_url = (config.api_base or _DEFAULT_BASE_URL).rstrip("/")
        submit_url = f"{base_url}/{selected_model}"

        headers = {
            "Authorization": f"Key {api_key}",
            "Content-Type": "application/json",
        }

        # Build payload
        payload: dict[str, object] = {"prompt": prompt}
        if duration_seconds:
            payload["duration"] = duration_seconds
        if aspect_ratio and aspect_ratio in _ASPECT_RATIO_MAP:
            payload["aspect_ratio"] = _ASPECT_RATIO_MAP[aspect_ratio]
        if enable_audio is not None:
            payload["enable_audio"] = enable_audio

        # Keyframes or single reference image support
        if reference_images:
            if len(reference_images) >= 2:
                # Keyframes interpolation mode
                payload["image_url"] = _encode_data_uri(reference_images[0])
                payload["end_image_url"] = _encode_data_uri(reference_images[-1])
                payload["mode"] = "keyframes"
            else:
                payload["image_url"] = _encode_data_uri(reference_images[0])

        if reference_videos:
            # Video continuation mode
            # Note: FAL accepts data URI or remote storage URL for continuation
            encoded_video = base64.b64encode(reference_videos[0]).decode("ascii")
            payload["video_url"] = f"data:video/mp4;base64,{encoded_video}"
            payload["continuation"] = True

        if extra_params:
            for k, v in extra_params.items():
                if k not in payload and v is not None:
                    payload[k] = v

        client = create_httpx_client(timeout=30.0)
        try:
            # 1. Submit to queue
            logger.info("Submitting video generation to FAL queue model=%s", selected_model)
            resp = await client.post(submit_url, headers=headers, json=payload)
            if resp.status_code not in (200, 201, 202):
                raise RuntimeError(f"FAL submission failed ({resp.status_code}): {resp.text}")

            submit_data = resp.json()
            status_url = submit_data.get("status_url")
            response_url = submit_data.get("response_url")
            request_id = submit_data.get("request_id")

            if not status_url and request_id:
                status_url = f"{base_url}/{selected_model}/requests/{request_id}/status"
            if not response_url and request_id:
                response_url = f"{base_url}/{selected_model}/requests/{request_id}"

            if not status_url:
                # Direct synchronous response fallback
                video_info = submit_data.get("video") or submit_data
                video_url = video_info.get("url") if isinstance(video_info, dict) else None
                if video_url:
                    video_bytes = await secure_get(video_url)
                    return ProviderOutput(assets=[VideoAsset(data=video_bytes, mime_type="video/mp4")])
                raise RuntimeError(f"FAL returned unrecognized response: {submit_data}")

            # 2. Poll for completion
            poll_interval = 3.0
            max_attempts = int(config.timeout_seconds / poll_interval) if config.timeout_seconds else 100
            for _ in range(max_attempts):
                await asyncio.sleep(poll_interval)
                status_resp = await client.get(status_url, headers=headers)
                if status_resp.status_code != 200:
                    continue
                status_info = status_resp.json()
                status_str = status_info.get("status")

                if status_str == "COMPLETED":
                    break
                if status_str in ("FAILED", "ERROR"):
                    raise RuntimeError(f"FAL video generation failed: {status_info.get('error', 'unknown error')}")
            else:
                raise TimeoutError(f"FAL video generation timed out after {config.timeout_seconds}s")

            # 3. Retrieve final result
            res_target = response_url or status_url
            final_resp = await client.get(res_target, headers=headers)
            if final_resp.status_code != 200:
                raise RuntimeError(f"Failed to fetch FAL result: {final_resp.text}")

            result_data = final_resp.json()
            video_entry = result_data.get("video")
            video_url = video_entry.get("url") if isinstance(video_entry, dict) else None
            if not video_url:
                raise RuntimeError(f"FAL result missing video url: {result_data}")

            # 4. Download video safely with SSRF protection
            video_bytes = await secure_get(video_url)
            return ProviderOutput(
                assets=[VideoAsset(data=video_bytes, mime_type="video/mp4")],
                provider_metadata={"request_id": request_id, "model": selected_model},
            )
        finally:
            await client.aclose()

    async def health_check(self, config: VideoGenerationConfig) -> bool:
        """Probe FAL API connectivity using user API key."""
        api_key = config.api_key.get_secret_value() if config.api_key else ""
        if not api_key:
            return False

        base_url = (config.api_base or _DEFAULT_BASE_URL).rstrip("/")
        # Verify connectivity by checking queue status endpoint
        probe_url = f"{base_url}/fal-ai/flux-3-video"
        client = create_httpx_client(timeout=10.0)
        try:
            # Send OPTIONS or lightweight GET
            headers = {"Authorization": f"Key {api_key}"}
            resp = await client.get(probe_url, headers=headers)
            # 400 or 405 means endpoint exists and reached, 401/403 means auth failure
            return resp.status_code in (200, 400, 405)
        except Exception as e:
            logger.warning("FAL health check failed: %s", e)
            return False
        finally:
            await client.aclose()
