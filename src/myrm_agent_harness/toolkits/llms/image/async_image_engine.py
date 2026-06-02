"""Async image generation tools that return task_id instead of blocking.

[INPUT]
- generator::ImageGenerator (POS: Core generation/editing engine)
- models::{ImageGenerationConfig, ImageGenerationError} (POS: Data types)
- validator::ImageValidator (POS: Pre-call validation)
- tasks::TaskStore (POS: Task persistence)

[OUTPUT]
- AsyncImageGenerationTools: Non-blocking LangChain tool for Agent integration

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

from myrm_agent_harness.toolkits.tasks import SQLiteTaskStore, Task, TaskStatus

from .models import ImageGenerationConfig
from .validator import ImageValidator, ValidationError

logger = logging.getLogger(__name__)


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
        ssrf_protection: bool = False,
    ) -> None:
        self._config = config
        self._task_store = task_store
        self._validator = ImageValidator(ssrf_protection=ssrf_protection)

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

        Returns:
            JSON string with task_id for frontend monitoring:
            {"task_id": "img-12345", "status": "pending"}
        """
        # Validate inputs
        if reference_image_urls:
            for url in reference_image_urls:
                try:
                    self._validator.validate_reference_url(url)
                except ValidationError as e:
                    return json.dumps({"error": str(e)})

        # Create task
        task_id = f"img-{uuid.uuid4().hex[:8]}"
        task = Task(
            task_id=task_id,
            task_type="image_generate",
            user_id=user_id,
            status=TaskStatus.PENDING,
            payload={
                "prompt": prompt,
                "size": size,
                "quality": quality,
                "style": style,
                "count": n,
                "reference_image_urls": reference_image_urls,
            },
            priority=5,
            timeout=300,
        )

        await self._task_store.create_task(task)

        logger.info("Created image generation task: %s", task_id)

        return json.dumps(
            {
                "task_id": task_id,
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


__all__ = ["AsyncImageGenerationTools"]
