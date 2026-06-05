"""Image search tool — DuckDuckGo-powered image retrieval for agents.

Provides a LangChain-compatible tool factory for image search using DuckDuckGo's
free API (no API key required). Designed for use as a reference-image retrieval
step before image generation, or standalone visual information lookup.

[INPUT]
- (none — uses ddgs library internally)

[OUTPUT]
- create_image_search_tool: Factory function returning a LangChain tool

[POS]
Image search tool. Provides structured image search results (title, original URL,
thumbnail URL, source page) via DuckDuckGo, with async execution, caching,
and timeout protection.
"""

from __future__ import annotations

import asyncio
import json
import logging

from langchain.tools import tool
from pydantic import BaseModel, Field

from myrm_agent_harness.utils.lru_cache import LRUCache

logger = logging.getLogger(__name__)

_image_cache: LRUCache[list[dict[str, str]]] = LRUCache(maxsize=100, ttl=900, id="image_search_cache")

_SEARCH_TIMEOUT_SECONDS = 30
_DEFAULT_MAX_RESULTS = 5


def _search_images_sync(
    query: str,
    max_results: int,
    region: str,
    safesearch: str,
    size: str | None,
    color: str | None,
    type_image: str | None,
    layout: str | None,
) -> list[dict[str, str]]:
    """Execute image search synchronously via ddgs (called in thread pool)."""
    try:
        from ddgs import DDGS
    except ImportError:
        logger.error("ddgs library not installed. Install via: uv pip install ddgs")
        return []

    ddgs = DDGS(timeout=_SEARCH_TIMEOUT_SECONDS)
    kwargs: dict[str, str | int] = {
        "region": region,
        "safesearch": safesearch,
        "max_results": max_results,
    }
    if size:
        kwargs["size"] = size
    if color:
        kwargs["color"] = color
    if type_image:
        kwargs["type_image"] = type_image
    if layout:
        kwargs["layout"] = layout

    try:
        results = ddgs.images(query, **kwargs)
        if not results:
            return []
        return [
            {
                "title": r.get("title", ""),
                "image_url": r.get("image", ""),
                "thumbnail_url": r.get("thumbnail", ""),
                "source_url": r.get("url", ""),
            }
            for r in results
            if r.get("image")
        ]
    except Exception as e:
        logger.warning(f"Image search failed for '{query}': {e}")
        return []


def create_image_search_tool(
    default_max_results: int = _DEFAULT_MAX_RESULTS,
):
    """Create an image search tool.

    Args:
        default_max_results: Default maximum number of images to return per search.

    Returns:
        A LangChain tool function for image search.
    """
    _default = default_max_results
    tool_description = """Search for images online. Use this tool to find reference images, product photos, visual examples, or any image content.

## When to use
- Finding reference images for image generation tasks
- Looking up product/object/place appearance
- Searching for design inspiration, logos, or visual styles
- Any request that needs visual/image information

## Parameters
- query: Descriptive search keywords (be specific for better results, e.g. "Japanese garden zen style" instead of "garden")
- max_results: Number of images to return (1-10, default 5)
- size: Image size filter — "Small", "Medium", "Large", "Wallpaper"
- type_image: Image type — "photo", "clipart", "gif", "transparent", "line"
- layout: Layout filter — "Square", "Tall", "Wide"

## Output
Returns a list of images with title, image_url (full resolution), thumbnail_url, and source_url.
Display results using markdown image syntax: ![title](image_url)
""".strip()

    class ImageSearchInput(BaseModel):
        query: str = Field(description="Descriptive keywords for the images to search")
        max_results: int = Field(
            default=_default,
            ge=1,
            le=10,
            description="Maximum number of images to return (1-10)",
        )
        size: str | None = Field(default=None, description='Image size: "Small", "Medium", "Large", "Wallpaper"')
        type_image: str | None = Field(
            default=None, description='Image type: "photo", "clipart", "gif", "transparent", "line"'
        )
        layout: str | None = Field(default=None, description='Layout: "Square", "Tall", "Wide"')

    @tool("image_search_tool", description=tool_description, args_schema=ImageSearchInput)
    async def image_search_func(
        query: str,
        max_results: int = _DEFAULT_MAX_RESULTS,
        size: str | None = None,
        type_image: str | None = None,
        layout: str | None = None,
    ) -> str:
        """Execute image search and return structured results."""
        cache_key = f"img:{query}:{max_results}:{size}:{type_image}:{layout}"
        cached = _image_cache.get(cache_key)
        if cached is not None:
            return json.dumps(
                {"query": query, "total_results": len(cached), "results": cached},
                ensure_ascii=False,
                indent=2,
            )

        try:
            results = await asyncio.wait_for(
                asyncio.to_thread(
                    _search_images_sync,
                    query=query,
                    max_results=max_results,
                    region="wt-wt",
                    safesearch="moderate",
                    size=size,
                    color=None,
                    type_image=type_image,
                    layout=layout,
                ),
                timeout=_SEARCH_TIMEOUT_SECONDS + 5,
            )
        except TimeoutError:
            return json.dumps({"error": "Image search timed out", "query": query}, ensure_ascii=False)

        if not results:
            return json.dumps({"error": "No images found", "query": query}, ensure_ascii=False)

        _image_cache.set(cache_key, results)
        return json.dumps(
            {"query": query, "total_results": len(results), "results": results},
            ensure_ascii=False,
            indent=2,
        )

    return image_search_func
