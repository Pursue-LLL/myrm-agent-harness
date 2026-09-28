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

from dataclasses import dataclass
from typing import Final

from langchain_core.messages import BaseMessage

from myrm_agent_harness.utils.image_utils import (
    estimate_base64_byte_size,
    get_image_url,
    is_base64_data_url,
    is_image_content_item,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.media.base64_downsampler import (
    DEFAULT_DOWNSAMPLE_MAX_DIM,
    DEFAULT_DOWNSAMPLE_QUALITY,
    downsample_base64_image,
    probe_base64_image_meta,
)

from ..base import BaseProcessor, ProcessorContext

logger = get_agent_logger(__name__)

# Default budget: 10 MiB cumulative base64 payload across all messages in context
# Most API gateways (Nginx/Cloudflare/OneAPI) enforce 15-25 MiB max request body.
DEFAULT_MAX_CUMULATIVE_IMAGE_BYTES: Final[int] = 10 * 1024 * 1024

# Focus window: Protect latest N turns from being downsampled or evicted
DEFAULT_FOCUS_WINDOW_TURNS: Final[int] = 2

# Quantum offload margin: When payload exceeds budget, shrink by an extra quantum margin
# to prevent consecutive per-turn single-image thrashing and preserve Prefix Prompt Cache.
DEFAULT_QUANTUM_OFFLOAD_BYTES: Final[int] = 2 * 1024 * 1024

# Tier 2 downsampling target dimensions & quality
TIER2_DOWNSAMPLE_MAX_DIM: Final[int] = DEFAULT_DOWNSAMPLE_MAX_DIM
TIER2_DOWNSAMPLE_QUALITY: Final[float] = DEFAULT_DOWNSAMPLE_QUALITY

# Tier 4 Focus window safety net downsampling (preserves high-res vision reasoning)
TIER4_FOCUS_DOWNSAMPLE_MAX_DIM: Final[int] = 1024
TIER4_FOCUS_DOWNSAMPLE_QUALITY: Final[float] = 0.80

# Backward-compatibility alias for internal module and tests
_downsample_base64_image = downsample_base64_image


@dataclass(slots=True)
class ImageItemRef:
    """Reference pointer to an image item inside context.messages."""

    msg_idx: int
    item_idx: int
    data_url: str
    byte_size: int
    is_focus: bool



import asyncio

class CumulativeImageBudgetGovernor:
    """Core governor tracking and progressively enforcing multi-turn image payload limits."""

    def __init__(
        self,
        max_cumulative_bytes: int = DEFAULT_MAX_CUMULATIVE_IMAGE_BYTES,
        focus_window_turns: int = DEFAULT_FOCUS_WINDOW_TURNS,
        quantum_offload_bytes: int = DEFAULT_QUANTUM_OFFLOAD_BYTES,
    ) -> None:
        self.max_cumulative_bytes = max_cumulative_bytes
        self.focus_window_turns = focus_window_turns
        self.quantum_offload_bytes = quantum_offload_bytes

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

        Uses Quantum Offloading to establish a buffer below max_cumulative_bytes,
        preventing single-image churn in successive turns and preserving Prefix Prompt Cache.

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

        # Quantum target: Once over budget, shrink by an extra quantum margin to lock historical prefixes
        effective_target = max(1024, self.max_cumulative_bytes - self.quantum_offload_bytes)

        downsampled_count = 0
        textified_count = 0

        # Tier 2: Downsample non-focus images from oldest to newest toward quantum buffer
        non_focus_items = [it for it in items if not it.is_focus]
        for item in non_focus_items:
            if total_bytes <= effective_target:
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

        # Tier 3: If still over budget, convert oldest non-focus images to structured text placeholders
        if total_bytes > self.max_cumulative_bytes:
            for item in non_focus_items:
                if total_bytes <= effective_target:
                    break

                content = messages[item.msg_idx].content
                if isinstance(content, list) and item.item_idx < len(content):
                    meta = probe_base64_image_meta(item.data_url)
                    meta_desc = f"; original: {meta[0]}x{meta[1]} {meta[2]}" if meta else ""
                    content[item.item_idx] = {
                        "type": "text",
                        "text": f"[Historical Image omitted: payload reduced {item.byte_size // 1024}KB{meta_desc}; use file/vision tools to re-inspect if needed]",
                    }
                    total_bytes -= item.byte_size
                    textified_count += 1

        # Tier 4: Focus window safety net — if total payload still exceeds budget
        if total_bytes > self.max_cumulative_bytes:
            focus_items = [it for it in items if it.is_focus]
            focus_items.sort(key=lambda it: it.byte_size, reverse=True)
            for item in focus_items:
                if total_bytes <= self.max_cumulative_bytes:
                    break
                if item.byte_size <= 4 * 1024:
                    continue

                downsampled_url = await asyncio.to_thread(
                    _downsample_base64_image,
                    item.data_url,
                    max_dim=TIER4_FOCUS_DOWNSAMPLE_MAX_DIM,
                    quality=TIER4_FOCUS_DOWNSAMPLE_QUALITY,
                )
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
        message_dicts: list[dict[str, object]],
        target_bytes: int = 5 * 1024 * 1024,
        force_shrink: bool = False,
    ) -> int:
        """Synchronously downsample or evict images in raw dict messages.

        Delegates to the framework-neutral implementation in
        ``toolkits.llms.adapters.image_payload_evictor`` (agent/ may import
        toolkits/, never the reverse).
        """
        from myrm_agent_harness.toolkits.llms.adapters.image_payload_evictor import (
            emergency_evict_from_message_dicts as _evict_dicts,
        )

        return _evict_dicts(message_dicts, target_bytes=target_bytes, force_shrink=force_shrink)

    @classmethod
    def emergency_evict(
        cls,
        messages: list[object],
        target_bytes: int = 5 * 1024 * 1024,
        force_shrink: bool = False,
    ) -> int:
        """Unified emergency eviction supporting both BaseMessage instances and raw dicts.

        Delegates to the framework-neutral implementation in
        ``toolkits.llms.adapters.image_payload_evictor``.
        """
        from myrm_agent_harness.toolkits.llms.adapters.image_payload_evictor import (
            emergency_evict as _evict,
        )

        return _evict(messages, target_bytes=target_bytes, force_shrink=force_shrink)



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
