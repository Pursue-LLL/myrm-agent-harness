"""混合搜索引擎单元测试和集成测试"""

import asyncio

import numpy as np
import pytest

from myrm_agent_harness.agent.meta_tools.skills.search.hybrid_engine import (
    DEFAULT_MIN_RELEVANCE_SCORE,
    DEFAULT_RECALL_MULTIPLIER,
    DEFAULT_RRF_K,
    HybridSkillSearchEngine,
)
from myrm_agent_harness.backends.skills.types import SkillMetadata
from myrm_agent_harness.toolkits.retriever.embedding.factory import EmbeddingConfig


@pytest.fixture
def sample_skills() -> list[SkillMetadata]:
    """创建测试技能列表

    6 skills ensure "railway"/"ticket" IDF > 0 (df=2 out of 6 docs → IDF ≈ 0.51).
    With only 4 skills where 2 contain "railway", BM25 IDF = log(1) = 0.
    """
    return [
        SkillMetadata(
            name="railway_ticket_skill",
            description="火车票查询和预订服务 railway ticket booking service",
            storage_skill_id="railway_ticket_skill",
        ),
        SkillMetadata(
            name="weather_forecast_skill",
            description="天气预报查询 weather forecast query",
            storage_skill_id="weather_forecast_skill",
        ),
        SkillMetadata(
            name="database_query_skill",
            description="数据库查询工具 database query tool SQL",
            storage_skill_id="database_query_skill",
        ),
        SkillMetadata(
            name="12306_skill",
            description="12306铁路售票系统 12306 railway ticket system",
            storage_skill_id="12306_skill",
        ),
        SkillMetadata(
            name="email_sender_skill",
            description="邮件发送服务 email sending notification service",
            storage_skill_id="email_sender_skill",
        ),
        SkillMetadata(
            name="calendar_event_skill",
            description="日历事件管理 calendar event scheduling",
            storage_skill_id="calendar_event_skill",
        ),
    ]


@pytest.fixture
def embedding_config() -> EmbeddingConfig:
    """创建测试Embedding配置"""
    return EmbeddingConfig(model="text-embedding-3-small")


