"""Provider image-limit recovery: measure, shrink, and evict oversized base64 images.

Split out of the one-shot recovery mixin because the image machinery is pure message
surgery with no dependency on the executor: it only needs the provider's stated
ceiling and the messages to rewrite.

[INPUT]
- utils.media.image_compressor::ImageCompressor, SEND_COMPRESS_TRIGGER_BYTES (POS: 压缩器与 base64 字节阈值)
- utils.image_utils::estimate_base64_byte_size, is_base64_data_url (POS: base64 体积与格式判定)
- toolkits.llms.errors.classifier::normalize_provider_error (POS: provider 错误归一化)

[OUTPUT]
- parse_image_max_dimension(): provider 声明的单边像素上限（缺省 8000）
- shrink_oversized_images(): 逐张压缩超限图片，无单张超限时退化为历史图片聚合淘汰
- evict_aggregate_historical_images(): 历史图片降采样或语义占位，保护最新轮次

[POS]
Image payload recovery primitives shared by the streaming one-shot handlers. Rewrites
message content in place and reports how many images changed so the caller can decide
whether a retry can succeed; it never retries by itself.
"""

from __future__ import annotations

import base64
import io
import re
from typing import TYPE_CHECKING

from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.media.image_compressor import SEND_COMPRESS_TRIGGER_BYTES

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage

logger = get_agent_logger(__name__)

_IMAGE_MAX_DIM_RE = re.compile(
    r"(?:maximum|max).*?(?:allowed\s+)?size.*?(\d{3,5})"
    r"|(\d{3,5})\s*(?:px|pixels?)?\s*(?:per[- ]?side|limit|maximum|cap)",
    re.IGNORECASE,
)

DEFAULT_MAX_DIMENSION = 8000
_AGGREGATE_THUMBNAIL_DIMENSION = 512
_LEGACY_MAX_DIM_BOUNDS = (64, 32768)


def parse_image_max_dimension(exc: Exception) -> int:
    """Extract the provider-reported dimension ceiling from an error message.

    Anthropic reports e.g. "maximum allowed size of 2000" or
    "exceeds the maximum of 8000px per side".  Returns the parsed
    integer or ``DEFAULT_MAX_DIMENSION`` when not parseable.
    """
    from myrm_agent_harness.toolkits.llms.errors.classifier import (
        normalize_provider_error,
    )

    msg = normalize_provider_error(exc).message
    match = _IMAGE_MAX_DIM_RE.search(msg)
    if match:
        value = int(match.group(1) or match.group(2))
        low, high = _LEGACY_MAX_DIM_BOUNDS
        if low <= value <= high:
            return value
    return DEFAULT_MAX_DIMENSION


def shrink_oversized_images(
    messages: list[BaseMessage],
    *,
    max_dimension: int = DEFAULT_MAX_DIMENSION,
    enable_aggregate_fallback: bool = True,
) -> int:
    """Walk messages and shrink base64 images exceeding byte/dimension limits.

    Checks **both** byte size (against ``SEND_COMPRESS_TRIGGER_BYTES``, base64
    space) and pixel dimensions (against ``max_dimension``).  Uses a
    ``triggered_by`` mechanism to validate the correct constraint after resize —
    a pixel-correct downscale is accepted even if its bytes grew (PNG
    re-encode can increase bytes).

    If no single image exceeds the individual thresholds (e.g. multiple legal
    ~2MB images whose sum exceeds an external proxy gateway's body limit),
    automatically activates Tier 2 aggregate eviction: degrades older historical
    images to 512px WebP thumbnails or semantic text placeholders, preserving
    the latest focus round.

    Returns the number of images actually replaced.  Returns 0 if any image
    was oversized but could not be shrunk (unshrinkable), because retrying
    would re-send the same rejected payload.
    """
    from myrm_agent_harness.utils.image_utils import (
        estimate_base64_byte_size,
        is_base64_data_url,
    )
    from myrm_agent_harness.utils.media.image_compressor import ImageCompressor

    shrunk_count = 0
    unshrinkable_count = 0
    compressor = ImageCompressor()

    for msg in messages:
        content = getattr(msg, "content", None)
        if not isinstance(content, list):
            continue
        for idx, part in enumerate(content):
            if not isinstance(part, dict) or part.get("type") != "image_url":
                continue
            image_url = part.get("image_url")
            if not isinstance(image_url, dict):
                continue
            url = image_url.get("url", "")
            if not isinstance(url, str) or not is_base64_data_url(url):
                continue

            b64_data = url.split(";base64,", 1)[1]
            # Base64-space byte check: provider per-image ceilings are base64
            # sizes, so a raw-byte comparison (estimate_base64_byte_size)
            # would miss 3-4 MiB raw images whose base64 form (4-5.3 MiB)
            # still exceeds a 5 MiB ceiling.
            over_bytes = len(b64_data) > SEND_COMPRESS_TRIGGER_BYTES
            original_size = estimate_base64_byte_size(url)

            dims = _decode_image_dimensions(url)
            over_pixels = dims is not None and max(dims) > max_dimension

            if not over_bytes and not over_pixels:
                continue

            triggered_by = "bytes" if over_bytes else "dimension"

            try:
                header = url.split(";base64,", 1)[0]
                raw_bytes = base64.b64decode(b64_data)
                compressed = compressor.compress(
                    io.BytesIO(raw_bytes),
                    quality=0.5,
                    max_dimension=max_dimension,
                )
                if compressed is None:
                    unshrinkable_count += 1
                    continue

                if triggered_by == "bytes" and len(compressed) >= original_size:
                    unshrinkable_count += 1
                    continue

                new_dims = _decode_bytes_dimensions(compressed)
                if new_dims is not None and max(new_dims) > max_dimension:
                    unshrinkable_count += 1
                    continue

                new_b64 = base64.b64encode(compressed).decode("ascii")
                image_url["url"] = f"{header};base64,{new_b64}"
                shrunk_count += 1
            except Exception as shrink_err:
                logger.warning("Image shrink failed for part %d: %s", idx, shrink_err)
                unshrinkable_count += 1

    if unshrinkable_count > 0:
        logger.warning(
            "Image shrink: %d part(s) could not be shrunk — not retrying",
            unshrinkable_count,
        )
        return 0

    # Tier 2 Aggregate Fallback: If no single image was oversized individually
    # but the provider/gateway rejected the request with IMAGE_TOO_LARGE or 413,
    # perform aggregate progressive downsampling on older historical images.
    # Protects the latest message (Focus Window) by requiring multiple turns (len > 1).
    if enable_aggregate_fallback and shrunk_count == 0 and len(messages) > 1:
        shrunk_count = evict_aggregate_historical_images(messages)

    return shrunk_count


