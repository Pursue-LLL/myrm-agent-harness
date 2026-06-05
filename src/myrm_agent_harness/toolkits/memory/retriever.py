"""Reciprocal Rank Fusion (RRF) retriever for multi-source memory search.


[INPUT]
- memory.config::RetrievalConfig (POS: retrieval configuration)
- memory.signals::SignalCalculator (POS: context signal calculator)
- memory.types::{MemorySearchResult, SemanticMemory} (POS: memory data models)

[OUTPUT]
- MemoryRetriever: RRF retriever with correction-chain suppression, MMR diversity (content + source decay), dual-channel fusion

[POS]
RRF retriever for multi-source memory search. Pipeline: RRF scoring → correction-chain
suppression → MMR diversity reranking (content similarity + source session decay) →
normalization. Supports dual-channel (raw + summary embedding) fusion for ConversationMemory.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.config import RetrievalConfig
from myrm_agent_harness.toolkits.memory.signals import (
    SignalCalculator,
    get_default_half_life,
    get_default_signal_weights,
)
from myrm_agent_harness.toolkits.memory.text_utils import tokenize
from myrm_agent_harness.toolkits.memory.types import MemorySearchResult, SemanticMemory


def _jaccard_similarity(a: frozenset[str], b: frozenset[str]) -> float:
    """Jaccard similarity between two token sets. Returns 0.0 for empty sets."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class MemoryRetriever:
    """Stateless RRF-based result fuser with correction-chain awareness and MMR diversity."""

    def __init__(self, config: RetrievalConfig | None = None) -> None:
        self._config = config or RetrievalConfig()
        self._signal_calc = SignalCalculator()

    def rank(
        self,
        results: list[MemorySearchResult],
        *,
        limit: int = 10,
        query: str = "",
        query_context: object | None = None,
    ) -> list[MemorySearchResult]:
        """Apply geometric mean scoring, correction suppression, and MMR diversity."""
        if not results:
            return []
        query_tokens = tokenize(query)
        scores: dict[str, float] = {}
        items: dict[str, MemorySearchResult] = {}
        for r in results:
            mid = r.id
            scores[mid] = self._boost(r.score, r, query_tokens, query_context)
            items[mid] = r
        self._suppress_corrected(scores, items)
        scores, items = self._mmr_select(scores, items, limit)
        return self._normalise(scores, items, limit)

    def fuse(
        self,
        result_lists: list[list[MemorySearchResult]],
        *,
        limit: int = 10,
        query: str = "",
        query_context: object | None = None,
    ) -> list[MemorySearchResult]:
        """Fuse multiple result lists using RRF, correction suppression, and MMR diversity.

        Supports dual-channel fusion for ConversationMemory:
        - Raw channel (raw_embedding): high precision for exact wording
        - Summary channel (summary_embedding): broad coverage for semantic meaning
        - Channel weights applied via type_weights configuration
        """
        scores: dict[str, float] = {}
        items: dict[str, MemorySearchResult] = {}
        k = self._config.rrf_k
        query_tokens = tokenize(query)

        for results in result_lists:
            for rank_idx, r in enumerate(results):
                mid = r.id
                rrf = 1.0 / (k + rank_idx + 1)
                type_w = self._config.type_weights.get(r.memory_type, 1.0)
                boosted = self._boost(rrf * type_w, r, query_tokens, query_context)
                scores[mid] = scores.get(mid, 0.0) + boosted
                if mid not in items:
                    items[mid] = r

        self._suppress_corrected(scores, items)
        scores, items = self._mmr_select(scores, items, limit)
        return self._normalise(scores, items, limit)

    def _mmr_select(
        self, scores: dict[str, float], items: dict[str, MemorySearchResult], limit: int
    ) -> tuple[dict[str, float], dict[str, MemorySearchResult]]:
        """Select diverse results using Maximal Marginal Relevance with source decay.

        MMR(d) = λ * relevance(d) - (1-λ) * (content_sim + β * source_overlap)

        Uses Jaccard text similarity as the inter-document similarity measure.
        Source decay penalizes results from sessions already represented in the
        selected set, promoting cross-session diversity without hard cutoffs.

        When λ=1.0, degrades to pure relevance ranking (no-op).
        When source_diversity_weight=0, degrades to standard content-only MMR.

        Returns:
            Filtered (scores, items) containing only the selected documents.
        """
        lam = self._config.mmr_lambda
        if lam >= 1.0 or len(scores) <= limit:
            return scores, items

        max_score = max(scores.values()) if scores else 1.0
        if max_score <= 0:
            return scores, items
        norm_scores = {mid: s / max_score for mid, s in scores.items()}

        token_sets: dict[str, frozenset[str]] = {mid: tokenize(items[mid].content) for mid in scores}

        remaining = set(scores.keys())
        selected: list[str] = []
        selected_tokens: list[frozenset[str]] = []
        source_counts: dict[str | None, int] = {}
        source_weight = self._config.source_diversity_weight

        for selected_count in range(min(limit, len(scores))):
            best_id = ""
            best_mmr = -1.0

            for mid in remaining:
                relevance = norm_scores[mid]
                if selected_tokens:
                    max_sim = max(_jaccard_similarity(token_sets[mid], st) for st in selected_tokens)
                else:
                    max_sim = 0.0

                source_penalty = 0.0
                if source_weight > 0 and selected_count > 0:
                    source_id = getattr(items[mid].memory, "source_chat_id", None)
                    if source_id:
                        source_penalty = source_weight * (source_counts.get(source_id, 0) / selected_count)

                penalty = max_sim + source_penalty
                mmr = lam * relevance - (1.0 - lam) * penalty
                if mmr > best_mmr:
                    best_mmr = mmr
                    best_id = mid

            if not best_id:
                break

            selected.append(best_id)
            selected_tokens.append(token_sets[best_id])
            best_source = getattr(items[best_id].memory, "source_chat_id", None)
            if best_source:
                source_counts[best_source] = source_counts.get(best_source, 0) + 1
            remaining.discard(best_id)

        selected_set = set(selected)
        return ({mid: scores[mid] for mid in selected_set}, {mid: items[mid] for mid in selected_set})

    def _normalise(
        self, scores: dict[str, float], items: dict[str, MemorySearchResult], limit: int
    ) -> list[MemorySearchResult]:
        """Normalize scores to [0, 1] range and return top-k results."""
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:limit]
        if not ranked:
            return []
        max_score = max(ranked[0][1], 1e-9)
        return [
            MemorySearchResult(
                memory=items[mid].memory, score=min(score / max_score, 1.0), memory_type=items[mid].memory_type
            )
            for mid, score in ranked
        ]

    def _suppress_corrected(self, scores: dict[str, float], items: dict[str, MemorySearchResult]) -> None:
        """Demote memories that have been superseded by a correction."""
        corrected_ids: set[str] = set()
        for r in items.values():
            mem = r.memory
            if isinstance(mem, SemanticMemory) and mem.correction_of and mem.correction_of in scores:
                corrected_ids.add(mem.correction_of)
        for cid in corrected_ids:
            scores[cid] *= self._config.correction_penalty

    def _boost(
        self, base: float, result: MemorySearchResult, query_tokens: frozenset[str], query_context: object | None = None
    ) -> float:
        """Apply context-aware scoring boost with hybrid enhancements.

        Enhancements:
        - Geometric scoring (recency/frequency/importance/preference/confidence)
        - Keyword overlap boost
        - Temporal proximity boost
        - Quoted phrase boost (if QueryContext provided)
        - Person name boost (if QueryContext provided)
        """
        geometric = self._geometric_score(base, result)
        keyword_boost = self._keyword_overlap_boost(result, query_tokens)
        temporal_boost = self._temporal_proximity_boost(result)
        pattern_boost = self._pattern_matching_boost(result, query_context) if query_context else 0.0
        return geometric * (1.0 + keyword_boost + temporal_boost + pattern_boost)

    def _geometric_score(self, semantic_score: float, result: MemorySearchResult) -> float:
        """Weighted geometric mean scoring with type-aware signal fusion.

        Formula: final = semantic^w0 * recency^w1 * frequency^w2 * importance^w3 * preference^w4 * confidence
        where Σwᵢ = 1 and weights are type-specific.

        Args:
            semantic_score: Base semantic similarity from RRF
            result: Memory search result with metadata

        Returns:
            Final score modulated by context signals
        """
        if semantic_score <= 0:
            return 0.0

        mem = result.memory
        mem_type = result.memory_type
        weights = get_default_signal_weights(mem_type)
        half_life = get_default_half_life(mem_type)

        recency = self._signal_calc.recency_factor(mem, half_life)
        frequency = self._signal_calc.frequency_factor(mem, self._config.frequency_saturation)
        importance = self._signal_calc.importance_factor(mem)
        preference = self._signal_calc.preference_factor(mem)
        confidence = self._signal_calc.confidence_factor(mem)
        rating = self._signal_calc.rating_factor(mem)

        floor = 0.01
        has_preference_weight = weights.get("preference", 0.0) > 0
        has_rating_weight = weights.get("rating", 0.0) > 0
        signals = {
            "semantic": semantic_score,
            "recency": max(floor, recency),
            "frequency": max(floor, frequency),
            "importance": max(floor, importance),
            "preference": max(floor, preference) if has_preference_weight else 1.0,
            "rating": max(floor, rating) if has_rating_weight else 1.0,
        }

        weighted_product = 1.0
        for signal_name, signal_value in signals.items():
            weight = weights.get(signal_name, 0.0)
            if weight > 0:
                weighted_product *= signal_value**weight

        return weighted_product * confidence

    def _keyword_overlap_boost(self, result: MemorySearchResult, query_tokens: frozenset[str]) -> float:
        """Calculate keyword overlap boost (MemPalace hybrid enhancement).

        Formula: boost = keyword_weight × (overlap_ratio)
        where overlap_ratio = |query_tokens ∩ content_tokens| / |query_tokens|

        Returns:
            Boost factor in [0, keyword_weight]
        """
        if not query_tokens or self._config.keyword_overlap_weight <= 0:
            return 0.0

        content_tokens = tokenize(result.content)
        if not content_tokens:
            return 0.0

        overlap_count = len(query_tokens & content_tokens)
        if overlap_count < self._config.keyword_overlap_min_tokens:
            return 0.0

        overlap_ratio = overlap_count / len(query_tokens)
        return self._config.keyword_overlap_weight * overlap_ratio

    def _temporal_proximity_boost(self, result: MemorySearchResult) -> float:
        """Calculate temporal proximity boost (MemPalace hybrid enhancement).

        Boosts memories created recently (within threshold_hours).

        Returns:
            Boost factor in [0, temporal_boost_weight]
        """
        if self._config.temporal_boost_weight <= 0:
            return 0.0

        proximity = self._signal_calc.temporal_proximity_factor(
            result.memory, threshold_hours=self._config.temporal_boost_threshold_hours
        )
        return self._config.temporal_boost_weight * proximity

    def _pattern_matching_boost(self, result: MemorySearchResult, query_context: object) -> float:
        """Calculate pattern matching boost (quoted phrases, person names, temporal reference).

        Args:
            result: Memory search result
            query_context: QueryContext from query_analyzer (optional)

        Returns:
            Boost factor based on pattern matches
        """
        try:
            from myrm_agent_harness.toolkits.memory.query_analyzer import (
                QueryContext,
                contains_person_name,
                contains_quoted_phrase,
            )

            if not isinstance(query_context, QueryContext):
                return 0.0

            content = result.content
            boost = 0.0

            for phrase in query_context.quoted_phrases:
                if contains_quoted_phrase(content, phrase):
                    boost += self._config.quoted_phrase_boost

            for name in query_context.person_names:
                if contains_person_name(content, name):
                    boost += self._config.person_name_boost

            if query_context.reference_time and result.memory.created_at:
                from datetime import UTC

                memory_time = result.memory.created_at
                if memory_time.tzinfo is None:
                    memory_time = memory_time.replace(tzinfo=UTC)
                days_diff = abs((memory_time - query_context.reference_time).total_seconds()) / 86400
                if days_diff <= 1.0:
                    boost += self._config.temporal_boost_weight
                elif days_diff <= 7.0:
                    boost += self._config.temporal_boost_weight * 0.5
                elif days_diff <= 30.0:
                    boost += self._config.temporal_boost_weight * 0.2

            return boost
        except (ImportError, TypeError):
            return 0.0
