"""IDF-aware BM25 query term selection.

[INPUT]
- tokens: list[str] (tokenized query terms)
- idf_map: Mapping[str, float] | None (mapping from term to BM25 IDF value)
- doc_count: int | None (total documents in index for cold-start determination)
- max_terms: int (maximum terms to retain, default 16)
- min_corpus_docs: int (threshold before applying skewed IDF ranking, default 5)
- protect_leading_terms: int (number of leading tokens preserved for intent, default 2)

[OUTPUT]
- select_selective_bm25_tokens: Returns list[str] of filtered query terms in original relative order

[POS]
Retriever BM25 词项选择优化层。针对超长检索词，基于语料库反文档频率（IDF）自适应筛选高判别度词项，
并提供首部意图词免淘汰保护与小语料冷启动降级，防止评分稀释和高频噪声。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

logger = logging.getLogger(__name__)

DEFAULT_MAX_QUERY_TERMS = 16


def select_selective_bm25_tokens(
    tokens: list[str],
    idf_map: Mapping[str, float] | None,
    doc_count: int | None = None,
    max_terms: int = DEFAULT_MAX_QUERY_TERMS,
    min_corpus_docs: int = 5,
    protect_leading_terms: int = 2,
) -> list[str]:
    """Select the most informative Top-N tokens from a query based on IDF.

    For short queries (length <= max_terms), all tokens are preserved without alteration.
    For long queries:
    1. Leading tokens (up to ``protect_leading_terms``) are preserved to retain intent/actions.
    2. Remaining positions are prioritized by inverse document frequency (IDF).
    3. Tokens absent from the corpus (OOV) are deprioritized below in-corpus terms to prevent
       spelling typos from starving discriminative indexed keywords.
    4. Selected tokens are returned preserving their original relative order.

    Args:
        tokens: Tokenized words/subwords from the query.
        idf_map: Term-to-IDF dictionary (e.g. from BM25Okapi.idf).
        doc_count: Total document count in corpus. When below ``min_corpus_docs``,
            statistically skewed IDF sorting is bypassed in favor of head truncation.
        max_terms: Maximum number of terms to retain. Must be > 0.
        min_corpus_docs: Minimum corpus document threshold for IDF ranking.
        protect_leading_terms: Number of initial query tokens to unconditionally retain.

    Returns:
        Filtered list of tokens in original relative order.
    """
    if not tokens or len(tokens) <= max_terms or max_terms <= 0:
        return tokens

    if not idf_map:
        return tokens[:max_terms]

    if doc_count is not None and doc_count < min_corpus_docs:
        return tokens[:max_terms]

    # Reserve head tokens for query intent protection
    head_count = min(max(0, protect_leading_terms), max_terms, len(tokens))
    selected_indices: set[int] = set(range(head_count))
    remaining_quota = max_terms - head_count

    if remaining_quota > 0:
        # Candidate pool for remaining slots
        unseen_default_idf = -1.0
        candidate_tokens: list[tuple[int, str, float]] = []
        for idx in range(head_count, len(tokens)):
            token = tokens[idx]
            score = idf_map.get(token, unseen_default_idf)
            candidate_tokens.append((idx, token, score))

        # Sort descending by IDF score, breaking ties by earlier original position
        candidate_tokens.sort(key=lambda item: (-item[2], item[0]))

        for item in candidate_tokens[:remaining_quota]:
            selected_indices.add(item[0])

    # Re-sort all selected tokens by original index to preserve natural word order
    result = [tokens[i] for i in sorted(selected_indices)]
    logger.debug(
        "IDF-aware term selection: compressed %d tokens to %d tokens (head_protected=%d)",
        len(tokens),
        len(result),
        head_count,
    )
    return result
