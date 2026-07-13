"""Image generation and editing LangChain tool wrapper.

[INPUT]
- generator::ImageGenerator (POS: Core generation/editing engine)
- models::{ImageGenerationConfig, ImageGenerationError, ImageResult} (POS: Data types)
- types::get_profile, list_profiles (POS: Model capability lookup)
- validator::ImageValidator, ValidationError (POS: Pre-call validation)

[OUTPUT]
- ImageGenerationTools: LangChain-compatible tool provider for Agent integration

[POS]
Tool wrapper that exposes ImageGenerator as LangChain tools for Agent use.
Provides three actions:
  - generate: Text-to-Image generation
  - edit: Image editing with optional mask
  - list: Discover available models and their capabilities
Pre-validates every request through the 3-layer ImageValidator.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import BinaryIO

from myrm_agent_harness.core.artifacts.constants import ArtifactType

from .generator import ImageGenerator
from .models import (
    ImageGenerationConfig,
    ImageGenerationError,
    ImageResult,
)
from .types import (
    get_profile,
    list_profiles,
)
from .validator import (
    ImageValidator,
    ValidationError,
)

logger = logging.getLogger(__name__)

ArtifactPushFn = Callable[[str, str, ArtifactType, str], None]


class ImageGenerationTools:
    """Image generation and editing tools for Agent integration.

    Wraps ImageGenerator and provides callable interfaces
    that return structured results for downstream consumption.
    Supports three actions: generate, edit, list.
    """

    def __init__(
        self,
        config: ImageGenerationConfig,
        *,
        allow_private_networks: bool = False,
        on_artifact_created: ArtifactPushFn | None = None,
    ) -> None:
        self._generator = ImageGenerator(config)
        self._config = config
        self._allow_private_networks = allow_private_networks
        self._validator = ImageValidator()
        self._on_artifact_created = on_artifact_created

    @property
    def generator(self) -> ImageGenerator:
        """Access the underlying generator (for metrics export)."""
        return self._generator

    async def generate_image(
        self,
        prompt: str,
        *,
        size: str | None = None,
        quality: str | None = None,
        style: str | None = None,
        n: int = 1,
        reference_image_urls: list[str] | None = None,
        cancellation_event: asyncio.Event | None = None,
    ) -> str:
        """Generate an image from a text description.

        Args:
            prompt: Text description of the desired image.
            size: Image dimensions (e.g. "1024x1024", "16:9").
            quality: Image quality ("standard" or "hd").
            style: Style option ("vivid" or "natural", DALL-E 3 only).
            n: Number of images to generate.
            reference_image_urls: Optional URLs of reference images for
                style transfer or continuous editing (e.g. "modify the
                previous image").
            cancellation_event: Set to cancel generation.

        Returns:
            JSON string with image URL/data and metadata.
        """
        profile = get_profile(self._config.model)
        try:
            self._validator.validate_generate(
                prompt,
                profile=profile,
                n=n,
                size=size,
            )
        except ValidationError as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

        try:
            result = await self._generator.generate(
                prompt=prompt,
                size=size,
                quality=quality,
                style=style,
                n=n,
                reference_image_urls=reference_image_urls,
                cancellation_event=cancellation_event,
                allow_private_networks=self._allow_private_networks,
            )
            self._push_artifact(result)
            return _format_result(result)
        except ImageGenerationError as e:
            logger.error("Image generation failed: %s", e)
            return json.dumps({"error": str(e)}, ensure_ascii=False)
        except Exception as e:
            logger.error("Unexpected error in image generation: %s", e)
            return json.dumps(
                {"error": f"Unexpected error: {type(e).__name__}"},
                ensure_ascii=False,
            )

    async def edit_image(
        self,
        image: bytes | BinaryIO,
        prompt: str,
        *,
        mask: bytes | BinaryIO | None = None,
        size: str | None = None,
        n: int = 1,
        image_mime: str | None = None,
        image_size_bytes: int | None = None,
        cancellation_event: asyncio.Event | None = None,
    ) -> str:
        """Edit an image based on a text prompt.

        Args:
            image: Source image data (PNG, < 4MB).
            prompt: Text description of the desired edit.
            mask: Optional mask image (transparent areas indicate edit regions).
            size: Output image dimensions.
            n: Number of edited images to generate.
            image_mime: MIME type of the input image (for validation).
            image_size_bytes: Size of input image in bytes (for validation).
            cancellation_event: Set to cancel editing.

        Returns:
            JSON string with edited image URL/data and metadata.
        """
        profile = get_profile(self._config.model)
        try:
            self._validator.validate_edit(
                prompt,
                profile=profile,
                image_mime=image_mime,
                image_size_bytes=image_size_bytes,
                n=n,
                size=size,
            )
        except ValidationError as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

        try:
            result = await self._generator.edit(
                image=image,
                prompt=prompt,
                mask=mask,
                size=size,
                n=n,
                cancellation_event=cancellation_event,
            )
            self._push_artifact(result)
            return _format_result(result)
        except ImageGenerationError as e:
            logger.error("Image editing failed: %s", e)
            return json.dumps({"error": str(e)}, ensure_ascii=False)
        except Exception as e:
            logger.error("Unexpected error in image editing: %s", e)
            return json.dumps(
                {"error": f"Unexpected error: {type(e).__name__}"},
                ensure_ascii=False,
            )

    def list_models(self) -> str:
        """List all registered image generation models and their capabilities.

        Returns:
            JSON string with model profiles.
        """
        profiles = list_profiles()
        return json.dumps(
            {
                "models": [p.to_dict() for p in profiles],
                "active_model": self._config.model,
                "fallback_models": self._config.fallback_models,
            },
            ensure_ascii=False,
        )

    def _push_artifact(self, result: ImageResult) -> None:
        """Notify caller about the generated artifact via callback."""
        if not self._on_artifact_created:
            return
        url = result.persisted_url or result.url
        if not url:
            return
        from myrm_agent_harness.utils.mime_types import extension_for_mime

        ext = extension_for_mime(result.mime_type)
        try:
            self._on_artifact_created(
                f"generated_{result.model}.{ext}",
                url,
                ArtifactType.IMAGE,
                result.mime_type,
            )
        except Exception as exc:
            logger.debug("Artifact push callback failed: %s", exc)

    # -- Tool metadata -----------------------------------------------------

    @property
    def tool_name(self) -> str:
        return "image_tool"

    @property
    def tool_description(self) -> str:
        return (
            "Image generation and editing tool. "
            'action="generate": create images from text (supports reference_image_urls for style transfer or editing previous results). '
            'action="edit": modify images with optional mask. '
            'action="list": discover available models. '
            f"Active model: {self._config.model}."
        )


def _format_result(result: ImageResult) -> str:
    """Format ImageResult as a JSON string for tool output."""
    output: dict[str, object] = {"model": result.model}
    if result.persisted_url:
        output["image_url"] = result.persisted_url
    elif result.url:
        output["image_url"] = result.url
    if result.revised_prompt:
        output["revised_prompt"] = result.revised_prompt
    if result.b64_json:
        output["image_data"] = f"[base64 image, {len(result.b64_json)} chars]"
    if result.latency_ms:
        output["latency_ms"] = round(result.latency_ms)
    if result.attempts:
        output["failover_attempts"] = [{"model": a.model, "error": a.error} for a in result.attempts]
    return json.dumps(output, ensure_ascii=False)
