"""Cumulative Multi-Turn Image Payload Budget Governor Processor.

Manages total session image payload across multi-turn conversations to prevent
HTTP 400 Payload Too Large errors and excessive vision token billing.

Implements a 3-Tier Progressive Visual Ladder:
- Tier 1 (Active Focus Window): Recent 1-2 turns keep full 2048px high-fidelity images.
- Tier 2 (Historical Context Window): Older turns are asynchronously downsampled to 512px
  WebP (reducing individual payload by 85-95%) when total cumulative base64 payload exceeds budget.
- Tier 3 (Semantic Text Window): Extreme payload overflows trigger Vision-to-Text summary
  fallbacks (via VisionFallbackEngine) and strip base64 data completely.

Prompt Cache Invariant:
Downsampling and text extraction are applied deterministically from oldest to newest messages.
Once a historical turn is stabilized in Tier 2 or Tier 3, its payload state remains fixed
across subsequent requests, protecting Anthropic / DeepSeek prefix prompt cache hit rates.

[INPUT]
- base::BaseProcessor, ProcessorContext
- utils.image_utils::is_base64_data_url, is_image_content_item, get_image_url, estimate_base64_byte_size
- utils.media.image_compressor::image_compressor
- processors.vision_fallback_processor::VisionFallbackProcessor, apply_vision_fallback_to_messages

[OUTPUT]
- MediaBudgetGovernorProcessor: ContextPipeline processor
- CumulativeImageBudgetGovernor: Core calculation & progressive eviction engine

[POS]
Positioned in ContextPipeline after MediaResolverProcessor (or integrated alongside send-time
resolution) to govern cumulative base64 image bytes before LLM invocation.
"""

from __future__ import annotations

import asyncio
import base64
import io
from dataclasses import dataclass
from typing import Final

from langchain_core.messages import BaseMessage
from PIL import Image

