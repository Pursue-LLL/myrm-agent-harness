"""Image generation and editing via LiteLLM unified API.

[INPUT]
- litellm::aimage_generation (POS: LiteLLM unified async image generation function)
- litellm::aimage_edit (POS: LiteLLM unified async image editing function)
- litellm::{AuthenticationError, BadRequestError, NotFoundError} (POS: Non-retryable exceptions)
- core.security.http.secure_fetch::secure_get (POS: SSRF-protected outbound HTTP for URL-based image downloads)
- models::{ImageGenerationConfig, (POS: Pydantic models for DingTalk robot callback payloads.)

[OUTPUT]
- ImageGenerator: Core image generation and editing with failover, smart retry,
  latency tracking, cancellation support, instance-level metrics,
  reference image support, and exception-safe media persistence
  (both b64 and URL download paths)

[POS]
Core image generation and editing engine. Wraps LiteLLM's aimage_generation()
and aimage_edit() to provide a unified interface across 20+ providers
(DALL-E, Gemini, Stability AI, Flux, etc.).
Supports multi-model failover, reference image input (for style transfer and
continuous editing), media storage decoupling via callback, SecretStr API key
protection, error message truncation, instance-level call metrics, cancellation
via asyncio.Event, and exception-safe media persistence that handles both
b64_json and URL results.
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
from collections.abc import Awaitable, Callable
from typing import BinaryIO

from .models import (
    FailoverAttempt,
    ImageGenerationConfig,
    ImageGenerationError,
    ImageResult,
    MediaCallback,
    MediaMeta,
)

__all__ = [
    "FailoverAttempt",
    "ImageGenerationConfig",
    "ImageGenerationError",
    "ImageGenerator",
    "ImageResult",
    "MediaCallback",
]

logger = logging.getLogger(__name__)

_NON_RETRYABLE_TYPES = ("AuthenticationError", "BadRequestError", "NotFoundError")
_ERROR_MSG_MAX_LEN = 500


def _is_retryable(exc: Exception) -> bool:
    """Check if an exception is worth retrying.

    Uses type name matching to avoid importing litellm at module level.
    Non-retryable: AuthenticationError, BadRequestError, NotFoundError.
    """
    return type(exc).__name__ not in _NON_RETRYABLE_TYPES


def _safe_truncate(msg: str, max_len: int = _ERROR_MSG_MAX_LEN) -> str:
    """Truncate error message to prevent sensitive data leakage."""
    if len(msg) <= max_len:
        return msg
    return msg[:max_len] + "... [truncated]"


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


class ImageGenerator:
    """Image generation and editing via LiteLLM unified API.

    Supports 20+ providers through LiteLLM's aimage_generation() and
    aimage_edit().  Features multi-model failover, smart retry,
    instance-level metrics, and cancellation support.
    """

    def __init__(self, config: ImageGenerationConfig) -> None:
        self._config = config
        self._call_count = 0
        self._error_count = 0
        self._total_latency_ms = 0.0

    # -- Metrics properties ------------------------------------------------

    @property
    def call_count(self) -> int:
        return self._call_count

    @property
    def error_count(self) -> int:
        return self._error_count

    @property
    def total_latency_ms(self) -> float:
        return self._total_latency_ms

    # -- Public API --------------------------------------------------------

    async def generate(
        self,
        prompt: str,
        *,
        size: str | None = None,
        quality: str | None = None,
        style: str | None = None,
        n: int = 1,
        reference_image_urls: list[str] | None = None,
        cancellation_event: asyncio.Event | None = None,
        allow_private_networks: bool = False,
    ) -> ImageResult:
        """Generate an image from a text prompt with failover.

        Args:
            prompt: Text description of the desired image.
            size: Image dimensions (overrides config default).
            quality: Image quality (overrides config default).
            style: Style option (DALL-E 3: "vivid" or "natural").
            n: Number of images to generate.
            reference_image_urls: URLs of reference images for style transfer
                or continuous editing. When the provider supports it
                (e.g. Gemini multimodal, DALL-E edit), images are sent
                natively; otherwise the URLs are appended to the prompt
                as context for the model.
            cancellation_event: Set this event to cancel generation.

        Returns:
            ImageResult with URL or base64 data.

        Raises:
            ImageGenerationError: If generation fails across all models.
        """
        if reference_image_urls:
            ref_bytes = await _download_reference_images(
                reference_image_urls,
                allow_private_networks=allow_private_networks,
            )
            if ref_bytes:
                return await self._generate_with_references(
                    prompt=prompt,
                    ref_bytes=ref_bytes,
                    size=size,
                    n=n,
                    cancellation_event=cancellation_event,
                )

        from litellm import aimage_generation

        effective_size = size or self._config.default_size

        def build_kwargs(model: str, bypass_gateway: bool = False) -> dict[str, object]:
            kw: dict[str, object] = {
                "model": model,
                "prompt": prompt,
                "size": effective_size,
                "quality": quality or self._config.default_quality,
                "n": n,
                "timeout": self._config.timeout_seconds,
            }
            if not bypass_gateway and self._config.gateway_config and self._config.gateway_config.use_gateway:
                kw["api_base"] = f"{self._config.gateway_config.gateway_url.rstrip('/')}/image_gen"
                kw["api_key"] = self._config.gateway_config.auth_token
            else:
                if self._config.api_key:
                    kw["api_key"] = self._config.api_key.get_secret_value()
                if self._config.base_url:
                    kw["api_base"] = self._config.base_url
            if style:
                kw["style"] = style
            return kw

        return await self._failover(
            call_factory=lambda model, bypass_gateway=False: aimage_generation(**build_kwargs(model, bypass_gateway)),
            operation="generate",
            size_label=effective_size,
            cancellation_event=cancellation_event,
        )

    async def _generate_with_references(
        self,
        prompt: str,
        ref_bytes: list[bytes],
        *,
        size: str | None = None,
        n: int = 1,
        cancellation_event: asyncio.Event | None = None,
    ) -> ImageResult:
        """Generate using reference images via the edit API path.

        Providers that support image editing (DALL-E 2, GPT-Image-1, etc.)
        receive the first reference image as the source image. This provides
        native reference image support across most providers without
        provider-specific branching.
        """
        if len(ref_bytes) > 1:
            logger.warning(
                "Only 1 reference image supported per generation, using first of %d",
                len(ref_bytes),
            )
        return await self.edit(
            image=ref_bytes[0],
            prompt=prompt,
            size=size,
            n=n,
            cancellation_event=cancellation_event,
        )

    async def edit(
        self,
        image: bytes | BinaryIO,
        prompt: str,
        *,
        mask: bytes | BinaryIO | None = None,
        size: str | None = None,
        n: int = 1,
        cancellation_event: asyncio.Event | None = None,
    ) -> ImageResult:
        """Edit an image based on a text prompt with failover.

        Args:
            image: Source image data (PNG, < 4MB).
            prompt: Text description of the desired edit.
            mask: Optional mask image (transparent areas indicate edit regions).
            size: Output image dimensions (overrides config default).
            n: Number of edited images to generate.
            cancellation_event: Set this event to cancel editing.

        Returns:
            ImageResult with URL or base64 data.

        Raises:
            ImageGenerationError: If editing fails across all models.
        """
        from litellm import aimage_edit

        effective_size = size or self._config.default_size
        image_bytes = _to_bytes(image)
        mask_bytes = _to_bytes(mask) if mask is not None else None

        def build_kwargs(model: str, bypass_gateway: bool = False) -> dict[str, object]:
            kw: dict[str, object] = {
                "model": model,
                "image": io.BytesIO(image_bytes),
                "prompt": prompt,
                "size": effective_size,
                "n": n,
                "timeout": self._config.timeout_seconds,
            }
            if not bypass_gateway and self._config.gateway_config and self._config.gateway_config.use_gateway:
                kw["api_base"] = f"{self._config.gateway_config.gateway_url.rstrip('/')}/image_gen"
                kw["api_key"] = self._config.gateway_config.auth_token
            else:
                if self._config.api_key:
                    kw["api_key"] = self._config.api_key.get_secret_value()
                if self._config.base_url:
                    kw["api_base"] = self._config.base_url
            if mask_bytes is not None:
                kw["mask"] = io.BytesIO(mask_bytes)
            return kw

        return await self._failover(
            call_factory=lambda model, bypass_gateway=False: aimage_edit(**build_kwargs(model, bypass_gateway)),
            operation="edit",
            size_label=effective_size,
            cancellation_event=cancellation_event,
        )

    # -- Failover engine ---------------------------------------------------

    async def _failover(
        self,
        *,
        call_factory: Callable[[str, bool], Awaitable[object]],
        operation: str,
        size_label: str,
        cancellation_event: asyncio.Event | None,
    ) -> ImageResult:
        """Try primary model, then each fallback in order."""
        models = [self._config.model, *self._config.fallback_models]
        attempts: list[FailoverAttempt] = []
        self._call_count += 1

        for idx, model in enumerate(models):
            try:
                result = await self._call_with_retry(
                    call_factory=call_factory,
                    model=model,
                    operation=operation,
                    size_label=size_label,
                    cancellation_event=cancellation_event,
                )
                result_with_attempts = ImageResult(
                    url=result.url,
                    b64_json=result.b64_json,
                    revised_prompt=result.revised_prompt,
                    model=result.model,
                    latency_ms=result.latency_ms,
                    persisted_url=result.persisted_url,
                    mime_type=result.mime_type,
                    attempts=attempts,
                )
                self._total_latency_ms += result.latency_ms
                return result_with_attempts

            except ImageGenerationError as e:
                attempts.append(
                    FailoverAttempt(
                        model=model,
                        error=_safe_truncate(str(e)),
                        latency_ms=e.latency_ms,
                    )
                )
                if idx < len(models) - 1:
                    logger.warning(
                        "Image %s model %s failed, falling back to %s",
                        operation,
                        model,
                        models[idx + 1],
                    )
                    continue

                self._error_count += 1
                all_errors = "; ".join(f"[{a.model}] {a.error}" for a in attempts)
                raise ImageGenerationError(
                    f"All {len(models)} models failed for image {operation}. "
                    f"Attempts: {_safe_truncate(all_errors, 1000)}",
                    latency_ms=sum(a.latency_ms for a in attempts),
                ) from e

        raise ImageGenerationError("No models configured")

    async def _call_with_retry(
        self,
        call_factory: Callable[[str, bool], Awaitable[object]],
        *,
        model: str,
        operation: str,
        size_label: str,
        cancellation_event: asyncio.Event | None,
    ) -> ImageResult:
        """Execute a LiteLLM image API call with smart retry and gateway fallback."""
        last_error: Exception | None = None
        t0 = time.monotonic()

        bypass_gateway = False

        for attempt in range(self._config.max_retries + 1):
            if cancellation_event and cancellation_event.is_set():
                raise ImageGenerationError(
                    f"Image {operation} cancelled by user",
                    latency_ms=(time.monotonic() - t0) * 1000,
                )

            try:
                response = await call_factory(model, bypass_gateway)
                elapsed_ms = (time.monotonic() - t0) * 1000
                data = response.data[0]  # type: ignore[union-attr]

                result = ImageResult(
                    url=getattr(data, "url", None),
                    b64_json=getattr(data, "b64_json", None),
                    revised_prompt=getattr(data, "revised_prompt", None),
                    model=model,
                    latency_ms=elapsed_ms,
                )

                persist_result = await self._maybe_persist(result)
                if persist_result:
                    p_url, p_mime = persist_result
                    result = ImageResult(
                        url=result.url,
                        b64_json=result.b64_json,
                        revised_prompt=result.revised_prompt,
                        model=model,
                        latency_ms=elapsed_ms,
                        persisted_url=p_url,
                        mime_type=p_mime,
                    )

                logger.info(
                    "Image %s: model=%s size=%s elapsed=%.0fms",
                    operation,
                    model,
                    size_label,
                    elapsed_ms,
                )
                return result

            except Exception as exc:
                last_error = exc

                # Gateway Flexible Fallback Logic
                if (
                    not bypass_gateway
                    and self._config.gateway_config
                    and self._config.gateway_config.use_gateway
                    and self._config.api_key  # Must have a local API key to fallback to
                ):
                    error_msg = str(exc).lower()
                    if (
                        "502" in error_msg
                        or "503" in error_msg
                        or "504" in error_msg
                        or "402" in error_msg
                        or "insufficient" in error_msg
                        or "timeout" in error_msg
                    ):
                        logger.warning(
                            f"Gateway image {operation} failed ({_safe_truncate(str(exc))}), falling back to direct provider API (BYOK)"
                        )
                        try:
                            from myrm_agent_harness.utils.event_utils import dispatch_custom_event

                            await dispatch_custom_event(
                                "agent_status",
                                {
                                    "event": "tool_fallback",
                                    "tool": "image_generation",
                                    "fallback_type": "gateway_failover",
                                    "message": f"统一网关异常，正在无缝回退至本地直连 ({model})...",
                                },
                            )
                        except Exception:
                            pass
                        bypass_gateway = True
                        # Immediately retry this attempt with direct connection
                        continue

                if not _is_retryable(exc) or attempt >= self._config.max_retries:
                    break
                delay = 2.0 * (attempt + 1)
                logger.warning(
                    "Image %s attempt %d/%d (model=%s) failed: %s. Retrying in %.1fs",
                    operation,
                    attempt + 1,
                    self._config.max_retries + 1,
                    model,
                    _safe_truncate(str(exc)),
                    delay,
                )
                await asyncio.sleep(delay)

        elapsed_ms = (time.monotonic() - t0) * 1000
        raise ImageGenerationError(
            _safe_truncate(
                f"Image {operation} failed ({type(last_error).__name__}): {last_error} "
                f"[model={model}, elapsed={elapsed_ms:.0f}ms]"
            ),
            latency_ms=elapsed_ms,
        ) from last_error

    # -- Media persistence -------------------------------------------------

    async def _maybe_persist(self, result: ImageResult) -> tuple[str, str] | None:
        """Persist image via callback and return ``(persisted_url, mime_type)``.

        Handles both b64_json and URL results. Persistence failures are
        logged but never propagate — the caller always gets the generation
        result regardless of storage outcome.
        """
        if not self._config.media_callback:
            return None

        try:
            pair = await result.to_bytes_with_mime()
            if pair is None:
                return None
            image_bytes, mime_type = pair
            meta = MediaMeta(
                prompt=result.revised_prompt,
                model=result.model,
            )
            url = await self._config.media_callback(image_bytes, mime_type, meta)
            return (url, mime_type) if url else None
        except Exception:
            logger.warning(
                "Image persistence failed for model=%s, result still returned",
                result.model,
                exc_info=True,
            )
            return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REF_DOWNLOAD_TIMEOUT_S = 30
_REF_MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


async def _download_reference_images(
    urls: list[str],
    *,
    allow_private_networks: bool = False,
) -> list[bytes]:
    """Download reference images from URLs.

    Silently skips URLs that fail (timeout, 4xx/5xx, oversized, SSRF blocked).
    Returns empty list if all downloads fail.
    """
    from myrm_agent_harness.core.security.guards.ssrf import SSRFSecurityError
    from myrm_agent_harness.core.security.http.secure_fetch import secure_get

    results: list[bytes] = []
    for url in urls:
        try:
            resp = await secure_get(
                url,
                timeout=_REF_DOWNLOAD_TIMEOUT_S,
                enable_ssrf_shield=not allow_private_networks,
            )
            resp.raise_for_status()
            data = resp.content
            if len(data) <= _REF_MAX_SIZE_BYTES:
                results.append(data)
            else:
                logger.warning(
                    "Reference image too large (%d bytes), skipping: %s",
                    len(data),
                    url[:100],
                )
        except SSRFSecurityError as exc:
            logger.warning("Reference image blocked by SSRF protection %s: %s", url[:100], exc)
        except Exception as e:
            logger.warning("Failed to download reference image %s: %s", url[:100], e)
    return results


def _to_bytes(data: bytes | BinaryIO) -> bytes:
    """Materialise BinaryIO into bytes for safe reuse across failover retries."""
    if isinstance(data, bytes):
        return data
    return data.read()
