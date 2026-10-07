"""Engine for collapsing deep reasoning thought streams and aligning prompt cache.

Implements sliding window retention, thought digest summarization,
multi-vendor reasoning normalization, and prompt cache prefix protection.
"""

import copy
import logging
import re
from typing import Optional

from .reasoning_collapse_types import (
    ReasoningCollapseConfig,
    ReasoningCollapseReport,
    ReasoningVendorType,
    ThinkingCollapseMode,
    UnifiedReasoningBlock,
)

logger = logging.getLogger(__name__)


class ReasoningStreamCollapseEngine:
    """Core engine for streaming thought collapse and prompt cache alignment."""

    def __init__(self, config: Optional[ReasoningCollapseConfig] = None) -> None:
        self.config = config or ReasoningCollapseConfig()
        self._session_blocks: dict[str, dict[int, UnifiedReasoningBlock]] = {}

    def ingest_turn_reasoning(
        self,
        session_id: str,
        turn_index: int,
        vendor: ReasoningVendorType,
        raw_thinking: str,
    ) -> UnifiedReasoningBlock:
        """Ingest and normalize raw reasoning content from an LLM response turn."""
        token_estimate = max(1, len(raw_thinking) // 4)
        block = UnifiedReasoningBlock.create(
            turn_index=turn_index,
            vendor=vendor,
            raw_content=raw_thinking,
            token_estimate=token_estimate,
        )
        if session_id not in self._session_blocks:
            self._session_blocks[session_id] = {}
        self._session_blocks[session_id][turn_index] = block
        return block

    def extract_thought_digest(self, raw_thinking: str, max_chars: int = 120) -> str:
        """Extract key decisions or conclusions from thinking text into a compact digest."""
        cleaned = re.sub(r"\s+", " ", raw_thinking).strip()
        if not cleaned:
            return "No thinking output recorded."

        # Search for decisive patterns (e.g. Conclusion, Decided, Plan, Action, Result)
        decision_patterns = [
            r"(?:therefore|conclude|conclusion|plan|decision|next step|i will|we should|in summary)[\s,:：]+([^.]+)",
            r"(?:因此|结论|决定|下一步|计划|核心方案|总结)[\s,:：]+([^。]+)",
        ]
        matched_points: list[str] = []
        for pat in decision_patterns:
            matches = re.findall(pat, cleaned, flags=re.IGNORECASE)
            for m in matches:
                item = m.strip()
                if item and item not in matched_points:
                    matched_points.append(item)
                if len(matched_points) >= 2:
                    break
            if matched_points:
                break

        if matched_points:
            summary = "; ".join(matched_points)
        else:
            if len(cleaned) <= max_chars:
                summary = cleaned
            else:
                summary = f"{cleaned[:max_chars // 2]}...{cleaned[-max_chars // 2:]}"

        if len(summary) > max_chars:
            summary = summary[:max_chars].rstrip() + "..."
        return summary

    def collapse_historical_messages(
        self,
        session_id: str,
        messages: list[dict[str, str]],
        active_turn_index: int,
    ) -> tuple[list[dict[str, str]], ReasoningCollapseReport]:
        """Collapse historical reasoning chains based on sliding window while keeping cache prefix intact."""
        processed_messages: list[dict[str, str]] = []
        blocks = self._session_blocks.get(session_id, {})

        original_tokens = 0
        collapsed_tokens = 0
        total_turns = len(messages)

        # Sliding window boundary: turns >= active_turn_index - sliding_window_turns are preserved
        window_start = max(0, active_turn_index - self.config.sliding_window_turns + 1)

        for idx, msg in enumerate(messages):
            msg_copy = copy.deepcopy(msg)
            content = msg_copy.get("content", "")
            turn_idx = idx

            # Extract reasoning tags if present (<think> or reasoning_content)
            think_match = re.search(r"<think>(.*?)</think>", content, flags=re.DOTALL)
            has_think_tags = bool(think_match)

            raw_thinking = ""
            if has_think_tags and think_match:
                raw_thinking = think_match.group(1).strip()
            elif turn_idx in blocks:
                raw_thinking = blocks[turn_idx].raw_content

            if raw_thinking:
                block_tokens = max(1, len(raw_thinking) // 4)
                original_tokens += block_tokens

                # Check if this turn should be collapsed
                should_collapse = False
                if self.config.mode == ThinkingCollapseMode.FULL_RETAIN:
                    should_collapse = False
                elif self.config.mode == ThinkingCollapseMode.DIGEST_ONLY:
                    should_collapse = True
                elif self.config.mode == ThinkingCollapseMode.AGGRESSIVE_PRUNE:
                    should_collapse = True
                elif self.config.mode == ThinkingCollapseMode.SLIDING_WINDOW:
                    should_collapse = turn_idx < window_start

                if should_collapse and block_tokens >= self.config.min_tokens_to_collapse:
                    digest = self.extract_thought_digest(raw_thinking)
                    digest_tag = f"<thought_digest turn={turn_idx}>{digest}</thought_digest>"
                    digest_tokens = max(1, len(digest_tag) // 4)
                    effective_digest_tokens = min(block_tokens, digest_tokens)
                    collapsed_tokens += effective_digest_tokens

                    if has_think_tags:
                        msg_copy["content"] = re.sub(
                            r"<think>.*?</think>",
                            digest_tag,
                            content,
                            flags=re.DOTALL,
                        )
                    else:
                        msg_copy["reasoning_digest"] = digest_tag
                else:
                    collapsed_tokens += block_tokens

            processed_messages.append(msg_copy)

        saved = max(0, original_tokens - collapsed_tokens)
        ratio = (saved / original_tokens) if original_tokens > 0 else 0.0

        # Verify prompt cache prefix alignment: system prompt must be first and unaffected
        prefix_aligned = True
        if processed_messages and processed_messages[0].get("role") == "system":
            first_msg = processed_messages[0].get("content", "")
            if "<thought_digest" in first_msg or "<think>" in first_msg:
                prefix_aligned = False

        report = ReasoningCollapseReport(
            session_id=session_id,
            total_turns=total_turns,
            active_turn_index=active_turn_index,
            original_reasoning_tokens=original_tokens,
            collapsed_reasoning_tokens=collapsed_tokens,
            tokens_saved=saved,
            compression_ratio=round(ratio, 4),
            cache_prefix_aligned=prefix_aligned,
        )
        return processed_messages, report

    def verify_prompt_cache_prefix_alignment(
        self,
        messages: list[dict[str, str]],
        system_fingerprint: str,
    ) -> bool:
        """Verify prompt cache prefix integrity: system prompt must remain strictly immutable."""
        if not messages:
            return False
        first_role = messages[0].get("role")
        if first_role != "system":
            return False
        content = messages[0].get("content", "")
        return system_fingerprint in content
