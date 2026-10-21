"""Result boosting for memory retrieval (MemPalace enhancement).

Applies multiple boosting strategies to search results based on query patterns:
- Keyword overlap: Boost results containing quoted phrases or important keywords
- Temporal proximity: Boost recent results for time-related queries
- Person name match: Boost results mentioning queried person names
- Quoted phrase match: Boost results containing exact quoted phrases

[I]
- results: List[MemorySearchResult] - search results to boost
- query: str - original query text
- query_context: QueryContext - parsed query patterns
- config: RetrievalConfig - boosting configuration (weights, enable flags)

[O]
- List[MemorySearchResult] - results with adjusted scores, re-sorted

[P]
Combines multiple signal-based boosts using multiplicative scoring.
Each boost type can be independently configured.

[INPUT]
- (none)

[OUTPUT]
- boost_results: Apply multiple boosting strategies to search results.

[POS]
Result boosting for memory retrieval (MemPalace enhancement).
"""

from __future__ import annotations

from datetime import UTC

from myrm_agent_harness.toolkits.memory.config import RetrievalConfig
from myrm_agent_harness.toolkits.memory.query_analyzer import (
    QueryContext,
    contains_person_name,
    contains_quoted_phrase,
)
from myrm_agent_harness.toolkits.memory.types import MemorySearchResult


def boost_results(
    results: list[MemorySearchResult], query: str, query_context: QueryContext, config: RetrievalConfig
) -> list[MemorySearchResult]:
    """Apply multiple boosting strategies to search results.

    Args:
        results: Search results to boost
        query: Original query text
        query_context: Parsed query patterns (quoted phrases, person names, temporal markers)
        config: Retrieval configuration with boost weights

    Returns:
        Results with adjusted scores, re-sorted by score (highest first)

    Boosting strategies applied (if enabled):
    1. Keyword overlap: Match quoted phrases and important keywords
    2. Temporal proximity: Boost recent memories for time-related queries
    3. Person name match: Boost memories mentioning queried person names
    4. Quoted phrase match: Boost memories containing exact quoted text
    5. Preference boost: Boost preference-tagged memories for preference queries
    """
    if not results:
        return results

    from myrm_agent_harness.toolkits.memory.metrics import get_search_metrics

    boosted_results = results[:]
    keyword_boost_count = 0
    temporal_boost_count = 0
    preference_boost_count = 0

    for i, result in enumerate(boosted_results):
        original_score = result.score
        score = original_score
        content = result.content or ""

        if config.enable_keyword_boost:
            new_score = _apply_keyword_boost(score, content, query_context, config)
            if new_score > score:
                keyword_boost_count += 1
            score = new_score

        if config.enable_temporal_boost and query_context.reference_time:
            new_score = _apply_temporal_boost(score, result, query_context, config)
            if new_score > score:
                temporal_boost_count += 1
            score = new_score

        if config.enable_person_name_boost and query_context.person_names:
            score = _apply_person_name_boost(score, content, query_context, config)

        if config.enable_quoted_phrase_boost and query_context.quoted_phrases:
            score = _apply_quoted_phrase_boost(score, content, query_context, config)

        if config.enable_preference_boost and query_context.is_preference_query:
            new_score = _apply_preference_boost(score, result, query_context, config)
            if new_score > score:
                preference_boost_count += 1
            score = new_score

        boosted_results[i] = result.model_copy(update={"score": score})

    boosted_results.sort(key=lambda r: r.score, reverse=True)

    metrics = get_search_metrics()
    metrics.record_keyword_boost(keyword_boost_count)
    metrics.record_temporal_boost(temporal_boost_count)
    metrics.record_preference_boost(preference_boost_count)

    return boosted_results


