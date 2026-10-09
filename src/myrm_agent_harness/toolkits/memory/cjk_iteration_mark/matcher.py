"""Bidirectional recall matcher for CJK text with ideographic iteration marks.

Computes weighted lexical overlap across raw, normalized, and anchor bigram sets,
ensuring high recall whether the query uses '々' or expanded Han kanji.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.cjk_iteration_mark.models import (
    CjkRecallMatchScore,
)
from myrm_agent_harness.toolkits.memory.cjk_iteration_mark.resolver import (
    IterationMarkResolver,
)


class CjkIterationRecallMatcher:
    """Matches search queries against target memory text taking iteration marks into account."""

    def __init__(self, resolver: IterationMarkResolver | None = None) -> None:
        self._resolver: IterationMarkResolver = resolver or IterationMarkResolver()

    def match(
        self,
        query: str,
        target_text: str,
        *,
        threshold: float = 0.1,
    ) -> CjkRecallMatchScore:
        """Evaluate match score between query and target memory text."""
        if not query.strip() or not target_text.strip():
            return CjkRecallMatchScore(
                query=query,
                target=target_text,
                is_matched=False,
                raw_overlap_count=0,
                normalized_overlap_count=0,
                anchor_overlap_count=0,
                composite_score=0.0,
                matched_tokens=(),
            )

        q_res = self._resolver.resolve(query)
        t_res = self._resolver.resolve(target_text)

        # Overlap across dimensions
        raw_overlap = set(q_res.tokens.raw_tokens) & set(t_res.tokens.raw_tokens)
        norm_overlap = set(q_res.tokens.normalized_tokens) & set(t_res.tokens.normalized_tokens)
        anchor_overlap = set(q_res.tokens.anchor_tokens) & set(t_res.tokens.anchor_tokens)

        # All matched tokens
        all_matched = sorted(raw_overlap | norm_overlap | anchor_overlap)

        total_query_tokens = len(q_res.tokens.all_tokens) or 1

        # Weighed scoring:
        # - Normalized overlap captures true semantic intent (weight 0.5)
        # - Raw overlap captures exact orthographic surface (weight 0.3)
        # - Anchor overlap confirms contextual environment (weight 0.2)
        score_norm = len(norm_overlap) / total_query_tokens
        score_raw = len(raw_overlap) / total_query_tokens
        score_anchor = (len(anchor_overlap) / total_query_tokens) if q_res.tokens.anchor_tokens else score_norm

        composite = (0.5 * score_norm) + (0.3 * score_raw) + (0.2 * score_anchor)
        composite = min(1.0, max(0.0, composite))

        is_matched = composite >= threshold and len(all_matched) > 0

        return CjkRecallMatchScore(
            query=query,
            target=target_text,
            is_matched=is_matched,
            raw_overlap_count=len(raw_overlap),
            normalized_overlap_count=len(norm_overlap),
            anchor_overlap_count=len(anchor_overlap),
            composite_score=round(composite, 4),
            matched_tokens=tuple(all_matched),
        )
