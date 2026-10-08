"""Dual-strategy Porter and Trigram matcher with Reciprocal Rank Fusion (RRF) ranking.

[INPUT]
- EphemeralFts5Config, SearchQueryItem, SearchResultChunk: Domain definitions.
- EphemeralSqliteFts5Vault: Dual FTS5 virtual table engine.

[OUTPUT]
- DualStrategyRrfRetriever: Fused ranking engine resolving precise terms and substring queries.

[POS]
Retrieval and rank fusion layer for ephemeral session FTS5 vault.
"""

from __future__ import annotations

from typing import Sequence

from .ephemeral_fts5_types import EphemeralFts5Config, SearchQueryItem, SearchResultChunk
from .ephemeral_sqlite_fts5_vault import EphemeralSqliteFts5Vault


class DualStrategyRrfRetriever:
    """Executes parallel Porter and Trigram FTS5 queries and merges them using Reciprocal Rank Fusion."""

    def __init__(
        self,
        vault: EphemeralSqliteFts5Vault,
        config: EphemeralFts5Config | None = None,
    ) -> None:
        self._vault = vault
        self._config = config or EphemeralFts5Config()

    def search(
        self,
        query: str | SearchQueryItem,
    ) -> Sequence[SearchResultChunk]:
        """Runs dual searches, aggregates rank positions, and computes RRF scores."""
        item = query if isinstance(query, SearchQueryItem) else SearchQueryItem(query_text=query)
        q_text = item.query_text.strip()
        if not q_text:
            return ()

        # 1. Fetch raw candidate ranks from dual tables
        porter_hits = self._vault.search_porter_raw(q_text, limit=60)
        trigram_hits = self._vault.search_trigram_raw(q_text, limit=60)

        if not porter_hits and not trigram_hits:
            return ()

        porter_ranks: dict[str, int] = {cid: rank for cid, rank in porter_hits}
        trigram_ranks: dict[str, int] = {cid: rank for cid, rank in trigram_hits}

        all_candidate_ids = set(porter_ranks.keys()).union(trigram_ranks.keys())
        chunks_map = self._vault.get_chunk_metadata_batch(tuple(all_candidate_ids))

        # 2. Compute RRF Scores
        k = self._config.rrf_k_constant
        scored_results: list[SearchResultChunk] = []

        q_lower = q_text.lower()

        for cid in all_candidate_ids:
            chunk = chunks_map.get(cid)
            if not chunk:
                continue

            p_rank = porter_ranks.get(cid)
            t_rank = trigram_ranks.get(cid)

            # Base RRF score: 1 / (k + rank)
            rrf = 0.0
            if p_rank is not None:
                rrf += 1.0 / (k + p_rank)
            if t_rank is not None:
                rrf += 1.0 / (k + t_rank)

            # 3. Code block and exact phrase proximity boosting
            multiplier = 1.0
            if chunk.has_code_block and item.boost_code_blocks:
                multiplier *= self._config.code_block_weight

            # Substring proximity bonus if full query is contained in heading or text
            if q_lower in chunk.heading_path.lower() or q_lower in chunk.content.lower():
                multiplier *= 1.2

            final_score = rrf * multiplier

            scored_results.append(
                SearchResultChunk(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    heading_path=chunk.heading_path,
                    content=chunk.content,
                    has_code_block=chunk.has_code_block,
                    porter_rank=p_rank,
                    trigram_rank=t_rank,
                    rrf_score=round(final_score, 6),
                    token_estimate=chunk.token_estimate,
                )
            )

        # 4. Sort descending by RRF score and slice top_k
        scored_results.sort(key=lambda x: x.rrf_score, reverse=True)
        return tuple(scored_results[: item.top_k])
