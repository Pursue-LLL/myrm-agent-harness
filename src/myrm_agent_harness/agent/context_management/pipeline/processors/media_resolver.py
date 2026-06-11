"""Media reference resolver processor.

Resolves non-base64 image URLs (HTTP/file references) in message content
to base64 data URLs right before sending to the LLM. This allows messages
to store lightweight URL references in checkpoints and history while still
providing full image data to models that need it.

Positioned AFTER MediaFilterProcessor in the pipeline:
- MediaFilter strips historical media → fewer URLs to resolve
- MediaResolver only resolves URLs in messages that survive filtering

[INPUT]
- base::BaseProcessor, ProcessorContext (POS: processor base class)
- utils.image_utils (POS: image content detection utilities)

[OUTPUT]
- MediaResolverProcessor: resolves URL references to base64 for LLM consumption

[POS]
Media reference resolver. Converts StorageProvider URLs and local file paths
in image_url content items to base64 data URLs before LLM invocation.
"""

from __future__ import annotations

import asyncio
import base64
import mimetypes
from pathlib import Path
from typing import Protocol

from myrm_agent_harness.utils.image_utils import (
    get_image_url,
    is_base64_data_url,
    is_image_content_item,
    MAX_IMAGE_READ_BYTES,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

from ..base import BaseProcessor, ProcessorContext

logger = get_agent_logger(__name__)

_RESOLVE_TIMEOUT = 10.0
_MAX_CONCURRENT_RESOLVES = 8


class FileContentReader(Protocol):
    """Protocol for reading file content by ID (injected by business layer)."""

    async def __call__(self, file_id: str) -> bytes | None: ...


class MediaResolverProcessor(BaseProcessor):
    """Resolve non-base64 image URLs to base64 data URLs for LLM consumption.

    Handles three URL schemes:
    - HTTP(S): fetches via httpx (StorageProvider API endpoints)
    - file://: reads from local filesystem
    - Relative API paths (/api/media/...): resolved via injected reader or HTTP fallback

    Positioned after MediaFilterProcessor so only surviving images are resolved.
    No-op when all images are already base64 data URLs.
    """

    def __init__(self, file_content_reader: FileContentReader | None = None) -> None:
        self._file_reader = file_content_reader

    @property
    def name(self) -> str:
        return "media_resolver"

    async def should_process(self, context: ProcessorContext) -> bool:
        return True

    async def process(self, context: ProcessorContext) -> ProcessorContext:
        resolve_tasks: list[tuple[int, int, str]] = []

        for msg_idx, msg in enumerate(context.messages):
            content = getattr(msg, "content", None)
            if not isinstance(content, list):
                continue

            for item_idx, item in enumerate(content):
                if not is_image_content_item(item):
                    continue

                url = get_image_url(item)  # type: ignore[arg-type]
                if not url or is_base64_data_url(url):
                    continue

                resolve_tasks.append((msg_idx, item_idx, url))

        if not resolve_tasks:
            return context

        sem = asyncio.Semaphore(_MAX_CONCURRENT_RESOLVES)
        results = await asyncio.gather(
            *[self._resolve_with_semaphore(sem, url) for _, _, url in resolve_tasks],
            return_exceptions=True,
        )

        resolved_count = 0
        for (msg_idx, item_idx, original_url), result in zip(resolve_tasks, results):
            if isinstance(result, Exception):
                logger.warning("[MediaResolver] Failed to resolve %s: %s", original_url[:80], result)
                continue
            if result is None:
                continue

            content = context.messages[msg_idx].content
            if isinstance(content, list) and item_idx < len(content):
                item = content[item_idx]
                if isinstance(item, dict) and isinstance(item.get("image_url"), dict):
                    item["image_url"]["url"] = result
                    resolved_count += 1

        if resolved_count > 0:
            logger.info(
                "[MediaResolver] Resolved %d/%d image reference(s) to base64",
                resolved_count,
                len(resolve_tasks),
            )

        return context

    async def _resolve_with_semaphore(self, sem: asyncio.Semaphore, url: str) -> str | None:
        async with sem:
            return await self._resolve_url(url)

    async def _resolve_url(self, url: str) -> str | None:
        """Resolve a URL to a base64 data URL."""
        if url.startswith("file://"):
            return _resolve_local_file(url[7:])

        if url.startswith("/api/media/files/"):
            return await self._resolve_api_file(url)

        if url.startswith("/"):
            return await _resolve_http(f"http://127.0.0.1:8000{url}")

        if url.startswith(("http://", "https://")):
            return await _resolve_http(url)

        return _resolve_local_file(url)

    async def _resolve_api_file(self, path: str) -> str | None:
        """Resolve /api/media/files/{file_id}/content via injected reader or HTTP."""
        import re

        match = re.match(r"/api/media/files/([^/]+)/content", path)
        if not match:
            return await _resolve_http(f"http://127.0.0.1:8000{path}")

        file_id = match.group(1)
        if self._file_reader:
            try:
                data = await self._file_reader(file_id)
                if data:
                    return _bytes_to_data_url(data, file_id)
            except Exception as exc:
                logger.debug("[MediaResolver] File reader failed for %s, falling back to HTTP: %s", file_id, exc)

        return await _resolve_http(f"http://127.0.0.1:8000{path}")


def _resolve_local_file(path_str: str) -> str | None:
    """Read a local file and convert to base64 data URL."""
    try:
        p = Path(path_str)
        if not p.is_file():
            return None
        size = p.stat().st_size
        if size > MAX_IMAGE_READ_BYTES:
            logger.warning("[MediaResolver] Local file too large (%d bytes): %s", size, path_str)
            return None
        data = p.read_bytes()
        return _bytes_to_data_url(data, path_str)
    except Exception as exc:
        logger.warning("[MediaResolver] Local file read failed for %s: %s", path_str, exc)
        return None


async def _resolve_http(url: str) -> str | None:
    """Fetch an HTTP URL and convert to base64 data URL."""
    try:
        import httpx

        async with httpx.AsyncClient(timeout=_RESOLVE_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.content

            if len(data) > MAX_IMAGE_READ_BYTES:
                logger.warning("[MediaResolver] HTTP response too large (%d bytes): %s", len(data), url[:80])
                return None

            content_type = resp.headers.get("content-type", "")
            mime = content_type.split(";")[0].strip() if content_type else ""
            if not mime or not mime.startswith("image/"):
                mime = _detect_mime(data)

            b64 = base64.b64encode(data).decode("ascii")
            return f"data:{mime};base64,{b64}"
    except Exception as exc:
        logger.warning("[MediaResolver] HTTP fetch failed for %s: %s", url[:80], exc)
        return None


def _bytes_to_data_url(data: bytes, hint: str = "") -> str:
    """Convert raw bytes to a base64 data URL with MIME detection."""
    mime = _detect_mime(data, hint)
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _detect_mime(data: bytes, hint: str = "") -> str:
    """Detect image MIME type from data or filename hint."""
    if hint:
        guessed, _ = mimetypes.guess_type(hint)
        if guessed and guessed.startswith("image/"):
            return guessed

    try:
        from myrm_agent_harness.utils.mime_types import detect_image_mime

        return detect_image_mime(data, fallback="image/png")
    except ImportError:
        return "image/png"
