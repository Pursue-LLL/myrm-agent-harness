"""Core engine for Visual Frame Context Pruning and Latency Squeezing.

[INPUT]
- visual_pruner_types: Configuration, pruning result, and audit footprint models.

[OUTPUT]
- VisualFramePruningEngine: Multimodal sliding window dehydrator and latency squeezer.

[POS]
Executes in-memory scanning and replacement of multimodal base64 image blocks,
preventing context window blowup and attentional degradation across long Computer Use sessions.
"""

from __future__ import annotations

import copy
import re
import time

from myrm_agent_harness.agent.context_management.visual_pruner.visual_pruner_types import (
    PrunedFrameFootprint,
    VisualPruningConfig,
    VisualPruningMode,
    VisualPruningResult,
)


class VisualFramePruningEngine:
    """Multimodal sliding window dehydrator for Computer Use and browser automation."""

    def __init__(self, config: VisualPruningConfig | None = None) -> None:
        self._config = config or VisualPruningConfig()

    @property
    def config(self) -> VisualPruningConfig:
        """Returns active pruning configuration."""
        return self._config

    @staticmethod
    def _is_image_block(block: object) -> bool:
        """Determines whether a content block represents an image payload."""
        if not isinstance(block, dict):
            return False
        b_type = block.get("type")
        if b_type in ("image", "image_url", "input_image"):
            return True
        if "image_url" in block or "source" in block:
            return True
        return False

    @staticmethod
    def _calculate_image_bytes(block: dict[str, object]) -> int:
        """Estimates raw byte size of the image payload."""
        img_url = block.get("image_url")
        if isinstance(img_url, dict):
            url_str = str(img_url.get("url", ""))
            return len(url_str)

        source = block.get("source")
        if isinstance(source, dict):
            data_str = str(source.get("data", ""))
            return len(data_str)

        return len(str(block))

    @staticmethod
    def _extract_turn_action_summary(msg: dict[str, object], turn_idx: int) -> str:
        """Heuristically extracts concise action descriptions from message metadata."""
        tool_calls = msg.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            first_call = tool_calls[0]
            if isinstance(first_call, dict):
                t_name = str(first_call.get("name") or first_call.get("tool_name") or "tool")
                args = first_call.get("args") or first_call.get("arguments") or {}
                if isinstance(args, dict):
                    action = args.get("action") or args.get("command") or args.get("method") or ""
                    coord = args.get("coordinate") or args.get("coords") or ""
                    if action:
                        target_str = f" {coord}" if coord else ""
                        return f"{t_name} action='{action}'{target_str}"
                return f"{t_name} invoked"

        content = msg.get("content")
        if isinstance(content, str) and content.strip():
            first_line = content.strip().split("\n")[0][:80]
            return first_line

        return f"Interaction step {turn_idx}"

    def prune_messages(
        self, messages: list[dict[str, object]]
    ) -> VisualPruningResult:
        """Scans message chain, identifies image blocks, and evicts older frames outside sliding window."""
        start_time = time.perf_counter()

        if self._config.is_bypass() or not messages:
            return VisualPruningResult(
                total_images_found=0,
                retained_image_count=0,
                pruned_image_count=0,
                estimated_tokens_saved=0,
                reclaimed_bytes=0,
                pruned_footprints=[],
                cleansed_messages=messages,
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
            )

        # 1. First pass: locate all image positions (msg_idx, block_idx_or_inline)
        image_locations: list[tuple[int, int, int]] = []  # (msg_idx, block_idx, byte_size)

        for m_idx, msg in enumerate(messages):
            content = msg.get("content")
            if isinstance(content, list):
                for b_idx, block in enumerate(content):
                    if self._is_image_block(block) and isinstance(block, dict):
                        b_size = self._calculate_image_bytes(block)
                        image_locations.append((m_idx, b_idx, b_size))

        total_images = len(image_locations)
        if total_images <= self._config.window_size:
            return VisualPruningResult(
                total_images_found=total_images,
                retained_image_count=total_images,
                pruned_image_count=0,
                estimated_tokens_saved=0,
                reclaimed_bytes=0,
                pruned_footprints=[],
                cleansed_messages=messages,
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
            )

        # 2. Determine indices of images to retain
        retained_indices: set[int] = set()
        window_size = self._config.window_size

        # Retain latest N images
        start_retain = max(0, total_images - window_size)
        for i in range(start_retain, total_images):
            retained_indices.add(i)

        # Optionally retain initial frame
        if (
            self._config.mode == VisualPruningMode.SLIDING_WINDOW_KEEP_INITIAL
            and total_images > 0
        ):
            retained_indices.add(0)

        # 3. Deep copy messages and perform in-place replacement
        new_messages: list[dict[str, object]] = copy.deepcopy(messages)
        pruned_footprints: list[PrunedFrameFootprint] = []
        reclaimed_bytes = 0
        tokens_saved = 0

        for img_idx, (m_idx, b_idx, b_size) in enumerate(image_locations):
            if img_idx in retained_indices:
                continue

            target_msg = new_messages[m_idx]
            content = target_msg.get("content")
            if not isinstance(content, list):
                continue

            # Extract turn summary
            action_summary = self._extract_turn_action_summary(target_msg, m_idx)
            placeholder_text = self._config.placeholder_template.format(
                turn=m_idx, summary=action_summary
            )

            # Replace image block with compact dehydrated text block
            content[b_idx] = {
                "type": "text",
                "text": placeholder_text,
            }

            footprint = PrunedFrameFootprint(
                turn_index=m_idx,
                action_summary=action_summary,
                reclaimed_bytes=b_size,
                estimated_tokens_saved=self._config.tokens_per_image_estimate,
            )
            pruned_footprints.append(footprint)
            reclaimed_bytes += b_size
            tokens_saved += self._config.tokens_per_image_estimate

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        return VisualPruningResult(
            total_images_found=total_images,
            retained_image_count=len(retained_indices),
            pruned_image_count=len(pruned_footprints),
            estimated_tokens_saved=tokens_saved,
            reclaimed_bytes=reclaimed_bytes,
            pruned_footprints=pruned_footprints,
            cleansed_messages=new_messages,
            duration_ms=duration_ms,
        )
