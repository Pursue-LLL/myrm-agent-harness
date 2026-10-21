"""缓存集成测试"""

from unittest.mock import patch

import pytest

from myrm_agent_harness.agent.meta_tools.skills.search.hybrid_engine import HybridSkillSearchEngine
from myrm_agent_harness.backends.skills.types import SkillMetadata
from myrm_agent_harness.toolkits.retriever.embedding import factory as _embedding_factory
from myrm_agent_harness.toolkits.retriever.embedding.factory import EmbeddingConfig

_FAKE_DIM = 1536


class _FakeEmbeddingResp:
    """Minimal litellm EmbeddingResponse mock."""

    def __init__(self, count: int) -> None:
        self.data = [{"embedding": [0.1] * _FAKE_DIM} for _ in range(count)]


@pytest.fixture(autouse=True)
def _mock_embedding_service():
    """Override conftest's DeterministicEmbeddingService — cache tests need real CloudEmbedding
    so the cache protocol is exercised. We mock only litellm.aembedding to avoid API calls.
    """

    async def _fake_aembedding(**kwargs: object) -> _FakeEmbeddingResp:
        texts = kwargs["input"]
        return _FakeEmbeddingResp(len(texts) if isinstance(texts, list) else 1)

    _embedding_factory._cache.clear()
    with patch("litellm.aembedding", side_effect=_fake_aembedding):
        yield
    _embedding_factory._cache.clear()


class MockEmbeddingCache:
    """Mock Embedding缓存用于测试"""

    def __init__(self) -> None:
        self.cache: dict[str, list[float]] = {}
        self.get_count = 0
        self.put_count = 0
        self.get_batch_count = 0
        self.put_batch_count = 0

    async def get(self, text: str) -> list[float] | None:
        self.get_count += 1
        return self.cache.get(text)

    async def put(self, text: str, embedding: list[float]) -> None:
        self.put_count += 1
        self.cache[text] = embedding

    async def get_batch(self, texts: list[str]) -> list[list[float] | None]:
        self.get_batch_count += 1
        return [self.cache.get(text) for text in texts]

    async def put_batch(self, texts: list[str], embeddings: list[list[float]]) -> None:
        self.put_batch_count += 1
        for text, embedding in zip(texts, embeddings, strict=True):
            self.cache[text] = embedding


@pytest.fixture
def sample_skills() -> list[SkillMetadata]:
    """创建测试技能列表"""
    return [
        SkillMetadata(name="skill_a", description="Description A", storage_skill_id="skill_a"),
        SkillMetadata(name="skill_b", description="Description B", storage_skill_id="skill_b"),
    ]


@pytest.fixture
def embedding_config() -> EmbeddingConfig:
    """创建测试Embedding配置"""
    return EmbeddingConfig(model="text-embedding-3-small", api_key="test-key-for-cache-tests")


class TestCacheIntegration:
    """缓存集成测试"""

    @pytest.mark.asyncio
    async def test_cache_hit_on_vector_build(
        self, sample_skills: list[SkillMetadata], embedding_config: EmbeddingConfig
    ) -> None:
        """测试向量构建时的缓存命中"""
        cache = MockEmbeddingCache()
        engine = HybridSkillSearchEngine(sample_skills, embedding_config, embedding_cache=cache)

        await engine._ensure_vectors_built()
        initial_get_batch_count = cache.get_batch_count
        initial_put_batch_count = cache.put_batch_count

        engine2 = HybridSkillSearchEngine(sample_skills, embedding_config, embedding_cache=cache)
        await engine2._ensure_vectors_built()

        assert cache.get_batch_count > initial_get_batch_count
        assert cache.put_batch_count == initial_put_batch_count

    @pytest.mark.asyncio
    async def test_cache_hit_on_query(
        self, sample_skills: list[SkillMetadata], embedding_config: EmbeddingConfig
    ) -> None:
        """测试查询时的缓存命中"""
        cache = MockEmbeddingCache()
        engine = HybridSkillSearchEngine(sample_skills, embedding_config, embedding_cache=cache)

        query = "test query"
        await engine.search_bm25(query)
        initial_get_count = cache.get_count

        await engine.search_bm25(query)
        assert cache.get_count > initial_get_count

    @pytest.mark.asyncio
    async def test_no_cache(self, sample_skills: list[SkillMetadata], embedding_config: EmbeddingConfig) -> None:
        """测试无缓存模式"""
        engine = HybridSkillSearchEngine(sample_skills, embedding_config, embedding_cache=None)

        await engine._ensure_vectors_built()
        assert engine._skill_vectors is not None

        results = await engine.search_bm25("test")
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_cache_miss_then_hit(
        self, sample_skills: list[SkillMetadata], embedding_config: EmbeddingConfig
    ) -> None:
        """测试缓存未命中后命中"""
        cache = MockEmbeddingCache()
        engine = HybridSkillSearchEngine(sample_skills, embedding_config, embedding_cache=cache)

        query = "unique query xyz"
        await engine.search_bm25(query)
        put_count_after_first = cache.put_count

        await engine.search_bm25(query)
        assert cache.put_count == put_count_after_first
