"""Fusion strategy module.

Provides multi-query result fusion algorithms (RRF, etc.).

[INPUT]
(no external module dependencies)

[OUTPUT]
rrf_fusion: Reciprocal Rank Fusion algorithm for merging ranked result lists

[POS]
Score-fusion utilities for hybrid retrieval. Merges multiple ranked lists into a single
ranking using rank-based (not score-based) fusion.

"""

import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


def rrf_fusion(
    query_results: list[list[tuple[int, float]]],
    k: int = 60,
    top_k: int | None = None,
) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion — merges multiple query results into a single ranking.

    A concise and efficient multi-query fusion strategy based on rank positions
    rather than absolute scores.

    Formula:
        RRF(doc) = Σ(1 / (k + rank_i + 1))

    Where:
        - k: Constant parameter (typically 60), controls rank decay speed
        - rank_i: Document rank in the i-th query result (0-based)

    Characteristics:
        - More sensitive to rank positions than absolute scores
        - Does not perform any filtering — caller is responsible
        - Widely validated in practice

    Note:
        - This function does not filter zero/negative scores (single responsibility)
        - If filtering is needed, the caller should handle it before passing results in

    Args:
        query_results: Retrieval results per query, formatted as [(doc_idx, score), ...]
        k: RRF parameter controlling rank decay speed (default 60)
        top_k: Number of top results to return (None returns all)

    Returns:
        Fused result list [(doc_idx, rrf_score), ...] sorted by score descending

    Examples:
        >>> results = [
        ...     [(0, 0.9), (1, 0.5)],  # query1 results
        ...     [(1, 0.8), (0, 0.6)],  # query2 results
        ... ]
        >>> fused = rrf_fusion(results, k=60)

        >>> # Filter zero scores before passing in
        >>> filtered_results = [
        ...     [(idx, score) for idx, score in r if score > 0]
        ...     for r in results
        ... ]
        >>> fused = rrf_fusion(filtered_results, k=60)
    """
    rrf_scores = defaultdict(float)

    for results in query_results:
        for rank, (doc_idx, _) in enumerate(results):
            rrf_scores[doc_idx] += 1.0 / (k + rank + 1)

    sorted_results = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)

    logger.debug(f"RRF fusion: {len(query_results)} queries -> {len(rrf_scores)} unique docs, selecting top_{top_k}")

    return sorted_results[:top_k] if top_k is not None else sorted_results


def unified_fusion(
    query_results: dict[str, list[tuple[int, float]]],
    k: int = 60,
    w1: float = 0.6,  # absolute score weight (quality)
    w2: float = 0.1,  # relative score weight (advantage)
    w3: float = 0.2,  # consensus score weight (consensus)
    w4: float = 0.1,  # pure rank score weight (prestige)
    rerank_score_threshold: float = 0.4,  # rerank score threshold
    fusion_score_threshold: float = 0.0,  # fusion score threshold
) -> list[tuple[int, float]]:
    """Four-pillar orthogonal fusion: an advanced fusion strategy with separated concerns.

    Fuses reranked results from different queries using four orthogonal pillars.

    Core idea:
    Each pillar has an independent, clear, non-overlapping responsibility,
    achieving fully orthogonal signal fusion.

    Four orthogonal pillars:
    1. Absolute Score (S_Absolute) — measures "quality": model's highest confidence in relevance
    2. Relative Score (S_Relative) — measures "advantage": avg margin of lead within each list
    3. Consensus Score (S_Consensus) — measures "consensus": fraction of queries that found this doc
    4. Pure Rank Score (S_Rank_Pure) — measures "prestige": average rank quality across queries

    Algorithm steps:
    1. S_Absolute(doc) = Max(raw_score_i) — highest raw score
    2. S_Relative(doc) = Avg(normalized_score_i) — mean of min-max normalized scores
    3. S_Consensus(doc) = appearance_count / total_queries — frequency of appearance
    4. S_Rank_Pure(doc) = Avg(1/(k + rank_i)) — mean reciprocal rank
    5. FinalScore = w1*S_Absolute + w2*S_Relative + w3*S_Consensus + w4*S_Rank_Pure

    Weight design philosophy (orthogonal control):
    - w1 (quality): 0.4-0.6 — how much do you trust the model's raw scores?
    - w2 (advantage): 0.05-0.2 — how much to reward runaway leaders?
    - w3 (consensus): 0.1-0.3 — how much to reward docs found by multiple queries?
    - w4 (prestige): 0.1-0.3 — how much to reward higher-ranked docs?

    Tuning tips:
    - Want dark horses? → increase w2  |  Want coverage? → increase w3  |  Want top hits? → increase w4

    Applicable scenarios:
    - Prevents a 0.5-score runaway leader from dominating a 0.95-score cluster champion
    - Balancing quality and consensus in multi-query variant retrieval
    - Scenarios requiring both absolute quality and relative advantage

    Args:
        query_results: Retrieval results per query {query: [(doc_idx, score), ...]}
        k: RRF parameter controlling rank decay speed, typically 60
        w1: Quality weight controlling rerank score influence, recommended 0.5
        w2: Advantage weight controlling margin-leader influence, recommended 0.1
        w3: Consensus weight controlling multi-query agreement influence, recommended 0.2
        w4: Prestige weight controlling average rank quality influence, recommended 0.2
        rerank_score_threshold: Filters out docs with rerank scores below this value
        fusion_score_threshold: Filters out docs with fusion scores below this value

    Returns:
        Document list sorted by final score descending [(doc_idx, final_score), ...]
    """
    # Step 0: Input validation and preprocessing
    if abs(w1 + w2 + w3 + w4 - 1.0) > 1e-6:
        raise ValueError(f"Weights must sum to 1.0, got: w1={w1}, w2={w2}, w3={w3}, w4={w4}, sum={w1 + w2 + w3 + w4}")

    # Remove queries with empty results to avoid min()/max() on empty lists,
    # ensure accurate consensus computation, and skip pointless iteration
    valid_query_results = {query: results for query, results in query_results.items() if results}

    if not valid_query_results:
        return []

    # Step 1: Initialize data structures
    all_docs = set()

    # Short-circuit: only compute dimensions with non-zero weights
    need_relative = w2 > 0
    need_consensus = w3 > 0
    need_rank = w4 > 0

    absolute_scores = defaultdict(float)
    relative_scores = defaultdict(float) if need_relative else {}
    rank_scores = defaultdict(float) if need_rank else {}
    appearance_counts = defaultdict(int)

    # Step 2: First pass — compute normalization parameters (only when relative scores needed)
    #
    # Two passes are required because computing relative scores needs min-max normalization
    # per query, which requires knowing the full score range before accumulation.
    # Normalization eliminates scale differences between queries, mapping all scores to [0, 1].
    normalized_query_results: dict[str, list[tuple[int, float]]] = {}

    for query, results in valid_query_results.items():
        for doc_idx, _ in results:
            all_docs.add(doc_idx)

        if need_relative:
            scores = [score for _, score in results]

            if len(scores) == 1:
                normalized_query_results[query] = [(results[0][0], 1.0)]
            else:
                min_score = min(scores)
                max_score = max(scores)
                score_range = max_score - min_score

                if score_range > 0:
                    normalized_results = [(doc_idx, (score - min_score) / score_range) for doc_idx, score in results]
                else:
                    # All scores identical — treat as equally important
                    normalized_results = [(doc_idx, 1.0) for doc_idx, _ in results]

                normalized_query_results[query] = normalized_results

    # Step 3: Second pass — accumulate four pillar scores
    for query, results in valid_query_results.items():
        for rank, (doc_idx, original_score) in enumerate(results):
            # Pillar 1: Absolute score — max raw score across all queries
            absolute_scores[doc_idx] = max(absolute_scores[doc_idx], original_score)

            # Pillar 4: Rank score — RRF formula: 1/(k + rank + 1)
            if need_rank:
                rank_scores[doc_idx] += 1.0 / (k + rank + 1)

            # Pillar 2: Relative score — accumulated normalized score
            if need_relative:
                normalized_score = normalized_query_results[query][rank][1]
                relative_scores[doc_idx] += normalized_score

            appearance_counts[doc_idx] += 1

    # Step 4: Final fusion — average + weighted combination (merged loop)
    total_queries = len(valid_query_results)
    final_scores = {}

    for doc_idx in all_docs:
        count = appearance_counts[doc_idx]

        if count > 0:
            # FinalScore = w1*S_Absolute + w2*S_Relative + w3*S_Consensus + w4*S_Rank_Pure
            final_score = w1 * absolute_scores[doc_idx]

            if need_relative:
                avg_relative_score = relative_scores[doc_idx] / count
                final_score += w2 * avg_relative_score

            if need_consensus:
                consensus_score = count / total_queries
                final_score += w3 * consensus_score

            if need_rank:
                avg_rank_score = rank_scores[doc_idx] / count
                final_score += w4 * avg_rank_score

            final_scores[doc_idx] = final_score

    # Step 5: Two-stage quality filtering
    # Stage 1: Rerank score filter (quality gate)
    rerank_filtered_scores = {
        doc_idx: score for doc_idx, score in final_scores.items() if absolute_scores[doc_idx] >= rerank_score_threshold
    }
    rerank_filtered_count = len(final_scores) - len(rerank_filtered_scores)

    # Stage 2: Fusion score filter (relevance gate)
    filtered_final_scores = {
        doc_idx: score for doc_idx, score in rerank_filtered_scores.items() if score >= fusion_score_threshold
    }
    fusion_filtered_count = len(rerank_filtered_scores) - len(filtered_final_scores)

    # Step 6: Sort by fusion score descending
    sorted_results = sorted(filtered_final_scores.items(), key=lambda x: x[1], reverse=True)

    # Step 7: Logging
    log_parts = [f"Orthogonal fusion: {total_queries} queries, {len(all_docs)} unique docs"]
    if rerank_filtered_count > 0:
        log_parts.append(f"rerank filter: removed {rerank_filtered_count} docs (threshold={rerank_score_threshold})")
    if fusion_filtered_count > 0:
        log_parts.append(f"fusion filter: removed {fusion_filtered_count} docs (threshold={fusion_score_threshold})")
    log_parts.append(
        f"weights: w1={w1:.2f}(quality), w2={w2:.2f}(advantage), w3={w3:.2f}(consensus), w4={w4:.2f}(prestige)"
    )
    logger.debug(" | ".join(log_parts))

    return sorted_results
