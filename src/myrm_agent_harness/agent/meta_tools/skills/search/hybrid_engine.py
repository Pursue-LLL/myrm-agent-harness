"""混合技能搜索引擎

结合 BM25 词法搜索 + Embedding 语义搜索, 使用 RRF 融合排序.

[INPUT]
- backends.skills.types::SkillMetadata (POS: 技能元数据)
- toolkits.retriever.embedding.factory::EmbeddingConfig, get_embedding_service (POS: Embedding 服务工厂)
- toolkits.memory.protocols.cache::EmbeddingCacheProtocol (POS: Embedding 缓存协议, 可选)
- .engine::SkillSearchEngine (POS: BM25 搜索引擎)

[OUTPUT]
- HybridSkillSearchEngine (POS: 混合搜索引擎, 缓存和重试内置在 EmbeddingService)

[POS]
Hybrid search engine. Executes BM25 and embedding searches in parallel, fusing results with Reciprocal Rank Fusion (RRF).

"""

from __future__ import annotations

import asyncio
import logging
import time
from types import ModuleType
from typing import TYPE_CHECKING

from .engine import SkillSearchEngine
from .types import SKILL_SEARCH_TOP_K, SearchMetadata, SkillSearchResult

if TYPE_CHECKING:
    import numpy as np
    import numpy.typing as npt

    from myrm_agent_harness.backends.skills.types import SkillMetadata
    from myrm_agent_harness.toolkits.memory.protocols.cache import EmbeddingCacheProtocol
    from myrm_agent_harness.toolkits.retriever.embedding.factory import EmbeddingConfig

logger = logging.getLogger(__name__)

DEFAULT_MIN_RELEVANCE_SCORE = 0.3
DEFAULT_RRF_K = 60
DEFAULT_RECALL_MULTIPLIER = 2


def _require_numpy() -> ModuleType:
    """Import numpy lazily so base installs without [retrieval] can import this module."""
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("numpy is required for hybrid skill search. Install myrm-agent-harness[retrieval].") from exc
    return np


