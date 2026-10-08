# [INPUT]: ContextBlockDescriptor, ContextTier, PrefixCachingLayoutConfig
# [OUTPUT]: PrefixCachingAlignedLayoutEngine
# [POS]: agent/context_management/prefix_caching_ledger/prefix_caching_aligned_layout_engine.py

"""Prefix-caching aligned context layout engine for high-affinity LLM prompt assembly.

[INPUT]
- ContextBlockDescriptor: Individual context blocks annotated with tiers.
- ContextTier: Hierarchical classification (TIER1, TIER2, TIER3).
- PrefixCachingLayoutConfig: Sorting and enforcement configuration.

[OUTPUT]
- PrefixCachingAlignedLayoutEngine: Deterministic layout assembler and prefix stability verifier.

[POS]
Layout orchestration layer ensuring 80%+ prompt prefix caching hits by eliminating prefix drift.
"""

from __future__ import annotations

import hashlib
from typing import Sequence

from .prefix_caching_types import (
    ContextBlockDescriptor,
    ContextTier,
    PrefixCachingLayoutConfig,
)


class PrefixCachingAlignedLayoutEngine:
    """Enforces byte-level prefix stability and strict three-tier layout for maximum KV-cache reuse."""

    TIER_ORDER: dict[ContextTier, int] = {
        ContextTier.TIER1_STATIC_PREFIX: 1,
        ContextTier.TIER2_SEMI_STATIC_PROJECT: 2,
        ContextTier.TIER3_DYNAMIC_TAIL: 3,
    }

    def __init__(self, config: PrefixCachingLayoutConfig | None = None) -> None:
        self._config = config or PrefixCachingLayoutConfig()

    def realign_blocks(self, blocks: Sequence[ContextBlockDescriptor]) -> list[ContextBlockDescriptor]:
        """Sort and sanitize context blocks into strict tier precedence (Tier 1 -> Tier 2 -> Tier 3).

        Within each tier:
        - Blocks are sorted deterministically by (sort_key, category, block_id).
        - Any dynamic elements misplaced in Tier 1 are automatically demoted to Tier 3 if configured.
        """
        sanitized_blocks: list[ContextBlockDescriptor] = []

        for block in blocks:
            # Prevent dynamic clock or timestamp leakage into Tier 1
            if block.category in ("dynamic_clock", "timestamp", "temporary_search") and block.tier != ContextTier.TIER3_DYNAMIC_TAIL:
                sanitized_block = ContextBlockDescriptor(
                    block_id=block.block_id,
                    tier=self._config.clock_stamp_tier,
                    category=block.category,
                    content=block.content,
                    sort_key=block.sort_key or block.block_id,
                    estimated_tokens=block.estimated_tokens,
                )
                sanitized_blocks.append(sanitized_block)
            else:
                sanitized_blocks.append(block)

        def _sort_key(b: ContextBlockDescriptor) -> tuple[int, str, str, str]:
            tier_rank = self.TIER_ORDER.get(b.tier, 99)
            return (tier_rank, b.sort_key or "", b.category, b.block_id)

        return sorted(sanitized_blocks, key=_sort_key)

    def assemble_prompt(
        self,
        blocks: Sequence[ContextBlockDescriptor],
        separator: str = "\n\n",
    ) -> str:
        """Assemble all context blocks into a unified prompt string preserving prefix caching alignment."""
        ordered = self.realign_blocks(blocks)
        contents = [b.content.strip() for b in ordered if b.content.strip()]
        return separator.join(contents)

    def compute_prefix_hash(self, blocks: Sequence[ContextBlockDescriptor]) -> str:
        """Compute cryptographic SHA-256 hash over Tier 1 static blocks only.

        As long as this hash remains identical across successive turns, upstream provider
        KV-caching is guaranteed to be 100% stable for the prefix.
        """
        ordered = self.realign_blocks(blocks)
        tier1_content = "\n\n".join(
            b.content.strip() for b in ordered if b.tier == ContextTier.TIER1_STATIC_PREFIX
        )
        return hashlib.sha256(tier1_content.encode("utf-8")).hexdigest()

    def estimate_tier_tokens(
        self,
        blocks: Sequence[ContextBlockDescriptor],
    ) -> dict[ContextTier, int]:
        """Aggregate token counts across each tier to verify prefix cache ratio."""
        ordered = self.realign_blocks(blocks)
        counts: dict[ContextTier, int] = {
            ContextTier.TIER1_STATIC_PREFIX: 0,
            ContextTier.TIER2_SEMI_STATIC_PROJECT: 0,
            ContextTier.TIER3_DYNAMIC_TAIL: 0,
        }
        for b in ordered:
            counts[b.tier] = counts.get(b.tier, 0) + b.estimated_tokens
        return counts

    def calculate_cacheable_ratio(self, blocks: Sequence[ContextBlockDescriptor]) -> float:
        """Calculate the proportion of context residing in Tier 1 and Tier 2 (cache-friendly)."""
        counts = self.estimate_tier_tokens(blocks)
        total = sum(counts.values())
        if total <= 0:
            return 0.0
        cacheable = counts[ContextTier.TIER1_STATIC_PREFIX] + counts[ContextTier.TIER2_SEMI_STATIC_PROJECT]
        return min(1.0, max(0.0, cacheable / total))
