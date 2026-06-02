"""Video generation orchestrator.

Handles multi-provider failover, content normalization, and task lifecycle.

[INPUT]
- toolkits.llms._media_shared.normalization::NormalizationResult (POS: Used by video/generator.py and future image/generator.py to normalize user-requested geometry to provider-supported values before API calls.)
- toolkits.llms._media_shared.types::ModeCapabilities, NormalizationRecord (POS: These types are imported by video/models.py, normalization.py, and task_store.py. They define the contract between provider declarations and the normalization engine.)

[OUTPUT]
- VideoGenerator: Video generation with failover and override sanitization.

[POS]
Video generation orchestrator.
"""

from __future__ import annotations

import asyncio
import logging
import time

from myrm_agent_harness.toolkits.llms._media_shared.normalization import (
    NormalizationResult,
    normalize_params,
)
from myrm_agent_harness.toolkits.llms._media_shared.types import (
    ModeCapabilities,
    NormalizationRecord,
)

from ._helpers import is_retryable, safe_truncate, validate_video_content
from .models import (
    FailoverAttempt,
    MediaMeta,
    OverrideIgnored,
    ProviderCapabilities,
    VideoAsset,
    VideoGenerationConfig,
    VideoGenerationError,
    VideoResult,
)
from .providers.base import ProviderOutput, ProviderRegistry

logger = logging.getLogger(__name__)


