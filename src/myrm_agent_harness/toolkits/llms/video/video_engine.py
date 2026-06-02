"""Video generation tools for the agent.

Provides a set of LangChain tools for async video generation,
status polling, and task management.

[INPUT]
- agent.artifacts.constants::ArtifactType (POS: Provides ArtifactType, ArtifactMappings, is_active_content.)

[OUTPUT]
- VideoGenerationTools: Video generation tools for Agent integration.

[POS]
Video generation tools for the agent.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from myrm_agent_harness.core.artifacts.constants import ArtifactType

from .generator import VideoGenerator
from .models import (
    SUPPORTED_ASPECT_RATIOS,
    TaskState,
    TaskStatus,
    VideoGenerationConfig,
    VideoGenerationError,
    VideoResolution,
    VideoResult,
)
from .providers import ProviderRegistry, get_registry
from .task_store import InMemoryVideoTaskStore, VideoTaskStore

logger = logging.getLogger(__name__)

ArtifactPushFn = Callable[[str, str, ArtifactType, str], None]


class VideoGenerationTools:
    """Video generation tools for Agent integration.

    Provides three actions:
    - generate: Create a video from text prompts or reference images (T2V / I2V)
    - status: Check the status of the current session's video task
    - list: Discover available providers and their capabilities
    """

    __slots__ = (
        "_active_task",
        "_background_task",
        "_config",
        "_generator",
        "_on_artifact_created",
        "_registry",
        "_task_store",
    )

    def __init__(
        self,
        config: VideoGenerationConfig,
        registry: ProviderRegistry | None = None,
        task_store: VideoTaskStore | None = None,
        on_artifact_created: ArtifactPushFn | None = None,
    ) -> None:
        self._registry = registry or get_registry()
        self._task_store: VideoTaskStore = task_store or InMemoryVideoTaskStore()
        self._active_task: TaskStatus | None = None
        self._background_task: asyncio.Task[None] | None = None
        if not config.progress_callback:

            async def _progress_cb(progress: str) -> None:
                if self._active_task:
                    self._active_task.progress = progress

            config = config.model_copy(update={"progress_callback": _progress_cb})
        self._config = config
        self._generator = VideoGenerator(config, self._registry)
        self._on_artifact_created = on_artifact_created

    def _push_artifact(self, result: VideoResult) -> None:
        """Notify caller about the generated artifact via callback."""
        if not self._on_artifact_created or not result.persisted_urls:
            return
        url = result.persisted_urls[0]
        mime = result.videos[0].mime_type if result.videos else "video/mp4"
        ext = mime.split("/")[-1] if "/" in mime else "mp4"
        try:
            self._on_artifact_created(
                f"generated_{result.provider}_{result.model}.{ext}",
                url,
                ArtifactType.VIDEO,
                mime,
            )
        except Exception:
            logger.debug("Artifact push callback failed for video", exc_info=True)

    @property
    def generator(self) -> VideoGenerator:
        return self._generator

    @property
    def task_store(self) -> VideoTaskStore:
        return self._task_store

    async def execute(
        self,
        action: str = "generate",
        *,
        prompt: str | None = None,
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
        cancellation_event: asyncio.Event | None = None,
    ) -> str:
        """Dispatch to the appropriate action handler."""
        normalized = (action or "generate").strip().lower()
        if normalized == "list":
            return self.list_providers()
        if normalized == "status":
            return self._get_status()
        if normalized == "generate":
            return await self._generate(
                prompt=prompt,
                provider=provider,
                model=model,
                duration_seconds=duration_seconds,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                enable_audio=enable_audio,
                reference_images=reference_images,
                reference_videos=reference_videos,
                force=force,
                extra_params=extra_params,
                cancellation_event=cancellation_event,
            )
        return json.dumps(
            {"error": f'Unknown action "{action}". Use "generate", "status", or "list".'},
            ensure_ascii=False,
        )

    async def _generate(
        self,
        *,
        prompt: str | None,
        provider: str | None,
        model: str | None,
        duration_seconds: int | None,
        aspect_ratio: str | None,
        resolution: str | None,
        enable_audio: bool | None,
        reference_images: list[str] | None,
        reference_videos: list[str] | None,
        force: bool,
        extra_params: dict[str, object] | None,
        cancellation_event: asyncio.Event | None,
    ) -> str:
        if not prompt or not prompt.strip():
            return json.dumps(
                {"error": "prompt is required for video generation"},
                ensure_ascii=False,
            )

        if err := self._validate_params(aspect_ratio, resolution):
            return json.dumps({"error": err}, ensure_ascii=False)

        if guard := self._check_duplicate_guard():
            return guard

        resolved_images: list[bytes] | None = None
        if reference_images:
            try:
                resolved_images = await _resolve_image_inputs(reference_images)
            except (OSError, ValueError) as e:
                return json.dumps(
                    {"error": f"Failed to resolve reference images: {e}"},
                    ensure_ascii=False,
                )

        resolved_videos: list[bytes] | None = None
        if reference_videos:
            try:
                resolved_videos = await _resolve_video_inputs(reference_videos)
            except (OSError, ValueError) as e:
                return json.dumps(
                    {"error": f"Failed to resolve reference videos: {e}"},
                    ensure_ascii=False,
                )

        effective_provider = provider or self._config.provider
        effective_model = model or self._config.model
        idem_key = _compute_idempotency_key(prompt.strip(), effective_provider, effective_model, resolved_images)

        if not force and (existing := self._task_store.find_by_idempotency_key(idem_key)):
            if existing.state == TaskState.COMPLETED and existing.result:
                return json.dumps(
                    {
                        "status": "idempotent_hit",
                        "task_id": existing.task_id,
                        "message": "Returning cached result for identical request. Use force=true to regenerate.",
                        "result": existing.result.to_dict(),
                    },
                    ensure_ascii=False,
                )
            if existing.state in (TaskState.QUEUED, TaskState.GENERATING, TaskState.DOWNLOADING):
                return json.dumps(
                    {
                        "status": "idempotent_in_progress",
                        "task_id": existing.task_id,
                        "state": existing.state.value,
                        "message": "An identical request is already in progress.",
                    },
                    ensure_ascii=False,
                )

        task_id = str(uuid.uuid4())[:12]
        task = TaskStatus(
            task_id=task_id,
            state=TaskState.QUEUED,
            provider=effective_provider,
            model=effective_model,
            prompt=prompt.strip(),
            idempotency_key=idem_key,
        )
        self._active_task = task
        self._task_store.save(task)

        self._background_task = asyncio.create_task(
            self._run_generation(
                task=task,
                prompt=prompt.strip(),
                provider=provider,
                model=model,
                duration_seconds=duration_seconds,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                enable_audio=enable_audio,
                reference_images=resolved_images,
                reference_videos=resolved_videos,
                extra_params=extra_params,
                cancellation_event=cancellation_event,
            ),
            name=f"video-gen-{task_id}",
        )

        if resolved_videos:
            mode = "V2V (video-to-video)"
        elif resolved_images:
            mode = "I2V (image-to-video)"
        else:
            mode = "T2V (text-to-video)"
        return json.dumps(
            {
                "task_id": task_id,
                "status": "queued",
                "mode": mode,
                "provider": effective_provider,
                "model": effective_model,
                "message": f'Video generation ({mode}) started in background. Use action="status" to check progress.',
            },
            ensure_ascii=False,
        )

    async def _run_generation(
        self,
        *,
        task: TaskStatus,
        prompt: str,
        provider: str | None,
        model: str | None,
        duration_seconds: int | None,
        aspect_ratio: str | None,
        resolution: str | None,
        enable_audio: bool | None,
        reference_images: list[bytes] | None,
        reference_videos: list[bytes] | None,
        extra_params: dict[str, object] | None,
        cancellation_event: asyncio.Event | None,
    ) -> None:
        """Execute generation in background, updating task status throughout."""
        task.state = TaskState.GENERATING
        task.progress = "Generating video..."
        self._task_store.save(task)

        try:
            result = await self._generator.generate(
                prompt,
                provider_id=provider,
                model=model,
                duration_seconds=duration_seconds,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                enable_audio=enable_audio,
                reference_images=reference_images,
                reference_videos=reference_videos,
                extra_params=extra_params,
                cancellation_event=cancellation_event,
            )
            task.state = TaskState.COMPLETED
            task.completed_at = time.time()
            task.result = result
            task.progress = "Video generation completed successfully"
            self._task_store.save(task)
            logger.info(
                "Video generation task %s completed: provider=%s model=%s",
                task.task_id,
                result.provider,
                result.model,
            )
            self._push_artifact(result)

        except VideoGenerationError as e:
            task.state = TaskState.FAILED
            task.completed_at = time.time()
            task.error = str(e)
            task.progress = "Video generation failed"
            self._task_store.save(task)
            logger.error("Video generation task %s failed: %s", task.task_id, e)

        except Exception as e:
            task.state = TaskState.FAILED
            task.completed_at = time.time()
            task.error = f"Unexpected error: {type(e).__name__}"
            task.progress = "Video generation failed with unexpected error"
            self._task_store.save(task)
            logger.error(
                "Video generation task %s unexpected error: %s",
                task.task_id,
                e,
                exc_info=True,
            )

    def _get_status(self) -> str:
        if not self._active_task:
            return json.dumps(
                {
                    "status": "idle",
                    "message": "No active video generation task in this session.",
                },
                ensure_ascii=False,
            )

        return json.dumps(self._active_task.to_dict(), ensure_ascii=False)

    def _check_duplicate_guard(self) -> str | None:
        """Prevent re-generation if a task is still in progress."""
        if not self._active_task:
            return None

        if self._active_task.state in (TaskState.QUEUED, TaskState.GENERATING, TaskState.DOWNLOADING):
            return json.dumps(
                {
                    "status": "duplicate_blocked",
                    "task_id": self._active_task.task_id,
                    "state": self._active_task.state.value,
                    "message": (
                        "A video generation task is already in progress. "
                        'Use action="status" to check its progress. '
                        "Wait for it to complete before starting a new one."
                    ),
                },
                ensure_ascii=False,
            )

        return None

    @staticmethod
    def _validate_params(
        aspect_ratio: str | None,
        resolution: str | None,
    ) -> str | None:
        if aspect_ratio and aspect_ratio not in SUPPORTED_ASPECT_RATIOS:
            return f"Unsupported aspect_ratio '{aspect_ratio}'. Supported: {', '.join(sorted(SUPPORTED_ASPECT_RATIOS))}"
        if resolution:
            try:
                VideoResolution(resolution)
            except ValueError:
                return (
                    f"Unsupported resolution '{resolution}'. Supported: {', '.join(r.value for r in VideoResolution)}"
                )
        return None

    def list_providers(self) -> str:
        providers = self._registry.list_providers()
        return json.dumps(
            {
                "providers": providers,
                "active_provider": self._config.provider,
                "active_model": self._config.model,
            },
            ensure_ascii=False,
        )

    @property
    def tool_name(self) -> str:
        return "video_tool"

    @property
    def tool_description(self) -> str:
        return (
            "Video generation tool. "
            'action="generate": create videos from text/images/videos '
            "(T2V, I2V, V2V auto-detected from inputs). "
            'action="status": check current task progress. '
            'action="list": discover providers, models, and per-mode capabilities. '
            f"Active: {self._config.provider}/{self._config.model}."
        )

    def create_progress_callback(self) -> Callable[[str], Awaitable[None]]:
        """Create a progress callback that updates the active task's progress field."""

        async def callback(progress: str) -> None:
            if self._active_task:
                self._active_task.progress = progress

        return callback


_MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20MB per MiniMax's limit (most restrictive)
_IDEM_IMAGE_SAMPLE_BYTES = 1024


def _compute_idempotency_key(
    prompt: str,
    provider: str,
    model: str,
    images: list[bytes] | None,
) -> str:
    """Compute SHA256-based idempotency key from request parameters."""
    h = hashlib.sha256()
    h.update(prompt.encode("utf-8"))
    h.update(provider.encode("utf-8"))
    h.update(model.encode("utf-8"))
    if images:
        for img in images:
            h.update(img[:_IDEM_IMAGE_SAMPLE_BYTES])
    return h.hexdigest()[:24]


_MAX_VIDEO_BYTES = 100 * 1024 * 1024  # 100MB


async def _resolve_media_sources(
    sources: list[str],
    *,
    max_bytes: int,
    timeout_seconds: float,
    media_label: str,
    allow_data_url: bool = False,
) -> list[bytes]:
    """Resolve media source strings (file path / URL / data URL) to raw bytes.

    Shared resolver for both video and image inputs.
    SSRF validation is performed before any HTTP download.
    """
    from pathlib import Path

    from myrm_agent_harness.toolkits.llms._media_shared.security import validate_media_url

    results: list[bytes] = []
    for src in sources:
        src = src.strip()
        if not src:
            continue

        if allow_data_url and src.startswith("data:"):
            import base64

            header_end = src.find(",")
            if header_end < 0:
                raise ValueError("Invalid data URL: missing comma separator")
            data = base64.b64decode(src[header_end + 1 :])
        elif src.startswith(("http://", "https://")):
            verdict = validate_media_url(src)
            if not verdict.allowed:
                raise ValueError(f"URL blocked by SSRF protection: {verdict.reason} ({src[:80]})")
            import httpx

            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds)) as client:
                resp = await client.get(src)
                resp.raise_for_status()
                data = resp.content
        else:
            path = Path(src)
            if not path.is_file():
                raise FileNotFoundError(f"{media_label} file not found: {src}")
            data = path.read_bytes()

        if len(data) > max_bytes:
            raise ValueError(f"{media_label} too large ({len(data)} bytes > {max_bytes} bytes): {src[:80]}")
        results.append(data)
    return results


async def _resolve_video_inputs(sources: list[str]) -> list[bytes]:
    """Resolve video source strings (file path / URL) to raw bytes."""
    return await _resolve_media_sources(
        sources,
        max_bytes=_MAX_VIDEO_BYTES,
        timeout_seconds=60.0,
        media_label="Video",
    )


async def _resolve_image_inputs(sources: list[str]) -> list[bytes]:
    """Resolve image source strings (file path / URL / base64 data URL) to raw bytes."""
    return await _resolve_media_sources(
        sources,
        max_bytes=_MAX_IMAGE_BYTES,
        timeout_seconds=30.0,
        media_label="Image",
        allow_data_url=True,
    )