def _apply_keyword_boost(score: float, content: str, query_context: QueryContext, config: RetrievalConfig) -> float:
    """Apply keyword overlap boost.

    Boost results that contain quoted phrases or important keywords from query.

    MemPalace formula: fused_dist = dist * (1.0 - 0.30 * overlap)
    We use multiplicative boost: score * (1.0 + weight * overlap)
    """
    if not query_context.quoted_phrases:
        return score

    overlap_count = sum(1 for phrase in query_context.quoted_phrases if contains_quoted_phrase(content, phrase))

    if overlap_count == 0:
        return score

    overlap_ratio = min(overlap_count / len(query_context.quoted_phrases), 1.0)
    boost_factor = 1.0 + config.keyword_boost_weight * overlap_ratio
    return score * boost_factor


def _apply_temporal_boost(
    score: float, result: MemorySearchResult, query_context: QueryContext, config: RetrievalConfig
) -> float:
    """Apply temporal proximity boost.

    Boost recent memories for time-related queries.

    MemPalace: up to 40% distance reduction for temporal matches.
    We use multiplicative boost based on time difference.
    """
    if not query_context.reference_time or not result.memory.created_at:
        return score

    memory_time = result.memory.created_at
    reference_time = query_context.reference_time

    if memory_time.tzinfo is None:
        memory_time = memory_time.replace(tzinfo=UTC)

    time_diff = abs((memory_time - reference_time).total_seconds())
    days_diff = time_diff / 86400

    if days_diff <= 1.0:
        boost_factor = 1.0 + config.temporal_boost_weight
    elif days_diff <= 7.0:
        boost_factor = 1.0 + config.temporal_boost_weight * 0.5
    elif days_diff <= 30.0:
        boost_factor = 1.0 + config.temporal_boost_weight * 0.2
    else:
        boost_factor = 1.0

    return score * boost_factor


def _apply_person_name_boost(score: float, content: str, query_context: QueryContext, config: RetrievalConfig) -> float:
    """Apply person name match boost.

    Boost results mentioning queried person names.
    """
    if not query_context.person_names:
        return score

    match_count = sum(1 for name in query_context.person_names if contains_person_name(content, name))

    if match_count == 0:
        return score

    match_ratio = min(match_count / len(query_context.person_names), 1.0)
    boost_factor = 1.0 + config.person_name_boost_weight * match_ratio
    return score * boost_factor


def _apply_quoted_phrase_boost(
    score: float, content: str, query_context: QueryContext, config: RetrievalConfig
) -> float:
    """Apply quoted phrase exact match boost.

    Boost results containing exact quoted phrases from query.
    """
    if not query_context.quoted_phrases:
        return score

    match_count = sum(1 for phrase in query_context.quoted_phrases if contains_quoted_phrase(content, phrase))

    if match_count == 0:
        return score

    match_ratio = min(match_count / len(query_context.quoted_phrases), 1.0)
    boost_factor = 1.0 + config.quoted_phrase_boost_weight * match_ratio
    return score * boost_factor


def _apply_preference_boost(
    score: float, result: MemorySearchResult, query_context: QueryContext, config: RetrievalConfig
) -> float:
    """Apply preference boost for preference-tagged memories.

    Boost semantic memories that have been tagged with preference_type and
    preference_strength when the query is asking about preferences.

    MyrmAgent enhancement: Leverages LLM-extracted preference metadata
    to improve ranking of preference-related memories without synthetic docs.

    Formula: score * (1.0 + preference_strength * preference_boost_weight)

    Args:
        score: Current score
        result: Memory search result
        query_context: Query context (must have is_preference_query=True)
        config: Retrieval config with preference_boost_weight

    Returns:
        Boosted score if memory has preference_strength > 0, else original score
    """
    if not query_context.is_preference_query:
        return score

    memory = result.memory
    if not hasattr(memory, "preference_strength"):
        return score

    pref_strength = getattr(memory, "preference_strength", 0.0)
    if pref_strength <= 0.0:
        return score

    boost_factor = 1.0 + pref_strength * config.preference_boost_weight
    return score * boost_factor