def evict_aggregate_historical_images(messages: list[BaseMessage]) -> int:
    """Progressively compress or placeholder older images when aggregate payload overflows.

    Protects the latest message (Focus Window) and downsamples historical base64
    images to 512px WebP (quality 0.5) to clear gateway payload restrictions.
    """
    from myrm_agent_harness.utils.image_utils import (
        estimate_base64_byte_size,
        is_base64_data_url,
    )
    from myrm_agent_harness.utils.media.image_compressor import ImageCompressor

    compressor = ImageCompressor()
    evicted_count = 0

    # Protect the latest message turn (last message in sequence)
    target_messages = messages[:-1]

    for msg in target_messages:
        content = getattr(msg, "content", None)
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "image_url":
                continue
            image_url = part.get("image_url")
            if not isinstance(image_url, dict):
                continue
            url = image_url.get("url", "")
            if not isinstance(url, str) or not is_base64_data_url(url):
                continue

            try:
                b64_data = url.split(";base64,", 1)[1]
                raw_bytes = base64.b64decode(b64_data)
                original_size = estimate_base64_byte_size(url)

                compressed = compressor.compress(
                    io.BytesIO(raw_bytes),
                    quality=0.5,
                    max_dimension=_AGGREGATE_THUMBNAIL_DIMENSION,
                )
                if compressed and len(compressed) < original_size:
                    new_b64 = base64.b64encode(compressed).decode("ascii")
                    image_url["url"] = f"data:image/webp;base64,{new_b64}"
                    evicted_count += 1
                else:
                    # If compression yields no gain, replace with semantic placeholder
                    part.clear()
                    part.update(
                        {
                            "type": "text",
                            "text": f"[Historical image omitted to reduce aggregate payload: {original_size // 1024}KB]",
                        }
                    )
                    evicted_count += 1
            except Exception as evict_err:
                logger.warning("[_evict_aggregate] Fallback eviction failed: %s", evict_err)

    if evicted_count > 0:
        logger.info(
            "[_evict_aggregate] Successfully compressed/evicted %d historical image(s) for aggregate recovery",
            evicted_count,
        )

    return evicted_count


def _decode_image_dimensions(data_url: str) -> tuple[int, int] | None:
    """Decode pixel dimensions (width, height) from a base64 data URL."""
    try:
        from PIL import Image

        _, b64_data = data_url.split(";base64,", 1)
        with Image.open(io.BytesIO(base64.b64decode(b64_data))) as img:
            return img.size
    except Exception:
        return None


def _decode_bytes_dimensions(raw_bytes: bytes) -> tuple[int, int] | None:
    """Decode pixel dimensions (width, height) from raw image bytes."""
    try:
        from PIL import Image

        with Image.open(io.BytesIO(raw_bytes)) as img:
            return img.size
    except Exception:
        return None
