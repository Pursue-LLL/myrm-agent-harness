"""Result fusion pipeline.

Fuses multi-query reranked results: deduplication → orthogonal fusion → autocut → final top-k.

[INPUT]
- retriever.fusion_strategies::unified_fusion (POS: four-pillar orthogonal fusion algorithm)
- retriever.autocut::AutocutConfig, apply_autocut (POS: score-discontinuity dynamic truncation)

[OUTPUT]
- FusionPipeline: class — Fusion Pipeline

[POS]
Provides FusionPipeline.
"""

from __future__ import annotations

import logging

from langchain_core.documents import Document

from myrm_agent_harness.toolkits.retriever.autocut import AutocutConfig, apply_autocut
from myrm_agent_harness.toolkits.retriever.fusion_strategies import unified_fusion
from myrm_agent_harness.utils.hash_utils import get_document_dedup_hash

logger = logging.getLogger(__name__)


class FusionPipeline:
    """Result fusion pipeline.

    Pipeline stages:
    1. Build global document index (deduplication)
    2. Four-pillar orthogonal fusion (quality, advantage, consensus, prestige)
    3. Score-discontinuity autocut (dynamic truncation based on rerank scores)
    4. Final top-k hard limit
    """

    def __init__(
        self,
        dedup_strategy: str = "content",
        fusion_weights: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0),
        rerank_score_threshold: float = 0.0,
        fusion_score_threshold: float = 0.0,
        autocut_config: AutocutConfig | None = None,
    ):
        """Initialise fusion pipeline.

        Args:
            dedup_strategy: Dedup strategy ("url" | "content").
            fusion_weights: Fusion weights (w1, w2, w3, w4).
            rerank_score_threshold: Minimum rerank score to keep a document.
            fusion_score_threshold: Minimum fusion score to keep a document.
            autocut_config: Score-discontinuity autocut config (None = disabled).
        """
        self.dedup_strategy = dedup_strategy
        self.fusion_weights = fusion_weights
        self.rerank_score_threshold = rerank_score_threshold
        self.fusion_score_threshold = fusion_score_threshold
        self.autocut_config = autocut_config
        self._all_documents: list[Document] = []

    def fuse_query_results(
        self,
        query_results: dict[str, list[tuple[Document, float]]],
        final_top_k: int,
    ) -> list[Document]:
        """Fuse multi-query results through dedup → fusion → autocut → top-k.

        Args:
            query_results: Per-query results {query: [(doc, score), ...]}.
            final_top_k: Maximum number of documents to return.

        Returns:
            Fused document list sorted by final score descending.
        """
        if not query_results:
            return []

        query_indexed_results = self._build_global_index_mapping(query_results)

        doc_rerank_scores: dict[int, float] = {}
        for results in query_indexed_results.values():
            for doc_idx, score in results:
                doc_rerank_scores[doc_idx] = max(doc_rerank_scores.get(doc_idx, 0.0), score)

        w1, w2, w3, w4 = self.fusion_weights
        fused_results = unified_fusion(
            query_indexed_results,
            k=60,
            w1=w1,
            w2=w2,
            w3=w3,
            w4=w4,
            rerank_score_threshold=self.rerank_score_threshold,
            fusion_score_threshold=self.fusion_score_threshold,
        )

        # Autocut: dynamic truncation based on rerank score discontinuity.
        # Operates on the fusion-ordered list but uses rerank scores for gap detection,
        # since cross-encoder scores have the most reliable discontinuity signal.
        if self.autocut_config is not None and self.autocut_config.enabled:
            rerank_scores_ordered = [doc_rerank_scores.get(idx, 0.0) for idx, _ in fused_results]
            decision = apply_autocut(rerank_scores_ordered, self.autocut_config)
            if decision.was_cut:
                fused_results = fused_results[: decision.kept_count]
                logger.info(
                    f"Autocut: {decision.original_count} → {decision.kept_count} results "
                    f"(gap={decision.max_gap:.3f} at index {decision.cut_index})"
                )

        selected_docs = []
        for doc_idx, final_score in fused_results[:final_top_k]:
            if doc_idx < len(self._all_documents):
                doc = self._all_documents[doc_idx]
                doc.metadata["final_score"] = final_score
                doc.metadata["rerank_score"] = doc_rerank_scores.get(doc_idx, 0.0)
                selected_docs.append(doc)

        logger.info(f"Fusion complete: returning {len(selected_docs)} documents")
        return selected_docs

    def _build_global_index_mapping(
        self, query_doc_results: dict[str, list[tuple[Document, float]]]
    ) -> dict[str, list[tuple[int, float]]]:
        """Build a global document index with deduplication.

        Dedup strategies:
        - "url": Dedup by URL (for web page results).
        - "content": Dedup by content hash (for chunk-level results).

        Args:
            query_doc_results: Per-query document results {query: [(doc, score), ...]}.

        Returns:
            Per-query global index results {query: [(global_idx, score), ...]}.
        """
        all_documents: list[Document] = []
        doc_to_global_idx: dict[str, int] = {}
        query_indexed_results: dict[str, list[tuple[int, float]]] = {}

        for query, doc_score_pairs in query_doc_results.items():
            query_global_results: list[tuple[int, float]] = []

            for doc, score in doc_score_pairs:
                doc_key = self._get_dedup_key(doc)

                if doc_key not in doc_to_global_idx:
                    doc_to_global_idx[doc_key] = len(all_documents)
                    all_documents.append(doc)

                global_idx = doc_to_global_idx[doc_key]
                query_global_results.append((global_idx, score))

            query_indexed_results[query] = query_global_results

        logger.info(
            f"Global index mapping: {len(all_documents)} unique documents (strategy: {self.dedup_strategy})"
        )
        self._all_documents = all_documents

        return query_indexed_results

    def _get_dedup_key(self, doc: Document) -> str:
        """Get document dedup key based on configured strategy."""
        if self.dedup_strategy == "url":
            url = doc.metadata.get("url")
            if url:
                return f"url:{url}"

        return f"content:{get_document_dedup_hash(doc)}"
