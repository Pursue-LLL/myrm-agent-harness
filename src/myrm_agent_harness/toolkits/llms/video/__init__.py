"""Video generation module — multi-provider video generation with failover.

Provides a unified interface for generating videos from text prompts or
reference images (T2V and I2V modes) across multiple providers
(OpenAI Sora, Google Veo, Qwen, MiniMax). Includes pluggable task
persistence, client-side idempotency, and ordered failover.

Quick start:
    from myrm_agent_harness.toolkits.llms.video import (
        VideoGenerationConfig,
        VideoGenerationTools,
    )

    config = VideoGenerationConfig(provider="gemini", model="veo-3.1-fast-generate-preview")
    tools = VideoGenerationTools(config)
    result = await tools.execute(action="generate", prompt="A sunset over the ocean")
"""

from .generator import VideoGenerator
from .models import (
    FailoverAttempt,
    MediaCallback,
    MediaMeta,
    OverrideIgnored,
    ProviderCapabilities,
    TaskState,
    TaskStatus,
    VideoAsset,
    VideoGenerationConfig,
    VideoGenerationError,
    VideoResolution,
    VideoResult,
)
from .providers import ProviderRegistry, VideoGenerationProvider, get_registry
from .task_store import FileVideoTaskStore, InMemoryVideoTaskStore, VideoTaskStore
from .video_engine import VideoGenerationTools

__all__ = [
    "FailoverAttempt",
    "FileVideoTaskStore",
    "InMemoryVideoTaskStore",
    "MediaCallback",
    "MediaMeta",
    "OverrideIgnored",
    "ProviderCapabilities",
    "ProviderRegistry",
    "TaskState",
    "TaskStatus",
    "VideoAsset",
    "VideoGenerationConfig",
    "VideoGenerationError",
    "VideoGenerationProvider",
    "VideoGenerationTools",
    "VideoGenerator",
    "VideoResolution",
    "VideoResult",
    "VideoTaskStore",
    "get_registry",
]
