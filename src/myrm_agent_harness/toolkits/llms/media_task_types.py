"""Image async-job payload/result DTOs for TaskStore integration.

Domain-specific task shapes live here (llms media stack), not in the generic
``toolkits/tasks`` queue protocol. ``Task.payload`` / ``Task.result`` remain
``dict[str, object]`` at the queue layer.

[INPUT]
- (none)

[OUTPUT]
- ImageGenerationPayload / ImageGenerationResult / ImageData
- TASK_TYPE_IMAGE_GENERATE: canonical async job type id
- get_media_task_payload_class / get_media_task_result_class

[POS]
Image-domain DTOs for async jobs enqueued through ``toolkits/tasks`` (consumed by
``llms/image/async_image_engine.py`` and server ``ImageTaskExecutor``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

TASK_TYPE_IMAGE_GENERATE = "image_generate"
TASK_TYPE_VIDEO_GENERATE = "video_generate"


@dataclass
class ImageGenerationPayload:
    """Image generation task input parameters."""

    prompt: str
    size: str | None = None
    quality: str | None = None
    style: str | None = None
    count: int = 1
    reference_image_urls: list[str] | None = None
    allow_private_networks: bool = False
    model: str | None = None
    provider: str | None = None
    usage: str | None = None
    description: str | None = None


@dataclass
class ImageData:
    """Single generated image data."""

    url: str
    width: int | None = None
    height: int | None = None
    mime_type: str = "image/png"
    thumbnail_url: str | None = None
    size_bytes: int | None = None


@dataclass
class ImageGenerationResult:
    """Image generation task output."""

    images: list[ImageData]
    prompt: str
    model: str
    provider: str
    latency_ms: int | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class VideoGenerationPayload:
    """Video generation task input parameters."""

    prompt: str
    provider_override: str | None = None
    model_override: str | None = None
    duration_seconds: int | None = None
    aspect_ratio: str | None = None
    resolution: str | None = None
    enable_audio: bool | None = None
    reference_images: list[str] | None = None
    reference_videos: list[str] | None = None
    force: bool = False
    model: str | None = None
    provider: str | None = None


@dataclass
class VideoGenerationResult:
    """Video generation task output."""

    video_urls: list[str]
    provider: str
    model: str
    count: int = 1
    latency_ms: int | None = None
    revised_prompt: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


_PAYLOAD_CLASS_BY_TASK_TYPE: dict[str, type[object]] = {
    TASK_TYPE_IMAGE_GENERATE: ImageGenerationPayload,
    TASK_TYPE_VIDEO_GENERATE: VideoGenerationPayload,
}

_RESULT_CLASS_BY_TASK_TYPE: dict[str, type[object]] = {
    TASK_TYPE_IMAGE_GENERATE: ImageGenerationResult,
    TASK_TYPE_VIDEO_GENERATE: VideoGenerationResult,
}


def get_media_task_payload_class(task_type: str) -> type[object] | None:
    """Return payload dataclass for a supported async media task type."""
    return _PAYLOAD_CLASS_BY_TASK_TYPE.get(task_type)


def get_media_task_result_class(task_type: str) -> type[object] | None:
    """Return result dataclass for a supported async media task type."""
    return _RESULT_CLASS_BY_TASK_TYPE.get(task_type)


__all__ = [
    "TASK_TYPE_IMAGE_GENERATE",
    "TASK_TYPE_VIDEO_GENERATE",
    "ImageData",
    "ImageGenerationPayload",
    "ImageGenerationResult",
    "VideoGenerationPayload",
    "VideoGenerationResult",
    "get_media_task_payload_class",
    "get_media_task_result_class",
]
