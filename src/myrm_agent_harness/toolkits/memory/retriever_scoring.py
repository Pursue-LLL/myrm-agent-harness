"""Context-aware scoring signals for MemoryRetriever.

[INPUT]
- memory.config::RetrievalConfig (POS: retrieval configuration)
- memory.signals::{SignalCalculator, get_default_half_life, get_default_signal_weights} (POS: context signal
  calculator and per-type priors)
- memory.text_utils::tokenize (POS: query/content tokenization)
- memory.types::MemorySearchResult (POS: memory data models)

[OUTPUT]
- RetrievalScoringMixin: Geometric signal fusion plus keyword, temporal and pattern boosts applied to a candidate

[POS]
Scoring half of the retriever: turns a base relevance score and a candidate's context signals into the final
score. Mixed into MemoryRetriever, which owns the configuration and the signal calculator.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.config import RetrievalConfig
from myrm_agent_harness.toolkits.memory.signals import (
    SignalCalculator,
    get_default_half_life,
    get_default_signal_weights,
)
from myrm_agent_harness.toolkits.memory.text_utils import tokenize
from myrm_agent_harness.toolkits.memory.types import MemorySearchResult


class RetrievalScoringMixin:
    """Per-candidate scoring shared by the rank and fuse pipelines."""

    _config: RetrievalConfig
    _signal_calc: SignalCalculator

    def _boost(
        self,
        base: float,
        result: MemorySearchResult,
        query_tokens: frozenset[str],
        query_context: object | None = None,
        raw_query: str = "",
    ) -> float:
        """Apply context-aware scoring boost with hybrid enhancements.

        Enhancements:
        - Geometric scoring (recency/frequency/importance/preference/confidence)
        - Keyword overlap boost
        - Temporal proximity boost
        """
        mem = result.memory
        if getattr(mem, "is_exact_fact", False) and getattr(mem, "exact_identifiers", None):
            q_lower = raw_query.lower()
            for ident in mem.exact_identifiers:
                ident_lower = ident.lower()
                if ident_lower in query_tokens or (q_lower and ident_lower in q_lower):
                    return 1.0

        geometric = self._geometric_score(base, result)
        keyword_boost = self._keyword_overlap_boost(result, query_tokens)
        temporal_boost = self._temporal_proximity_boost(result)
        pattern_boost = self._pattern_matching_boost(result, query_context) if query_context else 0.0
        # Clamp to the documented [0, 1] contract: the RRF base is already normalised to
        # 1.0, so a zero boost plus float rounding (e.g. 1.0000000045) would otherwise
        # violate ``MemorySearchResult.score`` and abort the entire retrieval stream.
        return min(1.0, geometric * (1.0 + keyword_boost + temporal_boost + pattern_boost))

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
        if self._config.dynamic_signal_weights:
            # Preserve type-specific zero priors (e.g. PROCEDURAL recency=0) and scale active priors
            modulated: dict[str, float] = {}
            for k, base_w in weights.items():
                if base_w <= 0.0:
                    modulated[k] = 0.0
                else:
                    multiplier = self._config.dynamic_signal_weights.get(k, 1.0)
                    modulated[k] = base_w * max(0.01, multiplier)

            total_w = sum(modulated.values())
            if total_w > 0.0:
                weights = {k: w / total_w for k, w in modulated.items()}
            else:
                weights = modulated

        if self._config.enable_gravity_decay:
            recency = self._signal_calc.gravity_decay_factor(
                mem,
                gravity=self._config.gravity_power,
                time_scale_hours=self._config.gravity_time_scale_hours,
            )
        else:
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

        Formula: boost = keyword_weight * (overlap_ratio)
        where overlap_ratio = |query_tokens & content_tokens| / |query_tokens|

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
