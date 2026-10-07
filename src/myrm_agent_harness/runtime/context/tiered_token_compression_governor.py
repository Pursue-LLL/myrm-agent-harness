"""Tiered token compression governor with reasoning preservation and budget enforcement.

Coordinates multi-dimensional budget governance across text, reasoning chains,
multimodal images, and tool executions inspired by OpenAI Codex Harness.

[INPUT]
- runtime.context.reasoning_anchor_extractor::ReasoningAnchorExtractor (POS: Extractor for condensing raw
  reasoning streams into structured logic anchors.)
- runtime.context.reasoning_compactor_types::CompactionTier, GovernanceCompactionResult,
  ReasoningChainAnchor, TieredTokenBudget, UnifiedCompactedTurn (POS: Type definitions for
  reasoning-preserving context compactor and token compression governor.)

[OUTPUT]
- TieredTokenCompressionGovernor: Orchestrates tiered context compaction while preserving critical reasoning
  chains.

[POS]
Tiered token compression governor with reasoning preservation and budget enforcement.
"""

import re
from collections.abc import Mapping

from myrm_agent_harness.runtime.context.reasoning_anchor_extractor import (
    ReasoningAnchorExtractor,
)
from myrm_agent_harness.runtime.context.reasoning_compactor_types import (
    CompactionTier,
    GovernanceCompactionResult,
    ReasoningChainAnchor,
    TieredTokenBudget,
    UnifiedCompactedTurn,
)