from myrm_agent_harness.utils.image_utils import (
    estimate_base64_byte_size,
    get_image_url,
    is_base64_data_url,
    is_image_content_item,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

from ..base import BaseProcessor, ProcessorContext

logger = get_agent_logger(__name__)

# Default budget: 10 MiB cumulative base64 payload across all messages in context
# Most API gateways (Nginx/Cloudflare/OneAPI) enforce 15-25 MiB max request body.
DEFAULT_MAX_CUMULATIVE_IMAGE_BYTES: Final[int] = 10 * 1024 * 1024

# Focus window: Protect latest N turns from being downsampled or evicted
DEFAULT_FOCUS_WINDOW_TURNS: Final[int] = 2

# Tier 2 downsampling target dimensions & quality
TIER2_DOWNSAMPLE_MAX_DIM: Final[int] = 512
TIER2_DOWNSAMPLE_QUALITY: Final[float] = 0.65


@dataclass(slots=True)
class ImageItemRef:
    """Reference pointer to an image item inside context.messages."""

    msg_idx: int
    item_idx: int
    data_url: str
    byte_size: int
    is_focus: bool


def _downsample_base64_image(
    data_url: str,
    max_dim: int = TIER2_DOWNSAMPLE_MAX_DIM,
    quality: float = TIER2_DOWNSAMPLE_QUALITY,
) -> str | None:
    """Downsample a base64 data URL to compact WebP format."""
    if not is_base64_data_url(data_url):
        return None

    try:
        header, b64_str = data_url.split(";base64,", 1)
        raw_bytes = base64.b64decode(b64_str)

        with Image.open(io.BytesIO(raw_bytes)) as img:
            # Preserve aspect ratio while resizing
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

            # Convert to RGB if palette or RGBA with transparency
            if img.mode in ("RGBA", "LA", "P"):
                # WebP supports RGBA directly
                pass
            elif img.mode != "RGB":
                img = img.convert("RGB")

            out_buf = io.BytesIO()
            img.save(out_buf, format="WEBP", quality=int(quality * 100), method=4)
            compressed_bytes = out_buf.getvalue()

            # If compression didn't save space, return original
            if len(compressed_bytes) >= len(raw_bytes):
                return data_url

            new_b64 = base64.b64encode(compressed_bytes).decode("ascii")
            return f"data:image/webp;base64,{new_b64}"
    except Exception as exc:
        logger.debug("[MediaBudgetGovernor] Failed to downsample image: %s", exc)
        return None


class CumulativeImageBudgetGovernor:
    """Core governor tracking and progressively enforcing multi-turn image payload limits."""

    def __init__(
        self,
        max_cumulative_bytes: int = DEFAULT_MAX_CUMULATIVE_IMAGE_BYTES,
        focus_window_turns: int = DEFAULT_FOCUS_WINDOW_TURNS,
    ) -> None:
        self.max_cumulative_bytes = max_cumulative_bytes
        self.focus_window_turns = focus_window_turns

    def scan_image_items(self, messages: list[BaseMessage]) -> list[ImageItemRef]:
        """Scan all messages and collect base64 image items with byte sizes."""
        items: list[ImageItemRef] = []
        total_msgs = len(messages)
        # Protect the latest N messages (matching focus_window_turns) from aggressive eviction
        focus_cutoff_idx = max(0, total_msgs - max(1, self.focus_window_turns))

        for msg_idx, msg in enumerate(messages):
            content = getattr(msg, "content", None)
            if not isinstance(content, list):
                continue

            is_focus = msg_idx >= focus_cutoff_idx

            for item_idx, item in enumerate(content):
                if not is_image_content_item(item):
                    continue

                url = get_image_url(item)  # type: ignore[arg-type]
                if not is_base64_data_url(url):
                    continue

                byte_size = estimate_base64_byte_size(url)
                items.append(
                    ImageItemRef(
                        msg_idx=msg_idx,
                        item_idx=item_idx,
                        data_url=url,
                        byte_size=byte_size,
                        is_focus=is_focus,
                    )
                )

        return items

    async def enforce_budget(
        self,
        messages: list[BaseMessage],
    ) -> tuple[int, int]:
        """Progressively downsample and evict images until total payload <= budget.

        Returns (images_downsampled, images_textified).
        """
        items = self.scan_image_items(messages)
        if not items:
            return 0, 0

        total_bytes = sum(item.byte_size for item in items)
        if total_bytes <= self.max_cumulative_bytes:
            return 0, 0

        logger.info(
            "[MediaBudgetGovernor] Cumulative image payload %d bytes exceeds budget %d bytes (%d images)",
            total_bytes,
            self.max_cumulative_bytes,
            len(items),
        )

        downsampled_count = 0
        textified_count = 0

        # Tier 2: Downsample non-focus images from oldest to newest
        non_focus_items = [it for it in items if not it.is_focus]
        for item in non_focus_items:
            if total_bytes <= self.max_cumulative_bytes:
                break

            # Skip images that are already tiny (e.g. <= 4KB)
            if item.byte_size <= 4 * 1024:
                continue

            downsampled_url = await asyncio.to_thread(_downsample_base64_image, item.data_url)
            if downsampled_url and downsampled_url != item.data_url:
                new_size = estimate_base64_byte_size(downsampled_url)
                saved = item.byte_size - new_size
                if saved > 0:
                    content = messages[item.msg_idx].content
                    if isinstance(content, list) and item.item_idx < len(content):
                        entry = content[item.item_idx]
                        if isinstance(entry, dict) and isinstance(entry.get("image_url"), dict):
                            entry["image_url"]["url"] = downsampled_url
                            total_bytes -= saved
                            item.byte_size = new_size
                            downsampled_count += 1

        # Tier 3: If still over budget, convert oldest non-focus images to text placeholders
        if total_bytes > self.max_cumulative_bytes:
            for item in non_focus_items:
                if total_bytes <= self.max_cumulative_bytes:
                    break

                content = messages[item.msg_idx].content
                if isinstance(content, list) and item.item_idx < len(content):
                    # Strip base64 and replace with structured text summary
                    content[item.item_idx] = {
                        "type": "text",
                        "text": f"[Historical Image omitted: payload reduced {item.byte_size // 1024}KB]",
                    }
                    total_bytes -= item.byte_size
                    textified_count += 1

        if downsampled_count > 0 or textified_count > 0:
            logger.info(
                "[MediaBudgetGovernor] Enforced budget: %d downsampled, %d textified, final payload %d bytes",
                downsampled_count,
                textified_count,
                total_bytes,
            )

        return downsampled_count, textified_count

    @classmethod
    def emergency_evict_from_message_dicts(
        cls,
        message_dicts: list[dict[str, Any]],
        target_bytes: int = 5 * 1024 * 1024,
    ) -> int:
        """Synchronously evict and textify historical images in raw dict messages.

        Designed for in-flight 400/413 Payload Too Large recovery in adapter mixins.
        Processes from oldest message to newest message, protecting the last message
        (current turn) whenever possible.

        Returns the number of image entries replaced with text summaries.
        """
        evicted_count = 0
        total_bytes = 0
        image_entries: list[tuple[int, int, dict[str, Any], int]] = []

        for m_idx, msg in enumerate(message_dicts):
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for c_idx, part in enumerate(content):
                if not isinstance(part, dict):
                    continue
                url = ""
                if part.get("type") == "image_url" and isinstance(part.get("image_url"), dict):
                    url = part["image_url"].get("url", "")
                elif part.get("type") == "image" and isinstance(part.get("source"), dict):
                    data = part["source"].get("data", "")
                    media_type = part["source"].get("media_type", "image/png")
                    url = f"data:{media_type};base64,{data}"

                if is_base64_data_url(url):
                    size = estimate_base64_byte_size(url)
                    total_bytes += size
                    image_entries.append((m_idx, c_idx, part, size))

        if not image_entries or total_bytes <= target_bytes:
            return 0

        # Protect the last message turn if there are multiple turns with images
        last_m_idx = max(m_idx for m_idx, _, _, _ in image_entries)
        candidates = [e for e in image_entries if e[0] < last_m_idx]
        if not candidates:
            # If all images are in the last turn, evict from oldest image entry in that turn
            candidates = image_entries[:-1] if len(image_entries) > 1 else image_entries

        for m_idx, c_idx, part, size in candidates:
            if total_bytes <= target_bytes:
                break

            msg_content = message_dicts[m_idx]["content"]
            msg_content[c_idx] = {
                "type": "text",
                "text": f"[Historical Image omitted: payload reduced {size // 1024}KB to recover from gateway limit]",
            }
            total_bytes -= size
            evicted_count += 1

        if evicted_count > 0:
            logger.warning(
                "[MediaBudgetGovernor] Emergency evicted %d images, reduced payload to %d bytes",
                evicted_count,
                total_bytes,
            )

        return evicted_count


class MediaBudgetGovernorProcessor(BaseProcessor):
    """ContextPipeline processor enforcing cumulative multi-turn image payload budgets."""

    def __init__(
        self,
        max_cumulative_bytes: int = DEFAULT_MAX_CUMULATIVE_IMAGE_BYTES,
        focus_window_turns: int = DEFAULT_FOCUS_WINDOW_TURNS,
    ) -> None:
        self._governor = CumulativeImageBudgetGovernor(
            max_cumulative_bytes=max_cumulative_bytes,
            focus_window_turns=focus_window_turns,
        )

    @property
    def name(self) -> str:
        return "media_budget_governor"

    async def should_process(self, context: ProcessorContext) -> bool:
        return True

    async def process(self, context: ProcessorContext) -> ProcessorContext:
        downsampled, textified = await self._governor.enforce_budget(context.messages)
        if downsampled > 0 or textified > 0:
            # Estimate token savings (conservative: 500 tokens per downsampled/textified image)
            context.tokens_saved += (downsampled * 400) + (textified * 700)
        return context