class VideoGenerator:
    """Video generation with failover and override sanitization.

    Lifecycle:
    1. Resolve provider/model from config chain
    2. Sanitize request params against provider capabilities
    3. Call provider.generate() with retry
    4. Persist via media_callback if configured
    5. On failure, try next fallback config
    """

    __slots__ = ("_call_count", "_config", "_error_count", "_registry", "_total_latency_ms")

    def __init__(self, config: VideoGenerationConfig, registry: ProviderRegistry) -> None:
        self._config = config
        self._registry = registry
        self._call_count = 0
        self._error_count = 0
        self._total_latency_ms = 0.0

    @property
    def call_count(self) -> int:
        return self._call_count

    @property
    def error_count(self) -> int:
        return self._error_count

    @property
    def total_latency_ms(self) -> float:
        return self._total_latency_ms

    async def generate(
        self,
        prompt: str,
        *,
        provider_id: str | None = None,
        model: str | None = None,
        duration_seconds: int | None = None,
        aspect_ratio: str | None = None,
        resolution: str | None = None,
        enable_audio: bool | None = None,
        reference_images: list[bytes] | None = None,
        reference_videos: list[bytes] | None = None,
        extra_params: dict[str, object] | None = None,
        cancellation_event: asyncio.Event | None = None,
    ) -> VideoResult:
        """Generate video with ordered failover across provider configs.

        Priority chain: explicit args → primary config → fallback configs.
        Unsupported overrides are silently dropped and reported in the result.
        Per-provider timeout is enforced via config.timeout_seconds.
        """
        configs = self._build_config_chain(provider_id, model)
        attempts: list[FailoverAttempt] = []
        self._call_count += 1

        for idx, cfg in enumerate(configs):
            provider = self._registry.get(cfg.provider)
            if not provider:
                attempts.append(
                    FailoverAttempt(
                        provider=cfg.provider,
                        model=cfg.model,
                        error=f"Provider '{cfg.provider}' not registered",
                    )
                )
                continue

            effective_model = cfg.model or provider.default_model
            t_start = time.monotonic()
            try:
                coro = self._call_with_retry(
                    prompt=prompt,
                    config=cfg,
                    provider_id=cfg.provider,
                    model_id=effective_model,
                    duration_seconds=duration_seconds,
                    aspect_ratio=aspect_ratio,
                    resolution=resolution,
                    enable_audio=enable_audio,
                    reference_images=reference_images,
                    reference_videos=reference_videos,
                    extra_params=extra_params,
                    cancellation_event=cancellation_event,
                )
                result = await asyncio.wait_for(coro, timeout=cfg.timeout_seconds)

                result_with_attempts = VideoResult(
                    videos=result.videos,
                    provider=result.provider,
                    model=result.model,
                    latency_ms=result.latency_ms,
                    persisted_urls=result.persisted_urls,
                    attempts=attempts,
                    ignored_overrides=result.ignored_overrides,
                    normalizations=result.normalizations,
                    revised_prompt=result.revised_prompt,
                    metadata=result.metadata,
                )
                self._total_latency_ms += result.latency_ms
                return result_with_attempts

            except TimeoutError:
                elapsed_ms = (time.monotonic() - t_start) * 1000
                timeout_msg = f"Provider '{cfg.provider}/{effective_model}' timed out after {cfg.timeout_seconds}s"
                logger.warning(timeout_msg)
                attempts.append(
                    FailoverAttempt(
                        provider=cfg.provider,
                        model=effective_model,
                        error=timeout_msg,
                        latency_ms=elapsed_ms,
                    )
                )
                if idx < len(configs) - 1:
                    continue
                self._error_count += 1
                all_errors = "; ".join(f"[{a.provider}/{a.model}] {a.error}" for a in attempts)
                raise VideoGenerationError(
                    f"All {len(configs)} provider(s) failed. Attempts: {safe_truncate(all_errors, 1000)}",
                    latency_ms=sum(a.latency_ms for a in attempts),
                ) from None

            except VideoGenerationError as e:
                attempts.append(
                    FailoverAttempt(
                        provider=cfg.provider,
                        model=effective_model,
                        error=safe_truncate(str(e)),
                        latency_ms=e.latency_ms,
                    )
                )
                if idx < len(configs) - 1:
                    next_cfg = configs[idx + 1]
                    logger.warning(
                        "Video generation %s/%s failed, falling back to %s/%s",
                        cfg.provider,
                        effective_model,
                        next_cfg.provider,
                        next_cfg.model,
                    )
                    continue

                self._error_count += 1
                all_errors = "; ".join(f"[{a.provider}/{a.model}] {a.error}" for a in attempts)
                raise VideoGenerationError(
                    f"All {len(configs)} provider(s) failed. Attempts: {safe_truncate(all_errors, 1000)}",
                    latency_ms=sum(a.latency_ms for a in attempts),
                ) from e

        self._error_count += 1
        raise VideoGenerationError("No video providers configured or registered")

    def _build_config_chain(
        self,
        provider_id: str | None,
        model: str | None,
    ) -> list[VideoGenerationConfig]:
        """Build ordered list of configs to try: explicit → primary → fallbacks."""
        if provider_id or model:
            override = self._config.model_copy(
                update={k: v for k, v in {"provider": provider_id, "model": model}.items() if v is not None}
            )
            return [override, *self._config.fallback_configs]
        return [self._config, *self._config.fallback_configs]

    async def _call_with_retry(
        self,
        *,
        prompt: str,
        config: VideoGenerationConfig,
        provider_id: str,
        model_id: str,
        duration_seconds: int | None,
        aspect_ratio: str | None,
        resolution: str | None,
        enable_audio: bool | None,
        reference_images: list[bytes] | None,
        reference_videos: list[bytes] | None,
        extra_params: dict[str, object] | None,
        cancellation_event: asyncio.Event | None,
    ) -> VideoResult:
        provider = self._registry.get(provider_id)
        if not provider:
            raise VideoGenerationError(f"Provider '{provider_id}' not found")

        sanitized, ignored, normalizations = self._sanitize_overrides(
            provider_id=provider_id,
            duration_seconds=duration_seconds,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            enable_audio=enable_audio,
            reference_images=reference_images,
            reference_videos=reference_videos,
        )

        last_error: Exception | None = None
        t0 = time.monotonic()

        for attempt in range(config.max_retries + 1):
            if cancellation_event and cancellation_event.is_set():
                raise VideoGenerationError(
                    "Video generation cancelled by user",
                    latency_ms=(time.monotonic() - t0) * 1000,
                )

            try:
                output: ProviderOutput = await provider.generate(
                    prompt,
                    config,
                    model=model_id,
                    duration_seconds=sanitized.get("duration_seconds"),
                    aspect_ratio=sanitized.get("aspect_ratio"),
                    resolution=sanitized.get("resolution"),
                    enable_audio=sanitized.get("enable_audio"),
                    reference_images=sanitized.get("reference_images"),
                    reference_videos=sanitized.get("reference_videos"),
                    extra_params=extra_params,
                )

                for video in output.assets:
                    validate_video_content(video.data, provider_id, model_id)

                elapsed_ms = (time.monotonic() - t0) * 1000

                persisted_urls = await self._persist_videos(
                    output.assets,
                    prompt,
                    provider_id,
                    model_id,
                    config,
                )

                logger.info(
                    "Video generated: provider=%s model=%s elapsed=%.0fms",
                    provider_id,
                    model_id,
                    elapsed_ms,
                )
                return VideoResult(
                    videos=output.assets,
                    provider=provider_id,
                    model=model_id,
                    latency_ms=elapsed_ms,
                    persisted_urls=persisted_urls,
                    ignored_overrides=ignored,
                    normalizations=normalizations,
                    revised_prompt=output.revised_prompt,
                )

            except Exception as exc:
                last_error = exc
                if not is_retryable(exc) or attempt >= config.max_retries:
                    break
                delay = 2.0 * (attempt + 1)
                logger.warning(
                    "Video gen attempt %d/%d (%s/%s) failed: %s. Retrying in %.1fs",
                    attempt + 1,
                    config.max_retries + 1,
                    provider_id,
                    model_id,
                    safe_truncate(str(exc)),
                    delay,
                )
                await asyncio.sleep(delay)

        elapsed_ms = (time.monotonic() - t0) * 1000
        raise VideoGenerationError(
            safe_truncate(
                f"Video generation failed ({type(last_error).__name__}): {last_error} "
                f"[provider={provider_id}, model={model_id}, elapsed={elapsed_ms:.0f}ms]"
            ),
            latency_ms=elapsed_ms,
        ) from last_error

    def _sanitize_overrides(
        self,
        *,
        provider_id: str,
        duration_seconds: int | None,
        aspect_ratio: str | None,
        resolution: str | None,
        enable_audio: bool | None,
        reference_images: list[bytes] | None,
        reference_videos: list[bytes] | None,
    ) -> tuple[dict[str, object], list[OverrideIgnored], list[NormalizationRecord]]:
        """Sanitize and normalize request params against provider capabilities.

        Uses the normalization engine when mode_capabilities are declared,
        falling back to simple accept/ignore logic for providers without it.
        Returns (sanitized_params, ignored_overrides, normalization_records).
        """
        provider = self._registry.get(provider_id)
        if not provider:
            return {}, [], []

        caps = provider.capabilities
        result: dict[str, object] = {}
        ignored: list[OverrideIgnored] = []
        normalizations: list[NormalizationRecord] = []

        mode_caps = self._detect_mode_capabilities(
            caps,
            reference_images,
            reference_videos,
        )

        if mode_caps is not None:
            norm_result: NormalizationResult = normalize_params(
                caps=mode_caps,
                requested_ratio=aspect_ratio,
                requested_size=resolution,
                requested_duration=duration_seconds,
            )
            if norm_result.aspect_ratio:
                result["aspect_ratio"] = norm_result.aspect_ratio
            if norm_result.size:
                result["resolution"] = f"{norm_result.size.width}x{norm_result.size.height}"
            elif resolution is not None and caps.supports_resolution:
                result["resolution"] = resolution
            if norm_result.duration_seconds is not None:
                result["duration_seconds"] = norm_result.duration_seconds
            elif duration_seconds is not None:
                result["duration_seconds"] = duration_seconds
            if norm_result.records:
                normalizations.extend(norm_result.records)
        else:
            if duration_seconds is not None:
                result["duration_seconds"] = duration_seconds
            if aspect_ratio is not None:
                if caps.supports_aspect_ratio:
                    result["aspect_ratio"] = aspect_ratio
                else:
                    ignored.append(OverrideIgnored(key="aspect_ratio", value=aspect_ratio))
            if resolution is not None:
                if caps.supports_resolution:
                    result["resolution"] = resolution
                else:
                    ignored.append(OverrideIgnored(key="resolution", value=resolution))
        if enable_audio is not None:
            if caps.supports_audio:
                result["enable_audio"] = enable_audio
            else:
                ignored.append(OverrideIgnored(key="enable_audio", value=enable_audio))

        if reference_images:
            if caps.max_input_images > 0:
                result["reference_images"] = reference_images[: caps.max_input_images]
                if len(reference_images) > caps.max_input_images:
                    logger.warning(
                        "Provider '%s' supports max %d input images, truncating from %d",
                        provider_id,
                        caps.max_input_images,
                        len(reference_images),
                    )
            else:
                ignored.append(
                    OverrideIgnored(
                        key="reference_images",
                        value=f"{len(reference_images)} image(s)",
                    )
                )
        if reference_videos:
            if caps.max_input_videos > 0:
                result["reference_videos"] = reference_videos[: caps.max_input_videos]
            else:
                ignored.append(
                    OverrideIgnored(
                        key="reference_videos",
                        value=f"{len(reference_videos)} video(s)",
                    )
                )

        if ignored:
            logger.info(
                "Provider '%s' ignored overrides: %s",
                provider_id,
                ", ".join(f"{o.key}={o.value}" for o in ignored),
            )
        if normalizations:
            logger.info(
                "Provider '%s' normalized params: %s",
                provider_id,
                ", ".join(f"{n.field}: {n.requested} → {n.applied}" for n in normalizations),
            )

        return result, ignored, normalizations

    @staticmethod
    def _detect_mode_capabilities(
        caps: ProviderCapabilities,
        reference_images: list[bytes] | None,
        reference_videos: list[bytes] | None,
    ) -> ModeCapabilities | None:
        """Auto-detect generation mode from inputs and return matching capabilities.

        Priority: V2V > I2V > T2V (same as OpenClaw's inputCount-based detection).
        Returns None if the provider has no mode_capabilities declared.
        """
        mc = caps.mode_capabilities
        if mc is None:
            return None

        if reference_videos and mc.video_to_video:
            return mc.video_to_video
        if reference_images and mc.image_to_video:
            return mc.image_to_video
        if mc.generate:
            return mc.generate
        return None

    async def _persist_videos(
        self,
        videos: list[VideoAsset],
        prompt: str,
        provider_id: str,
        model_id: str,
        config: VideoGenerationConfig,
    ) -> list[str]:
        """Persist generated videos via callback. Failures are logged, not raised."""
        if not config.media_callback:
            return []

        urls: list[str] = []
        for video in videos:
            try:
                meta = MediaMeta(
                    prompt=prompt,
                    model=model_id,
                    provider=provider_id,
                )
                url = await config.media_callback(video.data, video.mime_type, meta)
                urls.append(url)
            except Exception:
                logger.warning(
                    "Video persistence failed for %s/%s, result still returned",
                    provider_id,
                    model_id,
                    exc_info=True,
                )
        return urls
