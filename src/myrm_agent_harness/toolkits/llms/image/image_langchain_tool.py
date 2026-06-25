"""LangChain BaseTool wrapper for ImageGenerationTools.

[INPUT]
- image_engine::ImageGenerationTools (POS: image generation engine)

[OUTPUT]
- create_image_generation_tool: returns a LangChain BaseTool named ``image_tool``

[POS]
Bridges ImageGenerationTools (engine class) to SkillAgent registry which requires BaseTool.
"""

from __future__ import annotations

import json
from typing import Literal

import httpx
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from .image_engine import ImageGenerationTools
from .validator import ImageValidator, ValidationError

def _validate_image_fetch_url(url: str, *, allow_private_networks: bool = False) -> str | None:
    """Return JSON error string when URL fails SSRF validation, else None."""
    validator = ImageValidator(ssrf_protection=True, allow_private_networks=allow_private_networks)
    try:
        validator.validate_reference_url(url.strip())
    except ValidationError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    return None


class ImageToolInput(BaseModel):
    action: Literal["generate", "edit", "list"] = Field(
        default="generate",
        description='Use "generate" to create images; "edit" to modify an image; "list" for models.',
    )
    prompt: str = Field(
        default="",
        description="Text description (required for generate/edit).",
    )
    size: str | None = Field(default=None, description='Dimensions e.g. "1024x1024" or "16:9".')
    quality: str | None = Field(default=None, description='"standard" or "hd".')
    style: str | None = Field(default=None, description='"vivid" or "natural" (DALL-E 3).')
    n: int = Field(default=1, ge=1, le=4, description="Number of images to generate.")
    reference_image_urls: list[str] | None = Field(
        default=None,
        description="Optional reference image URLs for style transfer or iterative edits.",
    )
    image_url: str | None = Field(
        default=None,
        description="Source image URL for action=edit (HTTP/HTTPS).",
    )
    mask_url: str | None = Field(
        default=None,
        description="Optional mask image URL for action=edit (transparent areas are edited).",
    )


async def _fetch_image_bytes(url: str) -> tuple[bytes, str | None, int]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        response = await client.get(url)
        response.raise_for_status()
        content_type = response.headers.get("content-type")
        body = response.content
        return body, content_type, len(body)


def create_image_generation_tool(
    engine: ImageGenerationTools,
    *,
    allow_private_networks: bool = False,
) -> BaseTool:
    """Wrap an ImageGenerationTools engine as a LangChain tool."""

    @tool("image_tool", args_schema=ImageToolInput)
    async def image_tool(
        action: Literal["generate", "edit", "list"] = "generate",
        prompt: str = "",
        size: str | None = None,
        quality: str | None = None,
        style: str | None = None,
        n: int = 1,
        reference_image_urls: list[str] | None = None,
        image_url: str | None = None,
        mask_url: str | None = None,
    ) -> str:
        """Generate, edit, or list image generation models."""
        if action == "list":
            return engine.list_models()
        if action == "edit":
            if not image_url or not image_url.strip():
                return json.dumps({"error": "image_url is required when action=edit"}, ensure_ascii=False)
            if not prompt.strip():
                return json.dumps({"error": "prompt is required when action=edit"}, ensure_ascii=False)
            url_error = _validate_image_fetch_url(image_url, allow_private_networks=allow_private_networks)
            if url_error is not None:
                return url_error
            try:
                image_bytes, image_mime, image_size = await _fetch_image_bytes(image_url.strip())
            except Exception as exc:
                return json.dumps(
                    {"error": f"Failed to fetch image_url: {type(exc).__name__}: {exc}"},
                    ensure_ascii=False,
                )
            mask_bytes = None
            if mask_url and mask_url.strip():
                mask_error = _validate_image_fetch_url(mask_url, allow_private_networks=allow_private_networks)
                if mask_error is not None:
                    return mask_error
                try:
                    mask_bytes, _, _ = await _fetch_image_bytes(mask_url.strip())
                except Exception as exc:
                    return json.dumps(
                        {"error": f"Failed to fetch mask_url: {type(exc).__name__}: {exc}"},
                        ensure_ascii=False,
                    )
            return await engine.edit_image(
                image_bytes,
                prompt,
                mask=mask_bytes,
                size=size,
                n=n,
                image_mime=image_mime,
                image_size_bytes=image_size,
            )
        if not prompt.strip():
            return '{"error": "prompt is required when action=generate"}'
        return await engine.generate_image(
            prompt,
            size=size,
            quality=quality,
            style=style,
            n=n,
            reference_image_urls=reference_image_urls,
        )

    image_tool.description = engine.tool_description
    return image_tool