class TieredTokenCompressionGovernor:
    """Orchestrates tiered context compaction while preserving critical reasoning chains."""

    def __init__(
        self,
        extractor: ReasoningAnchorExtractor | None = None,
    ) -> None:
        self._extractor = extractor or ReasoningAnchorExtractor()

    def govern_and_compact(
        self,
        turn_records: list[Mapping[str, object]],
        budget: TieredTokenBudget | None = None,
        provider_supports_native_compaction: bool = False,
    ) -> GovernanceCompactionResult:
        """Apply tiered compaction across turns according to budget constraints."""
        cfg = budget or TieredTokenBudget()
        total_turns = len(turn_records)
        retain_cutoff = max(0, total_turns - cfg.retain_recent_turns)

        # 1. Initial usage profiling
        original_stats = self._profile_tokens(turn_records)
        orig_total = sum(original_stats.values())

        tiers_applied: list[CompactionTier] = []
        compacted_turns: list[UnifiedCompactedTurn] = []
        anchors_count = 0

        # Check if compaction is needed
        needs_compaction = (
            orig_total > cfg.max_total_tokens
            or original_stats["reasoning"] > cfg.max_reasoning_tokens
            or original_stats["image"] > cfg.max_image_tokens
        )

        # Tier flags
        apply_tier1 = needs_compaction
        apply_tier2 = needs_compaction and original_stats["image"] > cfg.max_image_tokens
        apply_tier3 = needs_compaction and (
            orig_total > cfg.max_total_tokens
            or original_stats["reasoning"] > cfg.max_reasoning_tokens
        )

        if apply_tier1:
            tiers_applied.append(CompactionTier.TIER_1_TOOLS)
        if apply_tier2:
            tiers_applied.append(CompactionTier.TIER_2_IMAGES)
        if apply_tier3:
            tiers_applied.append(CompactionTier.TIER_3_REASONING)

        # Process each turn
        for idx, turn in enumerate(turn_records):
            role = str(turn.get("role", "assistant"))
            content = str(turn.get("content", ""))
            raw_reasoning = str(
                turn.get("reasoning_content") or turn.get("thought") or ""
            )
            # Also extract in-line thinking tags if present
            if not raw_reasoning and ("<thinking>" in content or "<thought>" in content):
                m = re.search(r"<(?:thinking|thought)>(.*?)</(?:thinking|thought)>", content, re.DOTALL)
                if m:
                    raw_reasoning = m.group(1).strip()
                    content = re.sub(r"<(?:thinking|thought)>.*?</(?:thinking|thought)>", "", content, flags=re.DOTALL).strip()

            is_protected_recent = idx >= retain_cutoff
            anchor: ReasoningChainAnchor | None = None
            is_image_degraded = False

            # Reasoning preservation logic
            if raw_reasoning:
                if is_protected_recent or not apply_tier3:
                    # Keep full reasoning in content
                    content = f"<reasoning>\n{raw_reasoning}\n</reasoning>\n\n{content}"
                else:
                    # Distill to reasoning anchor
                    anchor = self._extractor.extract_anchor(idx, raw_reasoning)
                    anchors_count += 1
                    content = f"{self._extractor.render_condensed_anchor_block(anchor)}\n\n{content}"

            # Multimodal image degradation
            if apply_tier2 and not is_protected_recent and (
                "data:image" in content or "[Image:" in content
            ):
                content = re.sub(
                    r"data:image\/[a-zA-Z]+;base64,[A-Za-z0-9+/=]+",
                    "[Image degraded: base64 omitted (~120 tokens)]",
                    content,
                )
                is_image_degraded = True

            # Tool execution folding (Tier 1)
            tool_summary: str | None = None
            if apply_tier1 and not is_protected_recent:
                tool_calls = turn.get("tool_calls")
                if isinstance(tool_calls, list) and len(tool_calls) > 0:
                    names = [str(tc.get("name", "tool")) for tc in tool_calls if isinstance(tc, dict)]
                    tool_summary = f"[Folded {len(names)} tool calls: {', '.join(names)}]"

            compacted_turns.append(
                UnifiedCompactedTurn(
                    turn_index=idx,
                    role=role,
                    content=content,
                    reasoning_anchor=anchor,
                    tool_calls_summary=tool_summary,
                    is_image_degraded=is_image_degraded,
                )
            )

        # Re-profile compacted tokens
        final_total = sum(max(1, len(t.content) // 4) for t in compacted_turns)

        # Tier 4 fallback if still exceeding total budget
        if final_total > cfg.max_total_tokens and retain_cutoff > 0:
            tiers_applied.append(CompactionTier.TIER_4_TEXT_CUT)
            # Truncate oldest turns until fitting budget
            for i in range(retain_cutoff):
                if final_total <= cfg.max_total_tokens:
                    break
                t = compacted_turns[i]
                if len(t.content) > 300:
                    saved_chars = len(t.content) - 300
                    truncated_content = t.content[:300] + " ... [Truncated past content]"
                    compacted_turns[i] = UnifiedCompactedTurn(
                        turn_index=t.turn_index,
                        role=t.role,
                        content=truncated_content,
                        reasoning_anchor=t.reasoning_anchor,
                        tool_calls_summary=t.tool_calls_summary,
                        is_image_degraded=t.is_image_degraded,
                    )
                    final_total -= saved_chars // 4

        compressed_tokens = max(0, orig_total - final_total)
        native_eligible = (
            provider_supports_native_compaction
            and len(tiers_applied) <= 1
            and CompactionTier.TIER_1_TOOLS in tiers_applied
        )

        return GovernanceCompactionResult(
            original_total_tokens=orig_total,
            final_total_tokens=final_total,
            compressed_tokens=compressed_tokens,
            tiers_applied=tiers_applied,
            reasoning_anchors_count=anchors_count,
            native_server_side_eligible=native_eligible,
            compacted_turns=compacted_turns,
        )

    def _profile_tokens(
        self, turn_records: list[Mapping[str, object]]
    ) -> dict[str, int]:
        """Estimate tokens grouped by text, reasoning, image, and tool."""
        text_chars = 0
        reasoning_chars = 0
        image_chars = 0
        tool_chars = 0

        for turn in turn_records:
            c = str(turn.get("content", ""))
            r = str(turn.get("reasoning_content") or turn.get("thought") or "")

            if "data:image" in c:
                image_chars += len(c)
            else:
                text_chars += len(c)

            reasoning_chars += len(r)

            tc = turn.get("tool_calls")
            if tc:
                tool_chars += len(str(tc))

        return {
            "text": max(1, text_chars // 4),
            "reasoning": max(1, reasoning_chars // 4),
            "image": max(0, image_chars // 4),
            "tool": max(0, tool_chars // 4),
        }
