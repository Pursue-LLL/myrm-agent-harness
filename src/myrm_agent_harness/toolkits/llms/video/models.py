"""Data types for the video generation module.

[OUTPUT]
- VideoGenerationConfig: Video generation service configuration
- VideoResult: Structured result from a video generation request
- ProviderCapabilities: Declarative capability profile for a video provider
- FailoverAttempt: Record of a single provider attempt during failover
- MediaCallback: Async callback type for persisting generated videos
- VideoGenerationError: Exception raised when all providers fail
- OverrideIgnored: Record of an override parameter ignored by the provider
- TaskStatus: Async video generation task state

[POS]
Pure data types with no business logic. Mirrors the image module's
models.py architecture for consistency.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic.alias_generators import to_camel

from myrm_agent_harness.core.config.gateway import ToolGatewayConfig
from myrm_agent_harness.toolkits.llms._media_shared.types import (
    MediaTaskState,
    NormalizationRecord,
    ProviderModeCapabilities,
)


class MediaMeta:
    """Metadata passed alongside video bytes during persistence."""

    __slots__ = ("duration_seconds", "model", "prompt", "provider", "resolution")

    def __init__(
        self,
        prompt: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        duration_seconds: float | None = None,
        resolution: str | None = None,
    ) -> None:
        self.prompt = prompt
        self.model = model
        self.provider = provider
        self.duration_seconds = duration_seconds
        self.resolution = resolution


MediaCallback = Callable[[bytes, str, MediaMeta], Awaitable[str]]
"""Async callback: (video_bytes, mime_type, metadata) -> persisted URL.