class TestHybridSkillSearchEngine:
    """混合搜索引擎测试"""

    @pytest.mark.asyncio
    async def test_init(self, sample_skills: list[SkillMetadata], embedding_config: EmbeddingConfig) -> None:
        """测试引擎初始化"""
        engine = HybridSkillSearchEngine(sample_skills, embedding_config)
        assert len(engine._skills) == 6
        assert engine._rrf_k == DEFAULT_RRF_K
        assert engine._min_relevance_score == DEFAULT_MIN_RELEVANCE_SCORE
        assert engine._recall_multiplier == DEFAULT_RECALL_MULTIPLIER
        assert engine._skill_vectors is None

    @pytest.mark.asyncio
    async def test_init_with_custom_params(
        self, sample_skills: list[SkillMetadata], embedding_config: EmbeddingConfig
    ) -> None:
        """测试自定义参数初始化"""
        engine = HybridSkillSearchEngine(
            sample_skills, embedding_config, rrf_k=30, min_relevance_score=0.2, recall_multiplier=3
        )
        assert engine._rrf_k == 30
        assert engine._min_relevance_score == 0.2
        assert engine._recall_multiplier == 3

    @pytest.mark.asyncio
    async def test_lazy_vector_build(
        self, sample_skills: list[SkillMetadata], embedding_config: EmbeddingConfig
    ) -> None:
        """测试懒加载向量索引"""
        engine = HybridSkillSearchEngine(sample_skills, embedding_config)
        assert engine._skill_vectors is None

        await engine._ensure_vectors_built()
        assert engine._skill_vectors is not None
        assert engine._skill_vectors.shape[0] == 6

    @pytest.mark.asyncio
    async def test_concurrent_vector_build(
        self, sample_skills: list[SkillMetadata], embedding_config: EmbeddingConfig
    ) -> None:
        """测试并发安全的向量索引构建"""
        engine = HybridSkillSearchEngine(sample_skills, embedding_config)

        async def build_vectors() -> None:
            await engine._ensure_vectors_built()

        tasks = [build_vectors() for _ in range(10)]
        await asyncio.gather(*tasks)

        assert engine._skill_vectors is not None
        assert engine._skill_vectors.shape[0] == 6

    @pytest.mark.asyncio
    async def test_search_bm25_chinese(
        self, sample_skills: list[SkillMetadata], embedding_config: EmbeddingConfig
    ) -> None:
        """测试中文混合搜索"""
        engine = HybridSkillSearchEngine(sample_skills, embedding_config)
        results = await engine.search_bm25("火车票")
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_search_bm25_english(
        self, sample_skills: list[SkillMetadata], embedding_config: EmbeddingConfig
    ) -> None:
        """测试英文混合搜索"""
        engine = HybridSkillSearchEngine(sample_skills, embedding_config)
        results = await engine.search_bm25("railway ticket")
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_search_bm25_empty_query(
        self, sample_skills: list[SkillMetadata], embedding_config: EmbeddingConfig
    ) -> None:
        """测试空查询"""
        engine = HybridSkillSearchEngine(sample_skills, embedding_config)
        results = await engine.search_bm25("")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_search_bm25_special_query_star(
        self, sample_skills: list[SkillMetadata], embedding_config: EmbeddingConfig
    ) -> None:
        """测试特殊查询 *"""
        engine = HybridSkillSearchEngine(sample_skills, embedding_config)
        results = await engine.search_bm25("*")
        assert len(results) == 6

    @pytest.mark.asyncio
    async def test_search_regex(self, sample_skills: list[SkillMetadata], embedding_config: EmbeddingConfig) -> None:
        """测试regex搜索"""
        engine = HybridSkillSearchEngine(sample_skills, embedding_config)
        results = await engine.search_regex("railway")
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_rrf_fusion(self, sample_skills: list[SkillMetadata], embedding_config: EmbeddingConfig) -> None:
        """测试RRF融合算法"""
        engine = HybridSkillSearchEngine(sample_skills, embedding_config, rrf_k=60)

        from myrm_agent_harness.agent.meta_tools.skills.search.types import SkillSearchResult

        bm25_results = [
            SkillSearchResult(name="skill_a", description="desc_a", score=0.9),
            SkillSearchResult(name="skill_b", description="desc_b", score=0.8),
            SkillSearchResult(name="skill_c", description="desc_c", score=0.7),
        ]

        embedding_results = [
            SkillSearchResult(name="skill_a", description="desc_a", score=0.95),
            SkillSearchResult(name="skill_d", description="desc_d", score=0.85),
            SkillSearchResult(name="skill_e", description="desc_e", score=0.75),
        ]

        fused = engine._rrf_fusion(bm25_results, embedding_results, top_k=3)

        assert len(fused) == 3
        assert fused[0].name == "skill_a"

        for i in range(len(fused) - 1):
            assert fused[i].score >= fused[i + 1].score

    @pytest.mark.asyncio
    async def test_numerical_stability_zero_query(
        self, sample_skills: list[SkillMetadata], embedding_config: EmbeddingConfig
    ) -> None:
        """测试零查询向量的数值稳定性"""
        engine = HybridSkillSearchEngine(sample_skills, embedding_config)
        await engine._ensure_vectors_built()

        async def _zero_embed(_q: str) -> list[float]:
            return [0.0] * 1536

        engine._embeddings.embed = _zero_embed

        results = await engine._run_embedding_search("test", top_k=5)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_numerical_stability_zero_skill_vector(
        self, sample_skills: list[SkillMetadata], embedding_config: EmbeddingConfig
    ) -> None:
        """测试零技能向量的数值稳定性"""
        engine = HybridSkillSearchEngine(sample_skills, embedding_config)
        await engine._ensure_vectors_built()

        engine._skill_vectors[0] = np.zeros(engine._skill_vectors.shape[1])

        results = await engine._run_embedding_search("test", top_k=5)

        assert not np.isnan(results[0].score if results else 0.0)
        assert not np.isinf(results[0].score if results else 0.0)

    @pytest.mark.asyncio
    async def test_recall_multiplier(
        self, sample_skills: list[SkillMetadata], embedding_config: EmbeddingConfig
    ) -> None:
        """测试召回倍数参数"""
        engine = HybridSkillSearchEngine(sample_skills, embedding_config, recall_multiplier=3)

        results = await engine.search_bm25("railway")
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_min_relevance_score_filtering(
        self, sample_skills: list[SkillMetadata], embedding_config: EmbeddingConfig
    ) -> None:
        """测试最低相关性阈值过滤"""
        engine_strict = HybridSkillSearchEngine(sample_skills, embedding_config, min_relevance_score=0.9)
        engine_loose = HybridSkillSearchEngine(sample_skills, embedding_config, min_relevance_score=0.1)

        results_strict = await engine_strict.search_bm25("test")
        results_loose = await engine_loose.search_bm25("test")

        assert len(results_loose) >= len(results_strict)

    @pytest.mark.asyncio
    async def test_search_metadata_normal(
        self, sample_skills: list[SkillMetadata], embedding_config: EmbeddingConfig
    ) -> None:
        """测试正常搜索的metadata"""
        engine = HybridSkillSearchEngine(sample_skills, embedding_config)
        results = await engine.search_bm25("railway")

        if results:
            assert results[0].metadata is not None
            assert results[0].metadata.bm25_failed is False
            assert results[0].metadata.embedding_failed is False
            assert results[0].metadata.degraded is False

    @pytest.mark.asyncio
    async def test_retry_mechanism(self, sample_skills: list[SkillMetadata]) -> None:
        """测试重试机制（重试逻辑现在内置在EmbeddingService中）"""
        config = EmbeddingConfig(model="text-embedding-3-small", max_retries=1)
        engine = HybridSkillSearchEngine(sample_skills, config)

        results = await engine.search_bm25("test")
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_stable_tie_break(
        self, sample_skills: list[SkillMetadata], embedding_config: EmbeddingConfig
    ) -> None:
        """测试相同分数的技能排序稳定性（按名称字典序）"""
        engine = HybridSkillSearchEngine(sample_skills, embedding_config)

        # 多次运行相同查询，确保结果顺序一致
        results1 = await engine.search_bm25("test", top_k=10)
        results2 = await engine.search_bm25("test", top_k=10)
        results3 = await engine.search_bm25("test", top_k=10)

        # 验证结果一致
        assert len(results1) == len(results2) == len(results3)
        for r1, r2, r3 in zip(results1, results2, results3, strict=False):
            assert r1.name == r2.name == r3.name
            assert abs(r1.score - r2.score) < 1e-6
            assert abs(r2.score - r3.score) < 1e-6

        # 验证相同分数的技能按名称字典序排列
        for i in range(len(results1) - 1):
            if abs(results1[i].score - results1[i + 1].score) < 1e-6:
                # 相同分数，检查名称字典序
                assert results1[i].name < results1[i + 1].name, (
                    f"Same score skills not sorted by name: "
                    f"{results1[i].name} (score={results1[i].score:.6f}) should come before "
                    f"{results1[i + 1].name} (score={results1[i + 1].score:.6f})"
                )
