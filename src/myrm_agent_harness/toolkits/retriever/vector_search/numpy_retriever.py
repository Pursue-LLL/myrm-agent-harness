"""基于 NumPy  纯内存Vector检索器

 for temporary文档集合 高性能Vector检索（Web SearchResult、爬取Content etc.）， no 需持久化。

[INPUT]
- toolkits.retriever.embedding::EmbeddingService (POS: Embedding protocol — text to vector abstraction.)

[OUTPUT]
- RetrievalResult: Retrieval result.
- NumpyVectorRetriever: Performance optimization：
- search_with_numpy_retriever: function — search_with_numpy_retriever

[POS]
Provides RetrievalResult, NumpyVectorRetriever, search_with_numpy_retriever.
"""

import logging
from dataclasses import dataclass

import numpy as np
from langchain_core.documents import Document

from myrm_agent_harness.toolkits.retriever.embedding import EmbeddingService

logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    """检索Result"""

    document: Document
    score: float


class NumpyVectorRetriever:
    """基于 NumPy  纯内存Vector检索器

     for temporary文档集合 Vector检索（Web SearchResult、爬取Content etc.）。
     using 预归一化 + float32 optimized，适 for  < 10,000 文档。

    Performance optimization：
    - 预归一化文档Vector（ avoid 重复Compute）
    -  using  float32（节省 50% 内存）
    - 批量矩阵运算（批量Queryspeedup）
    - argpartition Top-K 选择（O(n) vs O(n log n)）

     and  Qdrant  区别：
    -  no 需Startindependent进程，零Start开销
    - 纯内存Compute，适合i.e.时Scenario
    -  not Support持久化，适合temporaryData
    """

    def __init__(
        self,
        documents: list[Document],
        embeddings: EmbeddingService,
    ):
        if not documents:
            raise ValueError("Document list cannot be empty")

        self._documents = documents
        self._embeddings = embeddings
        self._doc_vectors_normalized: np.ndarray | None = None
        self._embedding_computed = False

    async def ensure_embeddings(self) -> None:
        """ ensure 文档Embedding already Compute并归一化"""
        if self._embedding_computed:
            return

        logger.warning(f"Computing embeddings for {len(self._documents)} documents...")
        texts = [doc.page_content for doc in self._documents]
        doc_vectors = await self._embeddings.embed_batch(texts)

        docs_arr = np.array(doc_vectors, dtype=np.float32)
        norms = np.linalg.norm(docs_arr, axis=1, keepdims=True)
        self._doc_vectors_normalized = docs_arr / (norms + 1e-8)

        self._embedding_computed = True
        logger.warning(f"Embeddings computed ({self._doc_vectors_normalized.nbytes / 1024 / 1024:.2f} MB)")

    async def search(
        self,
        query: str,
        limit: int = 10,
        score_threshold: float = 0.0,
    ) -> list[RetrievalResult]:
        """单Query检索

        Args:
            query: Querytext
            limit: ReturnMaximumCount
            score_threshold: 最低相似度阈Value

        Returns:
            检索ResultList
        """
        await self.ensure_embeddings()

        if self._doc_vectors_normalized is None:
            return []

        query_vector = await self._embeddings.embed(query)
        query_arr = np.array(query_vector, dtype=np.float32)
        query_norm = query_arr / (np.linalg.norm(query_arr) + 1e-8)

        scores = self._doc_vectors_normalized @ query_norm

        if score_threshold > 0:
            mask = scores >= score_threshold
            valid_indices = np.where(mask)[0]

            if len(valid_indices) == 0:
                return []

            valid_scores = scores[mask]

            if len(valid_indices) > limit:
                top_k_local = np.argpartition(valid_scores, -limit)[-limit:]
                top_k_local = top_k_local[np.argsort(valid_scores[top_k_local])[::-1]]
                final_indices = valid_indices[top_k_local]
            else:
                final_indices = valid_indices[np.argsort(valid_scores)[::-1]]
        else:
            if len(scores) > limit:
                top_k_indices = np.argpartition(scores, -limit)[-limit:]
                final_indices = top_k_indices[np.argsort(scores[top_k_indices])[::-1]]
            else:
                final_indices = np.argsort(scores)[::-1]

        results = []
        for idx in final_indices:
            doc = self._documents[idx]
            score = float(scores[idx])
            doc.metadata["score"] = score
            results.append(RetrievalResult(document=doc, score=score))

        return results

    async def batch_search(
        self,
        queries: list[str],
        limit: int = 10,
        score_threshold: float = 0.0,
    ) -> dict[str, list[RetrievalResult]]:
        """批量Query检索

        Args:
            queries: QuerytextList
            limit: EachQueryReturn MaximumCount
            score_threshold: 最低相似度阈Value

        Returns:
            EachQuery 检索Result
        """
        if not queries:
            return {}

        await self.ensure_embeddings()

        if self._doc_vectors_normalized is None:
            return {}

        query_vectors = await self._embeddings.embed_batch(queries)

        queries_arr = np.array(query_vectors, dtype=np.float32)
        queries_norms = np.linalg.norm(queries_arr, axis=1, keepdims=True)
        queries_normalized = queries_arr / (queries_norms + 1e-8)

        similarities = queries_normalized @ self._doc_vectors_normalized.T

        results: dict[str, list[RetrievalResult]] = {}
        for i, query in enumerate(queries):
            scores = similarities[i]

            if score_threshold > 0:
                mask = scores >= score_threshold
                valid_indices = np.where(mask)[0]

                if len(valid_indices) == 0:
                    results[query] = []
                    continue

                valid_scores = scores[mask]

                if len(valid_indices) > limit:
                    top_k_local = np.argpartition(valid_scores, -limit)[-limit:]
                    top_k_local = top_k_local[np.argsort(valid_scores[top_k_local])[::-1]]
                    final_indices = valid_indices[top_k_local]
                else:
                    final_indices = valid_indices[np.argsort(valid_scores)[::-1]]
            else:
                if len(scores) > limit:
                    top_k_indices = np.argpartition(scores, -limit)[-limit:]
                    final_indices = top_k_indices[np.argsort(scores[top_k_indices])[::-1]]
                else:
                    final_indices = np.argsort(scores)[::-1]

            query_results = []
            for idx in final_indices:
                doc = self._documents[idx]
                score = float(scores[idx])
                result_doc = Document(
                    page_content=doc.page_content,
                    metadata={**doc.metadata, "score": score},
                )
                query_results.append(RetrievalResult(document=result_doc, score=score))

            results[query] = query_results

        logger.warning(f"Batch search completed: {len(queries)} queries, {len(self._documents)} documents")
        return results


async def search_with_numpy_retriever(
    queries: list[str],
    documents: list[Document],
    embeddings: EmbeddingService,
    *,
    limit: int = 10,
    score_threshold: float = 0.0,
) -> dict[str, list[tuple[Document, float]]]:
    """纯内存Vector检索便捷Function"""
    if not queries or not documents:
        return {}

    try:
        retriever = NumpyVectorRetriever(documents, embeddings)
        results = await retriever.batch_search(
            queries=queries,
            limit=limit,
            score_threshold=score_threshold,
        )

        return {query: [(r.document, r.score) for r in query_results] for query, query_results in results.items()}

    except Exception as e:
        logger.error(f"NumPy vector search failed: {e}")
        return {}
