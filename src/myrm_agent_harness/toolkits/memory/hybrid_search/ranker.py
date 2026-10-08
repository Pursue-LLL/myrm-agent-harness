"""Ranking, normalization, recency decay, and diversity algorithms.

[POS]
Lexical sanitization, BM25 score normalization, half-life recency decay,
Maximal Marginal Relevance (MMR) reordering, and token budget enforcement.

[INPUT]
- datetime.UTC, datetime.datetime
- re, math
- .models.HybridSearchHit

[OUTPUT]
- sanitize_fts_query
- bm25_to_score
- compute_recency_decay
- apply_mmr
- apply_token_budget
"""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.hybrid_search.models import HybridSearchHit

_TOKEN_PATTERN = re.compile(r"[\w]+", re.UNICODE)


def sanitize_fts_query(raw_query: str) -> str | None:
    """Sanitize raw user query into safe FTS5 boolean matching terms.

    Extracts alphanumeric tokens and joins them with AND syntax to avoid
    sqlite3.OperationalError syntax exceptions caused by rogue operators.
    """
    if not raw_query or not raw_query.strip():
        return None

    tokens = _TOKEN_PATTERN.findall(raw_query.strip())
    if not tokens:
        return None

    # Enclose each word in quotes to neutralize SQLite FTS5 reserved keywords
    sanitized_parts = [f'"{token}"' for token in tokens if token]
    return " AND ".join(sanitized_parts) if sanitized_parts else None


def bm25_to_score(rank: float) -> float:
    """Normalize SQLite FTS5 BM25 rank value into [0.0, 1.0] confidence score.

    SQLite FTS5 yields negative numbers for higher relevance (lower is better).
    Transforms rank monotonically into standard normalized similarity range.
    """
    if not math.isfinite(rank):
        return 0.001

    if rank < 0.0:
        relevance = -rank
        return relevance / (1.0 + relevance)
    return 1.0 / (1.0 + rank)


def compute_recency_decay(
    created_at_iso: str,
    half_life_days: float = 30.0,
    now_ts: float | None = None,
) -> float:
    """Calculate exponential recency decay multiplier with lower bound floor.

    Args:
        created_at_iso: ISO 8601 creation timestamp string.
        half_life_days: Half-life period in days where score drops to 0.5.
        now_ts: Optional reference POSIX timestamp (defaults to current time).

    Returns:
        Decay factor bounded between [0.15, 1.0].
    """
    if half_life_days <= 0.0 or not created_at_iso:
        return 1.0

    try:
        clean_iso = created_at_iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        item_ts = dt.timestamp()
    except (ValueError, TypeError):
        return 1.0

    current_ts = now_ts if now_ts is not None else datetime.now(UTC).timestamp()
    delta_seconds = max(0.0, current_ts - item_ts)
    delta_days = delta_seconds / 86400.0

    # Exponential decay: 2^(-delta_days / half_life_days)
    decay = math.pow(0.5, delta_days / half_life_days)
    return max(0.15, min(1.0, decay))


def _jaccard_similarity(tokens_a: set[str], tokens_b: set[str]) -> float:
    """Calculate word set Jaccard similarity coefficient."""
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = len(tokens_a.intersection(tokens_b))
    union = len(tokens_a.union(tokens_b))
    return intersection / union if union > 0 else 0.0


def apply_mmr(
    hits: list[HybridSearchHit],
    lambda_param: float = 0.7,
    top_k: int = 5,
) -> list[HybridSearchHit]:
    """Apply Maximal Marginal Relevance to diversify search results.

    Balances query relevance against redundancy with already selected items.
    """
    if len(hits) <= 1 or top_k <= 1:
        return hits[:top_k]

    clamped_lambda = max(0.0, min(1.0, lambda_param))
    if clamped_lambda >= 0.99:
        return hits[:top_k]

    # Pre-tokenize contents for fast similarity comparisons
    tokenized_pool: list[tuple[HybridSearchHit, set[str]]] = []
    for hit in hits[:50]:  # Limit candidate pool to top 50 to maintain <0.2ms latency
        words = set(_TOKEN_PATTERN.findall(hit.content.lower()))
        tokenized_pool.append((hit, words))

    selected: list[HybridSearchHit] = []
    selected_tokens: list[set[str]] = []
    remaining = tokenized_pool[:]

    # Pick the highest scoring item unconditionally first
    if remaining:
        best_first = remaining.pop(0)
        selected.append(best_first[0])
        selected_tokens.append(best_first[1])

    while remaining and len(selected) < top_k:
        best_candidate_idx = -1
        best_mmr_score = -float("inf")

        for idx, (candidate_hit, candidate_tokens) in enumerate(remaining):
            max_sim = 0.0
            for sel_tokens in selected_tokens:
                sim = _jaccard_similarity(candidate_tokens, sel_tokens)
                if sim > max_sim:
                    max_sim = sim

            # MMR = lambda * Relevance - (1 - lambda) * MaxSimilarityToSelected
            mmr_score = clamped_lambda * candidate_hit.score - (1.0 - clamped_lambda) * max_sim
            if mmr_score > best_mmr_score:
                best_mmr_score = mmr_score
                best_candidate_idx = idx

        if best_candidate_idx >= 0:
            chosen = remaining.pop(best_candidate_idx)
            selected.append(chosen[0])
            selected_tokens.append(chosen[1])
        else:
            break

    return selected


def apply_token_budget(
    hits: list[HybridSearchHit],
    max_tokens: int | None = 2000,
    chars_per_token: float = 3.5,
) -> list[HybridSearchHit]:
    """Enforce downstream LLM context token budget, dropping overflow hits."""
    if max_tokens is None or max_tokens <= 0:
        return hits

    retained: list[HybridSearchHit] = []
    accumulated_tokens = 0

    for hit in hits:
        token_est = int(len(hit.content) / chars_per_token) + 1
        if accumulated_tokens + token_est > max_tokens and retained:
            break
        retained.append(hit)
        accumulated_tokens += token_est

    return retained
