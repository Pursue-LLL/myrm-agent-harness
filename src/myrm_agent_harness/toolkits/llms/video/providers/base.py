"""Abstract base class and registry for video generation providers.

[INPUT]
- (none)

[OUTPUT]
- ModelInfo: Metadata for a model supported by a video generation prov...
- ProviderOutput: Return type for VideoGenerationProvider.generate().
- VideoGenerationProvider: Abstract base class for a video generation provider.
- ProviderRegistry: Thread-safe registry for video generation providers.

[POS]
Abstract base class and registry for video generation providers.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..models import ProviderCapabilities, VideoAsset

if TYPE_CHECKING:
    from ..models import VideoGenerationConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ModelInfo:
    """Metadata for a model supported by a video generation provider."""

    id: str
    display_name: str


@dataclass(frozen=True, slots=True)
class ProviderOutput:
    """Return type for VideoGenerationProvider.generate().

    Wraps the list of assets with optional provider-side metadata like
    revised_prompt (returned by providers that rewrite the user prompt).
    """

    assets: list[VideoAsset]
    revised_prompt: str | None = None
    provider_metadata: dict[str, object] = field(default_factory=dict)


class VideoGenerationProvider(ABC):
    """Abstract base class for a video generation provider.

    Each provider encapsulates the API-specific logic for submitting
    generation requests, polling for results, and downloading video assets.

    Providers are stateless singletons registered in the ProviderRegistry.
    Per-request state (API keys, timeouts) flows through VideoGenerationConfig.
    """

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Unique identifier for this provider (e.g. 'openai', 'google')."""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable display name (e.g. 'OpenAI Sora')."""

    @property
    @abstractmethod
    def default_model(self) -> str:
        """Default model ID when none is specified."""

    @property
    @abstractmethod
    def supported_models(self) -> tuple[ModelInfo, ...]:
        """All models this provider can serve. First entry is the default."""

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Declarative capability profile for this provider."""

    @abstractmethod
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
        """Generate video(s) from a text prompt.

        Returns a ProviderOutput containing video assets and optional metadata.
        This method handles the full lifecycle: submit → poll → download.
        """

    async def health_check(self, config: VideoGenerationConfig) -> bool:
        """Optional lightweight availability probe.

        Default implementation returns True (skip check).
        Providers can override to verify API key / endpoint reachability.
        """
        return True


class ProviderRegistry:
    """Thread-safe registry for video generation providers.

    Providers are registered by their provider_id and resolved at runtime.
    Supports both built-in and user-registered providers.
    """

    __slots__ = ("_providers",)

    def __init__(self) -> None:
        self._providers: dict[str, VideoGenerationProvider] = {}

    def register(self, provider: VideoGenerationProvider) -> None:
        pid = provider.provider_id
        if pid in self._providers:
            logger.warning("Overwriting video provider '%s'", pid)
        self._providers[pid] = provider

    def get(self, provider_id: str) -> VideoGenerationProvider | None:
        return self._providers.get(provider_id)

    def list_providers(self) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for p in self._providers.values():
            caps = p.capabilities
            info: dict[str, object] = {
                "id": p.provider_id,
                "name": p.display_name,
                "default_model": p.default_model,
                "models": [{"id": m.id, "name": m.display_name} for m in p.supported_models],
                "supports_audio": caps.supports_audio,
                "supports_image_input": caps.max_input_images > 0,
                "supports_video_input": caps.max_input_videos > 0,
                "max_duration_seconds": caps.max_duration_seconds,
            }
            mc = caps.mode_capabilities
            if mc:
                modes: dict[str, object] = {}
                for mode_name, mode_cap in (
                    ("text_to_video", mc.generate),
                    ("image_to_video", mc.image_to_video),
                    ("video_to_video", mc.video_to_video),
                ):
                    if mode_cap is None:
                        continue
                    detail: dict[str, object] = {"supported": True}
                    if mode_cap.supported_aspect_ratios:
                        detail["aspect_ratios"] = list(mode_cap.supported_aspect_ratios)
                    if mode_cap.supported_durations:
                        detail["durations"] = list(mode_cap.supported_durations)
                    if mode_cap.max_duration_seconds is not None:
                        detail["max_duration"] = mode_cap.max_duration_seconds
                    if mode_cap.supported_sizes:
                        detail["sizes"] = [f"{s.width}x{s.height}" for s in mode_cap.supported_sizes]
                    modes[mode_name] = detail
                info["supported_modes"] = modes
            result.append(info)
        return result

    def __contains__(self, provider_id: str) -> bool:
        return provider_id in self._providers

    def __len__(self) -> int:
        return len(self._providers)
