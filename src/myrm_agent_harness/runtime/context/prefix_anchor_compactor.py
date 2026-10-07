"""Prefix-anchor-preserving non-linear context compactor.

[INPUT]
Chat history message sequences, token budgets, and anchor tier configurations.

[OUTPUT]
Compacted message sequences maintaining Turn-1 topology and high prefix cache continuity.

[POS]
Item 124 in topic_06 roadmap: eliminates shift-window cache eviction via non-linear in-place folding.
"""

import threading
from collections.abc import Sequence

from myrm_agent_harness.runtime.context.prefix_anchor_compaction_types import (
    AnchoredMessageDescriptor,
    AnchorLockTier,
    MessageRoleKind,
    PrefixAnchorCompactionResult,
)


class PrefixAnchorPreservingCompactor:
    """Non-linear compactor preserving Turn-1 bearing wall and KV cache prefix continuity."""

    def __init__(
        self,
        turn1_protected_turns: int = 1,
        recent_tail_protected_turns: int = 2,
        max_folded_snippet_chars: int = 120,
    ) -> None:
        self.turn1_protected_turns = turn1_protected_turns
        self.recent_tail_protected_turns = recent_tail_protected_turns
        self.max_folded_snippet_chars = max_folded_snippet_chars
        self._lock = threading.RLock()

    def classify_message_tiers(
        self, messages: Sequence[AnchoredMessageDescriptor]
    ) -> tuple[AnchoredMessageDescriptor, ...]:
        """Classify messages into Turn-1 immutable, tail preserved, and intermediate foldable tiers."""
        if not messages:
            return ()

        max_turn = max(m.turn_index for m in messages)
        tail_threshold = max(self.turn1_protected_turns + 1, max_turn - self.recent_tail_protected_turns + 1)

        classified: list[AnchoredMessageDescriptor] = []
        for m in messages:
            # System message (turn 0) or Turn-1 user/assistant
            if m.turn_index <= self.turn1_protected_turns or m.role == MessageRoleKind.SYSTEM:
                classified.append(
                    AnchoredMessageDescriptor(
                        message_id=m.message_id,
                        turn_index=m.turn_index,
                        role=m.role,
                        content=m.content,
                        token_count=m.token_count,
                        tier=AnchorLockTier.TURN1_IMMUTABLE,
                        is_turn1_anchor=True,
                        is_protected=True,
                        is_folded=m.is_folded,
                    )
                )
            # Recent tail window
            elif m.turn_index >= tail_threshold:
                classified.append(
                    AnchoredMessageDescriptor(
                        message_id=m.message_id,
                        turn_index=m.turn_index,
                        role=m.role,
                        content=m.content,
                        token_count=m.token_count,
                        tier=AnchorLockTier.RECENT_WINDOW_PRESERVED,
                        is_turn1_anchor=False,
                        is_protected=True,
                        is_folded=m.is_folded,
                    )
                )
            # Intermediate candidate for folding
            else:
                classified.append(
                    AnchoredMessageDescriptor(
                        message_id=m.message_id,
                        turn_index=m.turn_index,
                        role=m.role,
                        content=m.content,
                        token_count=m.token_count,
                        tier=AnchorLockTier.INTERMEDIATE_COMPACTIBLE,
                        is_turn1_anchor=False,
                        is_protected=False,
                        is_folded=m.is_folded,
                    )
                )

        return tuple(classified)

    def compact_context(
        self,
        messages: Sequence[AnchoredMessageDescriptor],
        target_token_budget: int,
    ) -> PrefixAnchorCompactionResult:
        """Execute non-linear compaction folding intermediate tools while keeping Turn-1 anchor intact."""
        with self._lock:
            classified = self.classify_message_tiers(messages)
            original_tokens = sum(m.token_count for m in classified)

            if original_tokens <= target_token_budget or not classified:
                return PrefixAnchorCompactionResult(
                    compacted_messages=classified,
                    original_tokens=original_tokens,
                    compacted_tokens=original_tokens,
                    tokens_reclaimed=0,
                    prefix_overlap_ratio=1.0,
                    turn1_preserved=True,
                    folded_tool_count=0,
                )

            # We need to reclaim tokens: non-linearly fold intermediate tool messages
            tokens_needed = original_tokens - target_token_budget
            tokens_reclaimed = 0
            folded_count = 0

            compacted_list: list[AnchoredMessageDescriptor] = []
            for m in classified:
                if (
                    tokens_reclaimed < tokens_needed
                    and m.tier == AnchorLockTier.INTERMEDIATE_COMPACTIBLE
                    and m.role == MessageRoleKind.TOOL
                    and not m.is_folded
                ):
                    # In-place folding into structured digest tag
                    snippet = m.content[: self.max_folded_snippet_chars].replace("\n", " ")
                    if len(m.content) > self.max_folded_snippet_chars:
                        snippet += " ...[folded]"

                    folded_content = (
                        f'<folded_tool_result message_id="{m.message_id}" original_tokens="{m.token_count}">\n'
                        f"{snippet}\n"
                        f"</folded_tool_result>"
                    )
                    folded_tokens = max(10, len(folded_content) // 4)
                    saved = max(0, m.token_count - folded_tokens)

                    tokens_reclaimed += saved
                    folded_count += 1

                    compacted_list.append(
                        AnchoredMessageDescriptor(
                            message_id=m.message_id,
                            turn_index=m.turn_index,
                            role=m.role,
                            content=folded_content,
                            token_count=folded_tokens,
                            tier=m.tier,
                            is_turn1_anchor=m.is_turn1_anchor,
                            is_protected=m.is_protected,
                            is_folded=True,
                        )
                    )
                else:
                    compacted_list.append(m)

            final_tokens = sum(m.token_count for m in compacted_list)

            # Verify Turn-1 anchor preservation
            turn1_orig = [m for m in classified if m.is_turn1_anchor]
            turn1_compacted = [m for m in compacted_list if m.is_turn1_anchor]
            turn1_ok = (
                len(turn1_orig) == len(turn1_compacted)
                and all(
                    o.message_id == c.message_id and o.content == c.content
                    for o, c in zip(turn1_orig, turn1_compacted, strict=True)
                )
            )

            # Compute prefix overlap ratio (consecutive unchanged prefix tokens from start)
            prefix_unmodified_tokens = 0
            for orig_m, comp_m in zip(classified, compacted_list, strict=True):
                if orig_m.content == comp_m.content:
                    prefix_unmodified_tokens += orig_m.token_count
                else:
                    break

            overlap_ratio = (
                prefix_unmodified_tokens / original_tokens
                if original_tokens > 0
                else 1.0
            )

            return PrefixAnchorCompactionResult(
                compacted_messages=tuple(compacted_list),
                original_tokens=original_tokens,
                compacted_tokens=final_tokens,
                tokens_reclaimed=tokens_reclaimed,
                prefix_overlap_ratio=overlap_ratio,
                turn1_preserved=turn1_ok,
                folded_tool_count=folded_count,
            )
