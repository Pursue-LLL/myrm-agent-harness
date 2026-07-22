"""Async video generation tools that return task_id instead of blocking.

[INPUT]
- models::VideoGenerationConfig (POS: shared video engine configuration)
- tasks::SQLiteTaskStore, Task, TaskStatus (POS: generic async job queue)
- media_task_types::TASK_TYPE_VIDEO_GENERATE (POS: media async job type SSOT)

[OUTPUT]
- AsyncVideoGenerationTools: Non-blocking enqueue adapter for video generation.
- PayloadPostprocessor: Optional server hook to seal sensitive payload fields before persist.

[POS]
Async video enqueue adapter. It snapshots execution config into Task.payload and
returns immediately so the frontend can track progress through TaskStore + SSE.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable

from myrm_agent_harness.toolkits.llms.media_task_types import TASK_TYPE_VIDEO_GENERATE
from myrm_agent_harness.toolkits.tasks import SQLiteTaskStore, Task, TaskStatus

from .models import VideoGenerationConfig

logger = logging.getLogger(__name__)

PayloadPostprocessor = Callable[[dict[str, object]], dict[str, object]]


class AsyncVideoGenerationTools:
    """Async video generation tools for non-blocking Agent integration."""

    def __init__(
        self,
        config: VideoGenerationConfig,
        task_store: SQLiteTaskStore,
        *,
        payload_postprocessor: PayloadPostprocessor | None = None,
    ) -> None:
        self._config = config
        self._task_store = task_store
        self._payload_postprocessor = payload_postprocessor

    @classmethod
    def _serialize_config(
        cls,
        config: VideoGenerationConfig,
        *,
        include_fallbacks: bool,
    ) -> dict[str, object]:
        gateway_raw = config.gateway_config.model_dump(by_alias=False) if config.gateway_config else None
        api_key: str | None = None
        if config.api_key is not None:
            api_key = config.api_key.get_secret_value()

        serialized: dict[str, object] = {
            "provider": config.provider,
            "model": config.model,
            "api_key": api_key,
            "base_url": config.base_url,
            "timeout_seconds": config.timeout_seconds,
            "poll_interval_seconds": config.poll_interval_seconds,
            "max_poll_attempts": config.max_poll_attempts,
            "max_retries": config.max_retries,
            "gateway_config": gateway_raw,
            "default_aspect_ratio": config.default_aspect_ratio,
            "default_resolution": config.default_resolution,
            "default_duration_seconds": config.default_duration_seconds,
            "max_download_bytes": config.max_download_bytes,
        }

        if include_fallbacks:
            serialized["fallback_configs"] = [
                cls._serialize_config(fallback, include_fallbacks=False) for fallback in config.fallback_configs
            ]

        return serialized

    def _execution_config_payload(self) -> dict[str, object]:
        return self._serialize_config(self._config, include_fallbacks=True)

    @staticmethod
    def _detect_mode(reference_images: list[str] | None, reference_videos: list[str] | None) -> str:
        if reference_videos:
            return "V2V (video-to-video)"
        if reference_images:
            return "I2V (image-to-video)"
        return "T2V (text-to-video)"

    async def generate_video(
        self,
        prompt: str,
        *,
        provider: str | None = None,
        model: str | None = None,
        duration_seconds: int | None = None,
        aspect_ratio: str | None = None,
        resolution: str | None = None,
        enable_audio: bool | None = None,
        reference_images: list[str] | None = None,
        reference_videos: list[str] | None = None,
        force: bool = False,
        extra_params: dict[str, object] | None = None,
        user_id: str = "local",
        agent_id: str | None = None,
        chat_id: str | None = None,
    ) -> str:
        """Enqueue a video generation task and return task metadata."""
        task_id = f"vid-{uuid.uuid4().hex[:8]}"
        payload: dict[str, object] = {
            "prompt": prompt,
            "provider_override": provider,
            "model_override": model,
            "duration_seconds": duration_seconds,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "enable_audio": enable_audio,
            "reference_images": reference_images,
            "reference_videos": reference_videos,
            "force": force,
            "extra_params": extra_params,
            **self._execution_config_payload(),
        }
        if agent_id:
            payload["agent_id"] = agent_id
        if chat_id:
            payload["chat_id"] = chat_id
        if self._payload_postprocessor is not None:
            payload = self._payload_postprocessor(payload)

        timeout_seconds = max(int(self._config.timeout_seconds), 1)
        task = Task(
            task_id=task_id,
            task_type=TASK_TYPE_VIDEO_GENERATE,
            user_id=user_id,
            status=TaskStatus.PENDING,
            payload=payload,
            priority=5,
            timeout=timeout_seconds,
        )
        await self._task_store.create_task(task)
        logger.info("Created video generation task: %s", task_id)

        mode = self._detect_mode(reference_images, reference_videos)
        return json.dumps(
            {
                "task_id": task_id,
                "task_type": TASK_TYPE_VIDEO_GENERATE,
                "status": "pending",
                "mode": mode,
                "message": "Video generation task created. Monitor status via SSE.",
            },
            ensure_ascii=False,
        )


__all__ = ["AsyncVideoGenerationTools", "PayloadPostprocessor"]