Framework defines the interface; business layer injects the implementation.
"""


class VideoResolution(StrEnum):
    """Standard video resolution presets."""

    P480 = "480P"
    P720 = "720P"
    P1080 = "1080P"


SUPPORTED_ASPECT_RATIOS = frozenset(
    {
        "1:1",
        "2:3",
        "3:2",
        "3:4",
        "4:3",
        "4:5",
        "5:4",
        "9:16",
        "16:9",
        "21:9",
    }
)


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """Declarative capability profile for a video generation provider.

    Used by the generator to auto-sanitize request parameters:
    unsupported overrides are silently ignored and reported to the caller.

    mode_capabilities provides per-mode (T2V/I2V/V2V) capability declarations
    with supported aspect ratios, sizes, and durations. When populated, the
    generator uses normalization instead of simple accept/ignore logic.
    """

    max_videos: int = 1
    max_input_images: int = 0
    max_input_videos: int = 0
    max_duration_seconds: int | None = None
    supported_durations: tuple[int, ...] | None = None
    supported_durations_by_model: dict[str, tuple[int, ...]] | None = None
    supports_size: bool = False
    supports_aspect_ratio: bool = False
    supports_resolution: bool = False
    supports_audio: bool = False
    supports_watermark: bool = False
    mode_capabilities: ProviderModeCapabilities | None = None


@dataclass(frozen=True, slots=True)
class OverrideIgnored:
    """Record of an override parameter ignored because the provider
    does not support it."""

    key: str
    value: str | bool


@dataclass(frozen=True, slots=True)
class FailoverAttempt:
    """Record of a single provider/model attempt during failover."""

    provider: str
    model: str
    error: str
    latency_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class VideoAsset:
    """A single generated video asset."""

    data: bytes
    mime_type: str
    filename: str | None = None
    metadata: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class VideoResult:
    """Result from a video generation request."""

    videos: list[VideoAsset]
    provider: str
    model: str
    latency_ms: float = 0.0
    persisted_urls: list[str] = field(default_factory=list)
    attempts: list[FailoverAttempt] = field(default_factory=list)
    ignored_overrides: list[OverrideIgnored] = field(default_factory=list)
    normalizations: list[NormalizationRecord] = field(default_factory=list)
    revised_prompt: str | None = None
    metadata: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        """Export as a serializable dictionary for tool output."""
        out: dict[str, object] = {
            "provider": self.provider,
            "model": self.model,
            "count": len(self.videos),
            "latency_ms": round(self.latency_ms),
        }
        if self.persisted_urls:
            out["video_urls"] = self.persisted_urls
        if self.ignored_overrides:
            out["ignored_overrides"] = [{"key": o.key, "value": o.value} for o in self.ignored_overrides]
        if self.normalizations:
            out["normalizations"] = [
                {"field": n.field, "requested": n.requested, "applied": n.applied, "reason": n.reason}
                for n in self.normalizations
            ]
        if self.revised_prompt:
            out["revised_prompt"] = self.revised_prompt
        if self.attempts:
            out["failover_attempts"] = [
                {"provider": a.provider, "model": a.model, "error": a.error} for a in self.attempts
            ]
        return out


class VideoGenerationConfig(BaseModel):
    """Video generation service configuration."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    provider: str = Field(default="openai", description="Primary video generation provider ID")
    model: str = Field(default="sora", description="Primary model within the provider")
    api_key: SecretStr | None = Field(default=None, description="API key (protected from logging)")
    base_url: str | None = Field(default=None, description="Custom API base URL")
    timeout_seconds: int = Field(default=300, description="Per-request timeout (video generation is slow)")
    poll_interval_seconds: float = Field(default=3.0, description="Polling interval for async providers")
    max_poll_attempts: int = Field(default=120, description="Maximum poll attempts before timeout")
    max_retries: int = Field(default=1, ge=0, le=3, description="Max retry attempts per provider on failure")
    fallback_configs: list[VideoGenerationConfig] = Field(
        default_factory=list,
        description="Ordered fallback provider/model configs when primary fails",
    )
    gateway_config: ToolGatewayConfig | None = Field(
        default=None,
        description="Unified gateway configuration for proxying and billing",
    )
    default_aspect_ratio: str | None = Field(default=None, description="Default aspect ratio (e.g. '16:9')")
    default_resolution: str | None = Field(default=None, description="Default resolution (e.g. '720P')")
    default_duration_seconds: int | None = Field(default=None, description="Default video duration in seconds")
    media_callback: MediaCallback | None = Field(
        default=None,
        exclude=True,
        description="Async callback for persisting generated videos",
    )
    max_download_bytes: int = Field(default=200 * 1024 * 1024, description="Max video download size (200MB)")
    progress_callback: Callable[[str], Awaitable[None]] | None = Field(
        default=None,
        exclude=True,
        description="Async callback for reporting generation progress",
    )


class VideoGenerationError(Exception):
    """Raised when video generation fails."""

    def __init__(self, message: str, *, latency_ms: float = 0.0) -> None:
        super().__init__(message)
        self.latency_ms = latency_ms


TaskState = MediaTaskState
"""Backward-compatible alias. Use MediaTaskState for new code."""


@dataclass
class TaskStatus:
    """Status of an async video generation task."""

    task_id: str
    state: TaskState = TaskState.QUEUED
    provider: str = ""
    model: str = ""
    prompt: str = ""
    progress: str = ""
    provider_task_id: str = ""
    idempotency_key: str = ""
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    result: VideoResult | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "task_id": self.task_id,
            "state": self.state.value,
            "provider": self.provider,
            "model": self.model,
            "progress": self.progress,
            "created_at": self.created_at,
        }
        if self.provider_task_id:
            out["provider_task_id"] = self.provider_task_id
        if self.completed_at:
            out["completed_at"] = self.completed_at
        if self.error:
            out["error"] = self.error
        if self.result:
            out["result"] = self.result.to_dict()
        return out

    def to_persistence_dict(self) -> dict[str, object]:
        """Minimal serializable dict for task store persistence."""
        return {
            "task_id": self.task_id,
            "state": self.state.value,
            "provider": self.provider,
            "model": self.model,
            "prompt": self.prompt,
            "provider_task_id": self.provider_task_id,
            "idempotency_key": self.idempotency_key,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "error": self.error,
        }
