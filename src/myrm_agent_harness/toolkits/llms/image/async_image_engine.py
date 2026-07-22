"""Async image generation tools that return task_id instead of blocking.

[INPUT]
- generator::ImageGenerator (POS: Core generation/editing engine)
- models::{ImageGenerationConfig, ImageGenerationError} (POS: Data types)
- validator::ImageValidator (POS: Pre-call validation)
- tasks::SQLiteTaskStore, Task, TaskStatus (POS: generic async job queue)
- media_task_types::TASK_TYPE_IMAGE_GENERATE (POS: media async job type SSOT)

[OUTPUT]
- AsyncImageGenerationTools: Non-blocking enqueue; optional PayloadPostprocessor runs before TaskStore persist
- PayloadPostprocessor: Callable hook for server-side secret sealing (harness stays crypto-agnostic)

[POS]
Async version of ImageGenerationTools that creates tasks instead of blocking.
Returns task_id immediately, allowing user to continue conversation while
image generates in background. Frontend monitors task status via SSE and
dynamically renders placeholder -> real image.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable

from myrm_agent_harness.toolkits.llms.media_task_types import TASK_TYPE_IMAGE_GENERATE
from myrm_agent_harness.toolkits.tasks import SQLiteTaskStore, Task, TaskStatus

from .models import ImageGenerationConfig
from .validator import ImageValidator, ValidationError

logger = logging.getLogger(__name__)

PayloadPostprocessor = Callable[[dict[str, object]], dict[str, object]]


class AsyncImageGenerationTools:
    """Async image generation tools for non-blocking Agent integration.

    Key differences from ImageGenerationTools:
    - Returns task_id instead of blocking
    - Creates Task in TaskStore
    - Worker executes task in background
    - Frontend monitors task status via SSE
    """

    def __init__(
        self,
        config: ImageGenerationConfig,
        task_store: SQLiteTaskStore,
        *,
        allow_private_networks: bool = False,
        payload_postprocessor: PayloadPostprocessor | None = None,
    ) -> None:
        self._config = config
        self._task_store = task_store
        self._allow_private_networks = allow_private_networks
        self._validator = ImageValidator()
        self._payload_postprocessor = payload_postprocessor

    def _execution_config_payload(self) -> dict[str, object]:
        """Serialize non-callback execution fields for the worker snapshot."""
        cfg = self._config
        gateway_raw = cfg.gateway_config.model_dump(by_alias=False) if cfg.gateway_config else None
        api_key: str | None = None
        if cfg.api_key is not None:
            api_key = cfg.api_key.get_secret_value()
        return {
            "model": cfg.model,
            "fallback_models": list(cfg.fallback_models),
            "default_size": cfg.default_size,
            "default_quality": cfg.default_quality,
            "timeout_seconds": cfg.timeout_seconds,
            "max_retries": cfg.max_retries,
            "gateway_config": gateway_raw,
            "api_key": api_key,
        }

    async def generate_image(
        self,
        prompt: str,
        *,
        size: str | None = None,
        quality: str | None = None,
        style: str | None = None,
        n: int = 1,
        reference_image_urls: list[str] | None = None,
        user_id: str = "local",
        agent_id: str | None = None,
        chat_id: str | None = None,
    ) -> str:
        """Generate an image asynchronously.

        Args:
            prompt: Text description of the desired image.
            size: Image dimensions (e.g. "1024x1024", "16:9").
            quality: Image quality ("standard" or "hd").
            style: Style option ("vivid" or "natural").
            n: Number of images to generate.
            reference_image_urls: Optional URLs of reference images.
            user_id: User who owns this task (for multi-tenant isolation).
            agent_id: Agent that enqueued the task (opaque metadata for server resolver).
            chat_id: Chat session id for media library persistence.

        Returns:
            JSON string with task_id for frontend monitoring:
            {"task_id": "img-12345", "status": "pending"}
        """
        task_id = f"img-{uuid.uuid4().hex[:8]}"
        payload: dict[str, object] = {
            "prompt": prompt,
            "size": size,
            "quality": quality,
            "style": style,
            "count": n,
            "reference_image_urls": reference_image_urls,
            "allow_private_networks": self._allow_private_networks,
            **self._execution_config_payload(),
        }
        if agent_id:
            payload["agent_id"] = agent_id
        if chat_id:
            payload["chat_id"] = chat_id
        if self._payload_postprocessor is not None:
            payload = self._payload_postprocessor(payload)
        task = Task(
            task_id=task_id,
            task_type=TASK_TYPE_IMAGE_GENERATE,
            user_id=user_id,
            status=TaskStatus.PENDING,
            payload=payload,
            priority=5,
            timeout=300,
        )

        await self._task_store.create_task(task)

        logger.info("Created image generation task: %s", task_id)

        return json.dumps(
            {
                "task_id": task_id,
                "task_type": TASK_TYPE_IMAGE_GENERATE,
                "status": "pending",
                "message": "Image generation task created. Monitor status via SSE.",
            }
        )

    async def list_models(self) -> str:
        """List available image generation models."""
        from .types import list_profiles

        profiles = list_profiles()
        return json.dumps(
            {
                "models": [p.to_dict() for p in profiles],
                "active_model": self._config.model,
            }
        )


__all__ = ["AsyncImageGenerationTools", "PayloadPostprocessor"]