class HybridSkillSearchEngine:
    """混合技能搜索引擎

    并行执行 BM25 词法搜索和 Embedding 语义搜索, 使用 RRF 算法融合结果.

    特性:
    - 精确匹配: BM25 确保技能名称精确匹配("12306_skill")
    - 语义理解: Embedding 支持同义词和概念匹配("查票" vs "铁路售票")
    - 跨语言: Embedding 自动匹配("火车票" 匹配 "railway ticket")
    - 容错降级: 单引擎失败时自动降级到另一个引擎
    - RRF 融合: 两个引擎都召回的技能分数更高, 自动平衡权重
    - 并发安全: 懒加载向量索引使用锁保护, 避免重复构建
    - 缓存和重试: 内置在 EmbeddingService 中, 透明处理
    """

    def __init__(
        self,
        skills: list[SkillMetadata],
        embedding_config: EmbeddingConfig,
        embedding_cache: EmbeddingCacheProtocol | None = None,
        rrf_k: int = DEFAULT_RRF_K,
        min_relevance_score: float = DEFAULT_MIN_RELEVANCE_SCORE,
        recall_multiplier: int = DEFAULT_RECALL_MULTIPLIER,
    ) -> None:
        """初始化混合搜索引擎

        Args:
            skills: 技能列表
            embedding_config: Embedding 模型配置（包含重试参数）
            embedding_cache: Embedding 缓存实例（可选，将传递给 EmbeddingService）
            rrf_k: RRF融合算法的常数k, 越大则排名靠后的结果权重越低
            min_relevance_score: Embedding搜索最低相关性阈值(余弦相似度)
            recall_multiplier: 召回倍数, 每个引擎召回top_k*multiplier个结果用于融合
        """
        from myrm_agent_harness.toolkits.retriever.embedding.factory import get_embedding_service

        self._skills = list(skills)
        self._bm25_engine = SkillSearchEngine(skills)
        self._embeddings = get_embedding_service(embedding_config, cache=embedding_cache)
        self._skill_vectors: npt.NDArray[np.float64] | None = None
        self._vector_lock = asyncio.Lock()
        self._rrf_k = rrf_k
        self._min_relevance_score = min_relevance_score
        self._recall_multiplier = recall_multiplier

        cache_status = "enabled" if embedding_cache is not None else "disabled"
        logger.info(" HybridSkillSearchEngine initialized (BM25 + Embedding hybrid mode)")
        logger.info(
            " Skills: %d | RRF_K: %d | Threshold: %.2f | Recall multiplier: %d | "
            "Lazy vector loading: yes | Cache: %s | Retry: built-in EmbeddingService",
            len(self._skills),
            self._rrf_k,
            self._min_relevance_score,
            self._recall_multiplier,
            cache_status,
        )

    async def _ensure_vectors_built(self) -> None:
        """确保向量索引已构建(懒加载, 并发安全)

        缓存逻辑由 EmbeddingService 处理，此方法只负责向量索引构建。
        支持大批量分批处理（避免超过API batch size限制）。
        """
        if self._skill_vectors is not None:
            return

        async with self._vector_lock:
            if self._skill_vectors is not None:
                return

            np = _require_numpy()
            start_time = time.perf_counter()
            corpus = [f"{s.name} {s.description}" for s in self._skills]

            # 分批处理避免超过API batch size限制（如64）
            batch_size = 50  # 保守值，避免超过大多数API的限制
            all_vectors = []
            for i in range(0, len(corpus), batch_size):
                batch = corpus[i : i + batch_size]
                batch_vectors = await self._embeddings.embed_batch(batch)
                all_vectors.extend(batch_vectors)
                if i + batch_size < len(corpus):
                    logger.info(
                        " Vector batch %d/%d completed | Progress: %d/%d skills",
                        (i // batch_size) + 1,
                        (len(corpus) + batch_size - 1) // batch_size,
                        i + len(batch),
                        len(corpus),
                    )

            self._skill_vectors = np.array(all_vectors, dtype=np.float64)

            elapsed_ms = (time.perf_counter() - start_time) * 1000
            vector_dim = self._skill_vectors.shape[1] if len(self._skill_vectors.shape) > 1 else 0
            logger.info(
                " Vector index built | Skills: %d | Dimension: %d | Time: %.2fms",
                len(self._skills),
                vector_dim,
                elapsed_ms,
            )

    async def search_bm25(self, query: str, top_k: int = SKILL_SEARCH_TOP_K) -> list[SkillSearchResult]:
        """混合搜索(保持接口兼容性, 实际使用 BM25+Embedding)

        特殊查询:
        - "*" 或 "all" 返回所有技能(用于浏览全部)

        Args:
            query: 搜索查询(任意语言, 自动语义理解 + 词法匹配)
            top_k: 返回结果数

        Returns:
            RRF 融合后按分数排序的搜索结果
        """
        if not query.strip():
            return []

        if query.strip() in ["*", "all"]:
            logger.info(" [HybridSearch] 特殊查询 '%s' -> 返回全部 %d 个技能", query, len(self._skills))
            return [SkillSearchResult(name=s.name, description=s.description, score=1.0) for s in self._skills]

        return await self._search_hybrid(query, top_k)

    async def search_regex(self, pattern: str, top_k: int = SKILL_SEARCH_TOP_K) -> list[SkillSearchResult]:
        """Regex 搜索(使用 BM25 引擎的 regex 能力)

        特殊模式:
        - ".*" 或 "^.*$" 返回所有技能(用于浏览全部)
        """
        if not pattern.strip():
            return []

        if pattern.strip() in [".*", "^.*$", ".+", "^.+$"]:
            logger.info(" [HybridSearch] 特殊模式 '%s' -> 返回全部 %d 个技能", pattern, len(self._skills))
            return [SkillSearchResult(name=s.name, description=s.description, score=1.0) for s in self._skills]

        return self._bm25_engine.search_regex(pattern, top_k)

    async def _search_hybrid(self, query: str, top_k: int) -> list[SkillSearchResult]:
        """内部混合搜索实现

        并行执行 BM25 和 Embedding 搜索, 使用 RRF 融合结果.

        Args:
            query: 搜索查询
            top_k: 返回结果数

        Returns:
            RRF 融合后的搜索结果
        """
        start_time = time.perf_counter()
        await self._ensure_vectors_built()
        build_time = (time.perf_counter() - start_time) * 1000

        search_start = time.perf_counter()
        recall_k = top_k * self._recall_multiplier
        bm25_task = asyncio.create_task(self._run_bm25_search(query, recall_k))
        embedding_task = asyncio.create_task(self._run_embedding_search(query, recall_k))

        bm25_results, embedding_results = await asyncio.gather(bm25_task, embedding_task, return_exceptions=True)

        bm25_failed = isinstance(bm25_results, Exception)
        embedding_failed = isinstance(embedding_results, Exception)

        if bm25_failed:
            logger.warning("BM25 搜索失败, 降级到纯 Embedding: %s", bm25_results)
            bm25_results = []

        if embedding_failed:
            logger.warning("Embedding 搜索失败, 降级到纯 BM25: %s", embedding_results)
            embedding_results = []

        if not bm25_results and not embedding_results:
            logger.warning(" [HybridSearch] 两个引擎都失败, 返回空结果")
            return []

        degraded = bm25_failed or embedding_failed

        rrf_start = time.perf_counter()
        fused_results = self._rrf_fusion(bm25_results, embedding_results, top_k)
        rrf_time = (time.perf_counter() - rrf_start) * 1000

        metadata = SearchMetadata(bm25_failed=bm25_failed, embedding_failed=embedding_failed, degraded=degraded)
        for result in fused_results:
            object.__setattr__(result, "metadata", metadata)

        total_time = (time.perf_counter() - start_time) * 1000
        search_time = (time.perf_counter() - search_start) * 1000

        degraded_info = " [降级模式]" if degraded else ""
        logger.info(
            " [HybridSearch] 查询 '%s' | BM25: %d | Embedding: %d | 融合后: %d%s | "
            "耗时: %.2fms (索引: %.2fms, 搜索: %.2fms, RRF: %.2fms)",
            query,
            len(bm25_results),
            len(embedding_results),
            len(fused_results),
            degraded_info,
            total_time,
            build_time,
            search_time,
            rrf_time,
        )
        return fused_results

    async def _run_bm25_search(self, query: str, top_k: int) -> list[SkillSearchResult]:
        """执行 BM25 搜索

        BM25搜索极快(<1ms)，直接同步执行。在Hybrid模式下与Embedding并行时，
        总耗时由慢速Embedding决定(几十到几百ms)，BM25的<1ms可忽略。

        Args:
            query: 搜索查询
            top_k: 返回结果数

        Returns:
            BM25 搜索结果
        """
        return self._bm25_engine.search_bm25(query, top_k)

    async def _run_embedding_search(self, query: str, top_k: int) -> list[SkillSearchResult]:
        """执行 Embedding 搜索

        重试逻辑由 EmbeddingService 内置处理。

        Args:
            query: 搜索查询
            top_k: 返回结果数

        Returns:
            Embedding 搜索结果
        """
        np = _require_numpy()
        embed_start = time.perf_counter()

        query_vector = np.array(await self._embeddings.embed(query), dtype=np.float64)

        embed_time = (time.perf_counter() - embed_start) * 1000

        sim_start = time.perf_counter()

        skill_norms = np.linalg.norm(self._skill_vectors, axis=1)
        query_norm = np.linalg.norm(query_vector)

        if query_norm < 1e-10:
            logger.warning("Query vector is zero or near-zero")
            return []

        skill_norms = np.maximum(skill_norms, 1e-10)
        query_norm = max(query_norm, 1e-10)

        similarities = np.dot(self._skill_vectors, query_vector) / (skill_norms * query_norm)

        if len(similarities) <= top_k:
            top_indices = np.argsort(similarities)[::-1]
        else:
            top_indices = np.argpartition(similarities, -top_k)[-top_k:]
            top_indices = top_indices[np.argsort(similarities[top_indices])[::-1]]

        results: list[SkillSearchResult] = []
        for idx in top_indices:
            score = float(similarities[idx])
            if score < self._min_relevance_score:
                continue
            skill = self._skills[idx]
            results.append(SkillSearchResult(name=skill.name, description=skill.description, score=score))

        sim_time = (time.perf_counter() - sim_start) * 1000

        logger.debug(
            "Embedding search completed | Query encoding: %.2fms | Similarity calculation: %.2fms | Results: %d",
            embed_time,
            sim_time,
            len(results),
        )

        return results

    def _rrf_fusion(
        self, bm25_results: list[SkillSearchResult], embedding_results: list[SkillSearchResult], top_k: int
    ) -> list[SkillSearchResult]:
        """RRF (Reciprocal Rank Fusion) 融合算法

        RRF 公式: score(doc) = sum(1 / (k + rank)) for all ranking lists
        k 是常数(通常 60), rank 是排名(从 1 开始)

        Args:
            bm25_results: BM25 搜索结果
            embedding_results: Embedding 搜索结果
            top_k: 最终返回结果数

        Returns:
            RRF 融合后的排序结果
        """
        skill_scores: dict[str, float] = {}
        skill_descriptions: dict[str, str] = {}

        for rank, result in enumerate(bm25_results, start=1):
            skill_scores[result.name] = skill_scores.get(result.name, 0.0) + 1.0 / (self._rrf_k + rank)
            skill_descriptions[result.name] = result.description

        for rank, result in enumerate(embedding_results, start=1):
            skill_scores[result.name] = skill_scores.get(result.name, 0.0) + 1.0 / (self._rrf_k + rank)
            skill_descriptions[result.name] = result.description

        # Stable tie-break: sort by score (desc) then by name (asc)
        sorted_skills = sorted(skill_scores.items(), key=lambda x: (-x[1], x[0]))[:top_k]

        fused_results: list[SkillSearchResult] = []
        for skill_name, rrf_score in sorted_skills:
            description = skill_descriptions[skill_name]
            fused_results.append(SkillSearchResult(name=skill_name, description=description, score=rrf_score))

        return fused_results
