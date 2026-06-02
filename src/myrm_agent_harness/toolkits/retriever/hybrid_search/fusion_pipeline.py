"""Result融合管道

responsible for多QueryResult 融合、去重 and finalSort。

[INPUT]
- (none)

[OUTPUT]
- FusionPipeline: class — Fusion Pipeline

[POS]
Provides FusionPipeline.
"""

import logging

from langchain_core.documents import Document

from myrm_agent_harness.toolkits.retriever.fusion_strategies import unified_fusion
from myrm_agent_harness.utils.hash_utils import get_document_dedup_hash

logger = logging.getLogger(__name__)


class FusionPipeline:
    """Result融合管道

    职责：
    1. BuildGlobal文档Index（去重）
    2. 融合multipleQuery Result
    3. 应用分数阈ValueFilter
    4. ReturnfinalSort 文档List
    """

    def __init__(
        self,
        dedup_strategy: str = "content",
        fusion_weights: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0),
        rerank_score_threshold: float = 0.0,
        fusion_score_threshold: float = 0.0,
    ):
        """Initialize融合管道

        Args:
            dedup_strategy: 去重Strategy ("url" | "content")
            fusion_weights: 融合权重 (w1, w2, w3, w4)
            rerank_score_threshold: 重Sort分数阈Value
            fusion_score_threshold: 融合分数阈Value
        """
        self.dedup_strategy = dedup_strategy
        self.fusion_weights = fusion_weights
        self.rerank_score_threshold = rerank_score_threshold
        self.fusion_score_threshold = fusion_score_threshold
        self._all_documents: list[Document] = []

    def fuse_query_results(
        self,
        query_results: dict[str, list[tuple[Document, float]]],
        final_top_k: int,
    ) -> list[Document]:
        """融合multipleQuery Result

        Args:
            query_results: EachQuery Result {query: [(doc, score), ...]}
            final_top_k: finalReturnCount

        Returns:
            融合后 文档List
        """
        if not query_results:
            return []

        # 1. BuildGlobalIndex映射（去重）
        query_indexed_results = self._build_global_index_mapping(query_results)

        # 2. SaveEach文档 最高重Sort分数
        doc_rerank_scores = {}
        for results in query_indexed_results.values():
            for doc_idx, score in results:
                doc_rerank_scores[doc_idx] = max(doc_rerank_scores.get(doc_idx, 0.0), score)

        # 3. 统一融合算法
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

        # 4. Buildfinal文档List
        selected_docs = []
        for doc_idx, final_score in fused_results[:final_top_k]:
            if doc_idx < len(self._all_documents):
                doc = self._all_documents[doc_idx]
                doc.metadata["final_score"] = final_score
                doc.metadata["rerank_score"] = doc_rerank_scores.get(doc_idx, 0.0)
                selected_docs.append(doc)

        logger.warning(f"融合Complete: Return {len(selected_docs)} 个文档")
        return selected_docs

    def _build_global_index_mapping(
        self, query_doc_results: dict[str, list[tuple[Document, float]]]
    ) -> dict[str, list[tuple[int, float]]]:
        """BuildGlobalIndex映射： is 统一融合准备统一 文档Index

        去重Strategy:
        - "url": 以 URL  is 去重Key，适 for Webpage去重
        - "content": 以Content哈希 is 去重Key，适 for ChunkContent去重

        Args:
            query_doc_results: EachQuery 文档Result {query: [(doc, score), ...]}

        Returns:
            Query to GlobalIndexResult 映射 {query: [(global_idx, score), ...]}
        """
        all_documents = []
        doc_to_global_idx = {}
        query_indexed_results = {}

        for query, doc_score_pairs in query_doc_results.items():
            query_global_results = []

            for doc, score in doc_score_pairs:
                doc_key = self._get_dedup_key(doc)

                if doc_key not in doc_to_global_idx:
                    doc_to_global_idx[doc_key] = len(all_documents)
                    all_documents.append(doc)

                global_idx = doc_to_global_idx[doc_key]
                query_global_results.append((global_idx, score))

            query_indexed_results[query] = query_global_results

        logger.warning(f"GlobalIndex映射: {len(all_documents)} 个unique文档 (Strategy: {self.dedup_strategy})")
        self._all_documents = all_documents

        return query_indexed_results

    def _get_dedup_key(self, doc: Document) -> str:
        """ based on StrategyGet文档去重Key

        Args:
            doc: 文档Object

        Returns:
            去重KeyString
        """
        if self.dedup_strategy == "url":
            url = doc.metadata.get("url")
            if url:
                return f"url:{url}"
            # fallback to Content去重

        # Default using Content去重
        return f"content:{get_document_dedup_hash(doc)}"
