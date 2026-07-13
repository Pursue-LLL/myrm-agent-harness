"""Data types for the image generation module.

[INPUT]
- core.security.http.secure_fetch::secure_get (POS: SSRF-protected outbound HTTP for result URL download)
- pydantic (POS: Config and result schema validation)

[OUTPUT]
- ImageGenerationConfig: Image generation/editing service configuration
- ImageResult: Structured result from a generation/editing request
- FailoverAttempt: Record of a single model attempt during failover
- MediaCallback: Async callback type for persisting generated images
- ImageGenerationError: Exception raised when all models fail

[POS]
Pure data types with no business logic. Separated from generator.py
to maintain single-responsibility and keep file sizes manageable.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic.alias_generators import to_camel

from myrm_agent_harness.core.config.gateway import ToolGatewayConfig

logger = logging.getLogger(__name__)

_MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024  # 25 MB


class MediaMeta:
    """Metadata passed alongside image bytes during persistence."""

    __slots__ = ("model", "prompt", "resolution")

    def __init__(
        self,
        prompt: str | None = None,
        model: str | None = None,
        resolution: str | None = None,
    ) -> None:
        self.prompt = prompt
        self.model = model
        self.resolution = resolution


MediaCallback = Callable[[bytes, str, MediaMeta], Awaitable[str]]
"""Async callback: (image_bytes, mime_type, metadata) -> persisted URL.

Framework defines the interface; business layer injects the implementation.
"""


class ImageGenerationConfig(BaseModel):
    """Image generation/editing service configuration."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    model: str = Field(default="dall-e-3", description="Primary image generation model identifier")
    api_key: SecretStr | None = Field(default=None, description="API key (protected from logging)")
    base_url: str | None = Field(default=None, description="Custom API base URL (proxy, private deployment)")
    default_size: str = Field(
        default="1024x1024",
        description="Default image dimensions (e.g. '1024x1024', '1024x1792', '16:9')",
    )
    default_quality: str = Field(default="standard", description="Default quality (standard/hd)")
    timeout_seconds: int = Field(default=120, description="Per-model request timeout in seconds")
    max_retries: int = Field(default=1, ge=0, le=3, description="Max retry attempts per model on failure")
    fallback_models: list[str] = Field(
        default_factory=list,
        description="Ordered fallback models when primary fails",
    )
    gateway_config: ToolGatewayConfig | None = Field(
        default=None,
        description="Unified gateway configuration for proxying and billing",
    )
    media_callback: MediaCallback | None = Field(
        default=None,
        exclude=True,
        description="Async callback for persisting generated images",
    )


@dataclass(frozen=True, slots=True)
class FailoverAttempt:
    """Record of a single model attempt during failover."""

    model: str
    error: str
    latency_ms: float


@dataclass(frozen=True, slots=True)
class ImageResult:
    """Result from an image generation or editing request."""

    url: str | None
    b64_json: str | None
    revised_prompt: str | None
    model: str
    latency_ms: float = 0.0
    persisted_url: str | None = None
    mime_type: str = "image/png"
    attempts: list[FailoverAttempt] = field(default_factory=list)

    async def to_bytes_with_mime(self) -> tuple[bytes, str] | None:
        """Extract raw image bytes and detected MIME from b64_json or URL.

        Returns ``(image_bytes, mime_type)`` or ``None`` when no data is
        available.  Validates that the payload is non-empty and within
        the 25 MB download cap.
        """
        from myrm_agent_harness.utils.mime_types import detect_image_mime

        data: bytes | None = None

        if self.b64_json:
            import base64

            data = base64.b64decode(self.b64_json)
        elif self.url:
            data = await _download_url(self.url)

        if not data:
            return None

        return data, detect_image_mime(data)


class ImageGenerationError(Exception):
    """Raised when image generation or editing fails."""

    def __init__(self, message: str, *, latency_ms: float = 0.0) -> None:
        super().__init__(message)
        self.latency_ms = latency_ms


async def _download_url(url: str) -> bytes | None:
    """Download image bytes from *url* with size guard.

    Returns ``None`` on HTTP errors, empty responses, SSRF blocks, or payloads
    exceeding :data:`_MAX_DOWNLOAD_BYTES`.
    """
    from myrm_agent_harness.core.security.guards.ssrf import SSRFSecurityError
    from myrm_agent_harness.core.security.http.secure_fetch import secure_get

    try:
        resp = await secure_get(url, timeout=30.0)
        if resp.status_code != 200:
            logger.warning("Image download returned HTTP %d for %s", resp.status_code, url[:120])
            return None
        data = resp.content
        if not data:
            logger.warning("Image download returned 0 bytes for %s", url[:120])
            return None
        if len(data) > _MAX_DOWNLOAD_BYTES:
            logger.warning(
                "Image download too large (%d bytes, cap %d) for %s",
                len(data),
                _MAX_DOWNLOAD_BYTES,
                url[:120],
            )
            return None
        return data
    except SSRFSecurityError:
        logger.warning("Image download blocked by SSRF protection for %s", url[:120])
        return None
    except Exception:
        logger.warning("Image download failed for %s", url[:120], exc_info=True)
        return None
