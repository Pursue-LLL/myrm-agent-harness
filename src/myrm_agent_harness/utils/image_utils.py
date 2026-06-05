"""Media content utilities for context management.

Provides helpers to detect, estimate token cost, and strip base64 images,
video, and audio from LLM message content, preventing context window overflow
and 400 errors from text-only models.

[INPUT]

[OUTPUT]
- is_base64_data_url(): Detect base64 data URLs
- is_image_content_item(): Detect image content items (image_url / image / input_image)
- is_media_content_item(): Detect any media content item (image / video / audio)
- estimate_image_tokens_in_content(): Estimate total image token overhead
- strip_images_from_content(): Replace images with text placeholders (all 3 formats)
- strip_all_media_from_content(): Replace all media (image/video/audio) with placeholders
- content_has_images(): Check if content contains any image items
- content_has_media(): Check if content contains any media items

[POS]
Central media processing utilities. Used by context_management (token estimation),
chat_utils (history image degradation), and MediaFilterProcessor (proactive filtering)
to prevent context overflow and multimodal rejection errors.
"""

from __future__ import annotations

MAX_IMAGE_READ_BYTES = 50 * 1024 * 1024  # 50MB — max allowed file size to read into memory
MAX_IMAGE_PAYLOAD_BYTES = 20 * 1024 * 1024  # 20MB — max payload size sent to LLM API
IMAGE_TOKEN_ESTIMATE = 765  # OpenAI detail=high 2x2 tiles: 85 + 170*4
BASE64_DATA_URL_PREFIX = "data:image/"


def is_base64_data_url(url: str) -> bool:
    """Check if a URL is a base64-encoded data URL for an image."""
    return isinstance(url, str) and url.startswith(BASE64_DATA_URL_PREFIX) and ";base64," in url


_IMAGE_CONTENT_TYPES = frozenset({"image_url", "image", "input_image"})


def is_image_content_item(item: object) -> bool:
    """Check if a content item is an image type (image_url, image, or input_image)."""
    return isinstance(item, dict) and item.get("type") in _IMAGE_CONTENT_TYPES


def get_image_url(item: dict[str, object]) -> str:
    """Extract the URL string from an image_url content item."""
    image_url = item.get("image_url")
    if isinstance(image_url, dict):
        url = image_url.get("url", "")
        return str(url) if url else ""
    return ""


def estimate_base64_byte_size(url: str) -> int:
    """Estimate the decoded byte size of a base64 data URL without full decoding."""
    if not is_base64_data_url(url):
        return 0
    try:
        b64_part = url.split(";base64,", 1)[1]
        padding = b64_part.count("=")
        return (len(b64_part) * 3) // 4 - padding
    except (IndexError, ValueError):
        return 0


def estimate_image_tokens_in_content(content: str | list[object]) -> int:
    """Estimate the total image token overhead in a message's content.

    For each image item, returns IMAGE_TOKEN_ESTIMATE instead of
    serializing the base64 data as text tokens.
    """
    if isinstance(content, str):
        return 0

    total = 0
    for item in content:
        if is_image_content_item(item):
            total += IMAGE_TOKEN_ESTIMATE
    return total


_PLACEHOLDER_COMPRESSED = "[Image removed during context compression]"


def strip_images_from_content(
    content: str | list[object],
) -> str | list[object]:
    """Replace image content items with lightweight text placeholders.

    Supports all image content formats:
    - ``image_url``: OpenAI format with nested ``image_url.url``
    - ``image``: LangChain ``create_image_block()`` with inline ``base64``
    - ``input_image``: Anthropic format with ``source.data``

    Used to degrade historical images in older conversation turns,
    preserving context window space for actual dialogue.
    DB data is NOT modified — this operates on in-memory copies only.
    """
    if isinstance(content, str):
        return content

    result: list[object] = []
    for item in content:
        if not (isinstance(item, dict) and is_image_content_item(item)):
            result.append(item)
            continue

        item_type = item.get("type")
        if item_type == "image_url":
            url = get_image_url(item)
            if is_base64_data_url(url):
                result.append({"type": "text", "text": _PLACEHOLDER_COMPRESSED})
            elif url:
                truncated = url[:80] + "..." if len(url) > 80 else url
                result.append({"type": "text", "text": f"[Image: {truncated}]"})
            else:
                result.append({"type": "text", "text": _PLACEHOLDER_COMPRESSED})
        else:
            result.append({"type": "text", "text": _PLACEHOLDER_COMPRESSED})
    return result


def content_has_images(content: str | list[object]) -> bool:
    """Check if message content contains any image items."""
    if isinstance(content, str):
        return False
    return any(is_image_content_item(item) for item in content)


# ============================================================================
# Extended media support (video / audio)
# ============================================================================

_VIDEO_CONTENT_TYPES = frozenset({"video_url", "video", "input_video"})
_AUDIO_CONTENT_TYPES = frozenset({"audio_url", "audio", "input_audio"})
_ALL_MEDIA_CONTENT_TYPES = _IMAGE_CONTENT_TYPES | _VIDEO_CONTENT_TYPES | _AUDIO_CONTENT_TYPES


def is_media_content_item(item: object) -> bool:
    """Check if a content item is any media type (image / video / audio)."""
    return isinstance(item, dict) and item.get("type") in _ALL_MEDIA_CONTENT_TYPES


def content_has_media(content: str | list[object]) -> bool:
    """Check if message content contains any media items (image / video / audio)."""
    if isinstance(content, str):
        return False
    return any(is_media_content_item(item) for item in content)


_PLACEHOLDER_MEDIA_STRIPPED = "[Media removed — model does not support multimodal input]"


def strip_all_media_from_content(
    content: str | list[object],
) -> str | list[object]:
    """Replace all media content items (image/video/audio) with text placeholders.

    Superset of ``strip_images_from_content`` — also handles video and audio.
    Used by MediaFilterProcessor for proactive stripping before LLM calls.
    """
    if isinstance(content, str):
        return content

    result: list[object] = []
    changed = False
    for item in content:
        if isinstance(item, dict) and item.get("type") in _ALL_MEDIA_CONTENT_TYPES:
            result.append({"type": "text", "text": _PLACEHOLDER_MEDIA_STRIPPED})
            changed = True
        else:
            result.append(item)

    return result if changed else content
