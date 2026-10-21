"""性能测试和基准测试"""

import time

import pytest

from myrm_agent_harness.agent.meta_tools.skills.search.engine import SkillSearchEngine
from myrm_agent_harness.agent.meta_tools.skills.search.hybrid_engine import HybridSkillSearchEngine
from myrm_agent_harness.backends.skills.types import SkillMetadata
from myrm_agent_harness.toolkits.retriever.embedding.factory import EmbeddingConfig


def create_large_skill_set(count: int) -> list[SkillMetadata]:
    """创建大规模技能集合用于性能测试"""
    skills = []
    for i in range(count):
        skills.append(
            SkillMetadata(
                name=f"skill_{i}",
                description=f"This is skill {i} for testing performance with various keywords",
                storage_skill_id=f"skill_{i}",
            )
        )
    return skills


@pytest.fixture
def embedding_config() -> EmbeddingConfig:
    """创建测试Embedding配置"""
    return EmbeddingConfig(model="text-embedding-3-small")


class TestBM25Performance:
    """BM25搜索性能测试"""

    def test_bm25_index_build_time_small(self) -> None:
        """测试小规模技能集索引构建时间"""
        skills = create_large_skill_set(10)
        start = time.perf_counter()
        engine = SkillSearchEngine(skills)
        elapsed = time.perf_counter() - start
        assert elapsed < 0.5
        assert len(engine._skills) == 10

    def test_bm25_index_build_time_medium(self) -> None:
        """测试中等规模技能集索引构建时间"""
        skills = create_large_skill_set(100)
        start = time.perf_counter()
        engine = SkillSearchEngine(skills)
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0
        assert len(engine._skills) == 100

    def test_bm25_search_time_small(self) -> None:
        """测试小规模技能集搜索时间"""
        skills = create_large_skill_set(10)
        engine = SkillSearchEngine(skills)

        engine.search_bm25("warmup query for initialization")

        times = []
        for _ in range(3):
            start = time.perf_counter()
            results = engine.search_bm25("warmup query for initialization")
            times.append(time.perf_counter() - start)
        median = sorted(times)[1]

        assert median < 0.05
        assert isinstance(results, list)

    def test_bm25_search_time_medium(self) -> None:
        """测试中等规模技能集搜索时间"""
        skills = create_large_skill_set(100)
        engine = SkillSearchEngine(skills)

        engine.search_bm25("warmup query for initialization")

        times = []
        for _ in range(3):
            start = time.perf_counter()
            results = engine.search_bm25("warmup query for initialization")
            times.append(time.perf_counter() - start)
        median = sorted(times)[1]

        assert median < 0.1
        assert isinstance(results, list)

    def test_regex_search_time(self) -> None:
        """测试regex搜索时间"""
        skills = create_large_skill_set(100)
        engine = SkillSearchEngine(skills)

        start = time.perf_counter()
        results = engine.search_regex("skill_[0-9]+")
        elapsed = time.perf_counter() - start

        assert elapsed < 0.1
        assert isinstance(results, list)


class TestHybridPerformance:
    """混合搜索性能测试"""

    @pytest.mark.asyncio
    async def test_lazy_loading_performance(self, embedding_config: EmbeddingConfig) -> None:
        """测试懒加载性能"""
        skills = create_large_skill_set(10)
        engine = HybridSkillSearchEngine(skills, embedding_config)

        start = time.perf_counter()
        await engine._ensure_vectors_built()
        first_build_time = time.perf_counter() - start

        start = time.perf_counter()
        await engine._ensure_vectors_built()
        second_build_time = time.perf_counter() - start

        assert second_build_time < first_build_time * 0.01

    @pytest.mark.asyncio
    async def test_concurrent_search_performance(self, embedding_config: EmbeddingConfig) -> None:
        """测试并发搜索性能"""
        import asyncio

        skills = create_large_skill_set(10)
        engine = HybridSkillSearchEngine(skills, embedding_config)

        async def search_task() -> None:
            await engine.search_bm25("test query")

        start = time.perf_counter()
        tasks = [search_task() for _ in range(10)]
        await asyncio.gather(*tasks)
        elapsed = time.perf_counter() - start

        assert elapsed < 5.0

    @pytest.mark.asyncio
    async def test_rrf_fusion_performance(self, embedding_config: EmbeddingConfig) -> None:
        """测试RRF融合性能"""
        from myrm_agent_harness.agent.meta_tools.skills.search.types import SkillSearchResult

        skills = create_large_skill_set(10)
        engine = HybridSkillSearchEngine(skills, embedding_config)

        bm25_results = [
            SkillSearchResult(name=f"skill_{i}", description=f"desc_{i}", score=1.0 - i * 0.1) for i in range(20)
        ]
        embedding_results = [
            SkillSearchResult(name=f"skill_{i}", description=f"desc_{i}", score=1.0 - i * 0.1) for i in range(20)
        ]

        start = time.perf_counter()
        fused = engine._rrf_fusion(bm25_results, embedding_results, top_k=10)
        elapsed = time.perf_counter() - start

        assert elapsed < 0.001
        assert len(fused) == 10


class TestScalability:
    """可扩展性测试"""

    def test_bm25_scalability(self) -> None:
        """测试BM25搜索的可扩展性"""
        sizes = [10, 50, 100]
        times = []

        for size in sizes:
            skills = create_large_skill_set(size)
            engine = SkillSearchEngine(skills)

            engine.search_bm25("warmup")

            start = time.perf_counter()
            for _ in range(10):
                engine.search_bm25("testing")
            elapsed = time.perf_counter() - start
            times.append(elapsed / 10)

        for i in range(len(times) - 1):
            ratio = times[i + 1] / times[i]
            assert ratio < 10.0

    @pytest.mark.asyncio
    async def test_hybrid_scalability(self, embedding_config: EmbeddingConfig) -> None:
        """测试混合搜索的可扩展性"""
        sizes = [5, 10]
        times = []

        for size in sizes:
            skills = create_large_skill_set(size)
            engine = HybridSkillSearchEngine(skills, embedding_config)

            start = time.perf_counter()
            for _ in range(3):
                await engine.search_bm25("testing")
            elapsed = time.perf_counter() - start
            times.append(elapsed / 3)

        for i in range(len(times) - 1):
            ratio = times[i + 1] / times[i]
            assert ratio < 10.0
