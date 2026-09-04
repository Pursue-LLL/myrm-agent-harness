"""IDF-aware BM25 query term selection.

Selects the most discriminative (highest inverse document frequency / rarest)
terms from long search queries to prevent score dilution and high-frequency noise.

[INPUT]
tokens: list[str] (tokenized query terms)
idf_map: dict[str, float] | None (mapping from term to BM25 IDF value)
max_terms: int (maximum terms to retain, default 16)

[OUTPUT]
select_selective_bm25_tokens: Returns list[str] of filtered query terms in original relative order
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

logger = logging.getLogger(__name__)

DEFAULT_MAX_QUERY_TERMS = 16


def select_selective_bm25_tokens(
    tokens: list[str],
    idf_map: Mapping[str, float] | None,
    max_terms: int = DEFAULT_MAX_QUERY_TERMS,
) -> list[str]:
    """Select the most informative Top-N tokens from a query based on IDF.

    For short queries (length <= max_terms), all tokens are preserved without alteration.
    For long queries, terms with the highest IDF (or unseen terms with high specificity)
    are prioritized, while high-frequency terms appearing across most documents are pruned.
    The selected tokens maintain their original relative order.

    Args:
        tokens: Tokenized words/subwords from the query.
        idf_map: Term-to-IDF dictionary (e.g. from BM25Okapi.idf).
        max_terms: Maximum number of terms to retain. Must be > 0.

    Returns:
        Filtered list of tokens in original relative order.
    """
    if not tokens or len(tokens) <= max_terms or max_terms <= 0:
        return tokens

    if not idf_map:
        return tokens[:max_terms]

    # Calculate default IDF for unseen terms: highest observed IDF + 0.1
    # This guarantees that unique/novel identifiers or symbols in query are prioritized.
    max_observed_idf = max(idf_map.values()) if idf_map else 1.0
    unseen_default_idf = max_observed_idf + 0.1

    # Pair each token with its original index and scored IDF
    scored_tokens: list[tuple[int, str, float]] = []
    for idx, token in enumerate(tokens):
        # Unseen terms get highest priority (unseen_default_idf)
        score = idf_map.get(token, unseen_default_idf)
        scored_tokens.append((idx, token, score))

    # Sort descending by IDF score, breaking ties by earlier original position
    scored_tokens.sort(key=lambda item: (-item[2], item[0]))

    # Pick top-N highest IDF tokens
    selected = scored_tokens[:max_terms]

    # Re-sort selected items by original index to preserve natural word order
    selected.sort(key=lambda item: item[0])

    result = [item[1] for item in selected]
    logger.debug(
        "IDF-aware term selection: compressed %d tokens to %d tokens (pruned low-IDF noise)",
        len(tokens),
        len(result),
    )
    return result
