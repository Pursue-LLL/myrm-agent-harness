"""Framework-agnostic image payload emergency eviction.

[INPUT]
- utils.image_utils::is_base64_data_url, estimate_base64_byte_size (POS: Base64 data URL helpers.)

[OUTPUT]
- emergency_evict_from_message_dicts: Downsample/evict images in raw dict messages.
- emergency_evict: Unified eviction for BaseMessage instances and raw dicts.

[POS]
Pure message-payload image eviction for in-flight 400/413 recovery. Framework
layer: usable by any agent runtime without importing agent/ session machinery.
The agent-side CumulativeImageBudgetGovernor delegates to these functions.
"""

from __future__ import annotations

from typing import Final

from myrm_agent_harness.utils.image_utils import (
    estimate_base64_byte_size,
    is_base64_data_url,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.media.base64_downsampler import (
    DEFAULT_DOWNSAMPLE_MAX_DIM as _DOWNSAMPLE_MAX_DIM,
    DEFAULT_DOWNSAMPLE_QUALITY as _DOWNSAMPLE_QUALITY,
    downsample_base64_image as _downsample_base64_image,
)

logger = get_agent_logger(__name__)

_TINY_ICON_BYTES: Final[int] = 2 * 1024




def _extract_image_url(part: dict[str, object]) -> str:
    """Extract a base64-capable URL from an OpenAI- or Anthropic-shaped image part."""
    image_url = part.get("image_url")
    if part.get("type") == "image_url" and isinstance(image_url, dict):
        url = image_url.get("url", "")
        return url if isinstance(url, str) else ""
    source = part.get("source")
    if part.get("type") == "image" and isinstance(source, dict):
        data = source.get("data", "")
        media_type = source.get("media_type", "image/png")
        if isinstance(data, str) and isinstance(media_type, str):
            return f"data:{media_type};base64,{data}"
    return ""


def _replace_image_part(part: dict[str, object], downsampled_url: str) -> bool:
    """Swap an image part's payload for the downsampled URL. Returns True when swapped."""
    image_url = part.get("image_url")
    if part.get("type") == "image_url" and isinstance(image_url, dict):
        image_url["url"] = downsampled_url
        return True
    source = part.get("source")
    if part.get("type") == "image" and isinstance(source, dict):
        _, b64 = downsampled_url.split(";base64,", 1)
        source["data"] = b64
        source["media_type"] = "image/webp"
        return True
    return False


def emergency_evict_from_message_dicts(
    message_dicts: list[dict[str, object]],
    target_bytes: int = 5 * 1024 * 1024,
    force_shrink: bool = False,
) -> int:
    """Synchronously downsample or evict images in raw dict messages.

    Designed for in-flight 400/413 Payload Too Large recovery in adapter mixins.
    Operates in two progressive stages:
      - Stage 1: Downsample base64 images to compact 512px WebP format,
        preserving visual content so multimodal perception continues to work.
      - Stage 2: If payload still exceeds target_bytes, evict historical images
        from oldest to newest into text placeholders, protecting the latest turn.

    Returns the number of images modified (downsampled or textified).
    """
    modified_count = 0
    total_bytes = 0
    image_entries: list[tuple[int, int, dict[str, object], int, str]] = []

    for m_idx, msg in enumerate(message_dicts):
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for c_idx, part in enumerate(content):
            if not isinstance(part, dict):
                continue
            url = _extract_image_url(part)

            if is_base64_data_url(url):
                size = estimate_base64_byte_size(url)
                total_bytes += size
                image_entries.append((m_idx, c_idx, part, size, url))

    if not image_entries or (not force_shrink and total_bytes <= target_bytes):
        return 0

    effective_target = target_bytes
    if force_shrink and total_bytes <= target_bytes:
        effective_target = max(512, total_bytes // 2)

    # Stage 1: Downsample all large images to compact WebP first (preserve visual reasoning)
    for idx, (m_idx, c_idx, part, size, url) in enumerate(image_entries):
        if total_bytes <= effective_target:
            break
        if size <= _TINY_ICON_BYTES:  # Tiny icon, skipping downsample
            continue

        downsampled_url = _downsample_base64_image(url, max_dim=512, quality=0.65)
        if downsampled_url and downsampled_url != url:
            new_size = estimate_base64_byte_size(downsampled_url)
            saved = size - new_size
            if saved > 0 and _replace_image_part(part, downsampled_url):
                total_bytes -= saved
                image_entries[idx] = (m_idx, c_idx, part, new_size, downsampled_url)
                modified_count += 1

    # Stage 2: If still over budget, convert historical images from oldest to newest into text
    if total_bytes > effective_target:
        last_m_idx = max(m_idx for m_idx, _, _, _, _ in image_entries)
        candidates = [e for e in image_entries if e[0] < last_m_idx]
        if not candidates:
            candidates = image_entries[:-1] if len(image_entries) > 1 else image_entries

        for m_idx, c_idx, _part, size, _ in candidates:
            if total_bytes <= effective_target:
                break

            msg_content = message_dicts[m_idx]["content"]
            if isinstance(msg_content, list):
                msg_content[c_idx] = {
                    "type": "text",
                    "text": f"[Historical Image omitted: payload reduced {size // 1024}KB to recover from gateway limit]",
                }
                total_bytes -= size
                modified_count += 1

    if modified_count > 0:
        logger.warning(
            "[ImagePayloadEvictor] Emergency recovered %d images, reduced payload to %d bytes",
            modified_count,
            total_bytes,
        )

    return modified_count


def _emergency_evict_indexed(
    messages: list[object],
    target_bytes: int = 5 * 1024 * 1024,
    force_shrink: bool = False,
) -> int:
    """Eviction over the original list preserving element indices.

    Accepts BaseMessage instances and raw dicts (mixed lists tolerated: foreign
    elements are skipped instead of crashing stage 2 indexing).
    """
    modified_count = 0
    total_bytes = 0
    image_entries: list[tuple[int, int, dict[str, object], int, str]] = []

    for m_idx, msg in enumerate(messages):
        content = getattr(msg, "content", None)
        if not isinstance(content, list):
            continue
        for c_idx, part in enumerate(content):
            if not isinstance(part, dict):
                continue
            url = _extract_image_url(part)

            if is_base64_data_url(url):
                size = estimate_base64_byte_size(url)
                total_bytes += size
                image_entries.append((m_idx, c_idx, part, size, url))

    if not image_entries or (not force_shrink and total_bytes <= target_bytes):
        return 0

    effective_target = target_bytes
    if force_shrink and total_bytes <= target_bytes:
        effective_target = max(512, total_bytes // 2)

    # Stage 1: Downsample all large images to compact WebP first
    for idx, (m_idx, c_idx, part, size, url) in enumerate(image_entries):
        if total_bytes <= effective_target:
            break
        if size <= _TINY_ICON_BYTES:
            continue

        downsampled_url = _downsample_base64_image(url, max_dim=512, quality=0.65)
        if downsampled_url and downsampled_url != url:
            new_size = estimate_base64_byte_size(downsampled_url)
            saved = size - new_size
            if saved > 0 and _replace_image_part(part, downsampled_url):
                total_bytes -= saved
                image_entries[idx] = (m_idx, c_idx, part, new_size, downsampled_url)
                modified_count += 1

    # Stage 2: Convert historical to text
    if total_bytes > effective_target:
        last_m_idx = max(m_idx for m_idx, _, _, _, _ in image_entries)
        candidates = [e for e in image_entries if e[0] < last_m_idx]
        if not candidates:
            candidates = image_entries[:-1] if len(image_entries) > 1 else image_entries

        for m_idx, c_idx, _part, size, _ in candidates:
            if total_bytes <= effective_target:
                break

            holder = messages[m_idx]
            msg_content = holder["content"] if isinstance(holder, dict) else getattr(holder, "content", None)
            if isinstance(msg_content, list) and c_idx < len(msg_content):
                msg_content[c_idx] = {
                    "type": "text",
                    "text": f"[Historical Image omitted: payload reduced {size // 1024}KB to recover from gateway limit]",
                }
                total_bytes -= size
                modified_count += 1

    if modified_count > 0:
        logger.warning(
            "[ImagePayloadEvictor] Emergency recovered %d images in BaseMessages, reduced payload to %d bytes",
            modified_count,
            total_bytes,
        )

    return modified_count


def emergency_evict(
    messages: list[object],
    target_bytes: int = 5 * 1024 * 1024,
    force_shrink: bool = False,
) -> int:
    """Unified emergency eviction supporting both BaseMessage instances and raw dicts."""
    if not messages:
        return 0
    if isinstance(messages[0], dict):
        # Fast path: homogeneous dict lists keep exact legacy behavior.
        dict_messages = [msg for msg in messages if isinstance(msg, dict)]
        if len(dict_messages) == len(messages):
            return emergency_evict_from_message_dicts(
                dict_messages, target_bytes=target_bytes, force_shrink=force_shrink
            )
    return _emergency_evict_indexed(messages, target_bytes=target_bytes, force_shrink=force_shrink)
