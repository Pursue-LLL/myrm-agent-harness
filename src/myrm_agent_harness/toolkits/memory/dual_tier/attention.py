"""Memory Attention dynamic weighting and context fusion router.

Calculates cross-attention between the active task query and dual-tier memory blocks
(Hyper vs Local), allocates dynamic token budgets, and formats structured prompts
with strict scope boundaries to eliminate semantic aliasing.

[INPUT]
- myrm_agent_harness.toolkits.memory.dual_tier.models::HyperMemoryBlock, LocalMemoryBlock, AttentionFusionContext (POS: data schemas)
- re, math (POS: standard library tokenization and scoring utilities)

[OUTPUT]
- MemoryAttentionRouter: Core routing class for computing attention scores and prompt assembly.

[POS]
Memory Attention Fusion layer inspired by Fast Weight Programming (Metis / arXiv:2607.26760).
"""

from __future__ import annotations

import re
from typing import Final

from myrm_agent_harness.toolkits.memory.dual_tier.models import (
    AttentionFusionContext,
    HyperMemoryBlock,
    LocalMemoryBlock,
)

_TOKEN_SPLIT_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^\w\-]+", re.UNICODE)
_STOP_WORDS: Final[frozenset[str]] = frozenset(
    {
        "a", "an", "the", "and", "or", "in", "on", "at", "to", "for", "with",
        "is", "are", "was", "were", "it", "this", "that", "of", "by", "from",
        "my", "you", "we", "he", "she", "they", "me", "him", "her", "us",
        "do", "does", "did", "have", "has", "had", "be", "been", "being",
    }
)


def _tokenize(text: str) -> set[str]:
    """Extract lowercased non-stopword tokens from text."""
    tokens = _TOKEN_SPLIT_PATTERN.split(text.lower())
    return {t for t in tokens if len(t) > 1 and t not in _STOP_WORDS}


class MemoryAttentionRouter:
    """Calculates task-memory attention and synthesizes safe, scoped prompt injections."""

    def __init__(
        self,
        min_activation_threshold: float = 0.15,
        max_hyper_chars: int = 4000,
        max_local_chars: int = 4000,
    ) -> None:
        self.min_activation_threshold = min_activation_threshold
        self.max_hyper_chars = max_hyper_chars
        self.max_local_chars = max_local_chars

    def compute_hyper_attention(self, query_tokens: set[str], block: HyperMemoryBlock) -> float:
        """Compute attention score for a long-term HyperMemoryBlock."""
        if block.status != "active":
            return 0.0

        block_tokens = _tokenize(block.statement)
        if not block_tokens:
            return block.confidence * 0.3

        overlap = len(query_tokens & block_tokens)
        overlap_score = overlap / (len(block_tokens) + 1.0)

        # Baseline attention incorporates high intrinsic confidence + query overlap
        base_weight = 0.35 * block.confidence
        query_weight = 0.65 * min(1.0, overlap_score * 2.0)
        return round(min(1.0, base_weight + query_weight), 4)

    def compute_local_attention(self, query_tokens: set[str], block: LocalMemoryBlock) -> float:
        """Compute attention score for a session-bound LocalMemoryBlock."""
        from myrm_agent_harness.toolkits.memory.types import EvaporationState

        if block.evaporation_state == EvaporationState.EVAPORATED:
            return 0.0

        block_tokens = _tokenize(block.content)
        if not block_tokens:
            return 0.2 if block.verified_useful else 0.1

        overlap = len(query_tokens & block_tokens)
        overlap_score = overlap / (len(block_tokens) + 1.0)

        score = min(1.0, overlap_score * 2.5)
        if block.verified_useful:
            score = min(1.0, score + 0.2)
        if block.transient_tag == "tool_override":
            score = min(1.0, score + 0.15)

        return round(score, 4)

    def fuse(
        self,
        task_query: str,
        hyper_blocks: list[HyperMemoryBlock],
        local_blocks: list[LocalMemoryBlock],
    ) -> AttentionFusionContext:
        """Route and assemble dual-tier memory blocks into an attention-weighted context."""
        query_tokens = _tokenize(task_query)

        # 1. Score and filter Hyper Blocks
        hyper_scores: dict[str, float] = {}
        active_hyper: list[HyperMemoryBlock] = []
        for hb in hyper_blocks:
            score = self.compute_hyper_attention(query_tokens, hb)
            if score >= self.min_activation_threshold:
                hyper_scores[hb.block_id] = score
                active_hyper.append(hb)

        # Sort hyper blocks by attention score descending
        active_hyper.sort(key=lambda b: hyper_scores.get(b.block_id, 0.0), reverse=True)

        # 2. Score and filter Local Blocks
        local_scores: dict[str, float] = {}
        active_local: list[LocalMemoryBlock] = []
        for lb in local_blocks:
            score = self.compute_local_attention(query_tokens, lb)
            if score >= self.min_activation_threshold:
                local_scores[lb.block_id] = score
                active_local.append(lb)

        # Sort local blocks by attention score descending
        active_local.sort(key=lambda b: local_scores.get(b.block_id, 0.0), reverse=True)

        # 3. Format structured prompt with strict boundary isolation
        formatted_prompt = self._format_prompt(active_hyper, active_local)

        return AttentionFusionContext(
            hyper_weights=hyper_scores,
            local_weights=local_scores,
            hyper_blocks=active_hyper,
            local_blocks=active_local,
            formatted_prompt=formatted_prompt,
        )

    def _format_prompt(
        self,
        hyper_blocks: list[HyperMemoryBlock],
        local_blocks: list[LocalMemoryBlock],
    ) -> str:
        """Format dual-tier blocks into scoped markdown prompt sections."""
        sections: list[str] = []

        if hyper_blocks:
            hyper_lines: list[str] = [
                "### [Global Mental Models & Long-term Preferences (Hyper Memory)]",
                "The following are enduring, verified preferences and architectural rules:",
            ]
            total_chars = 0
            for hb in hyper_blocks:
                line = f"- [{hb.category.upper()}] {hb.statement} (confidence: {hb.confidence:.2f})"
                if total_chars + len(line) > self.max_hyper_chars:
                    break
                hyper_lines.append(line)
                total_chars += len(line)
            sections.append("\n".join(hyper_lines))

        if local_blocks:
            local_lines: list[str] = [
                "### [Active Session Transient Context (Local Memory)]",
                "⚠️ CAUTION: The following entries are temporary task entities for the current session ONLY. "
                "DO NOT treat them as global rules or propagate them across sessions:",
            ]
            total_chars = 0
            for lb in local_blocks:
                verified_mark = " [VERIFIED]" if lb.verified_useful else ""
                line = f"- ({lb.transient_tag}){verified_mark}: {lb.content}"
                if total_chars + len(line) > self.max_local_chars:
                    break
                local_lines.append(line)
                total_chars += len(line)
            sections.append("\n".join(local_lines))

        return "\n\n".join(sections)
