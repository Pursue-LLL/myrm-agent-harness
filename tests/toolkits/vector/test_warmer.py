"""测试向量存储缓存预热功能。

验证 VectorStoreWarmer 的预热和效果验证功能。
"""

from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.vector import (
    DummyQueryStrategy,
    VectorStoreWarmer,
    VectorWarmupMetrics,
)
from myrm_agent_harness.toolkits.vector.base import CollectionInfo, SearchResult, VectorDocument


@pytest.fixture
def mock_vector_store():
    """创建模拟的向量存储。"""
    store = AsyncMock()
    store.collection_exists = AsyncMock(return_value=True)
    store.search = AsyncMock(
        return_value=[
            SearchResult(
                document=VectorDocument(id="doc1", content="test document", vector=[0.1] * 1536),
                score=0.9,
            )
        ]
    )
    store.list_collections = AsyncMock(
        return_value=[
            CollectionInfo(name="kb_docs", dimension=1536, count=100),
            CollectionInfo(name="kb_code", dimension=1536, count=50),
        ]
    )
    return store


@pytest.fixture
def warmer(mock_vector_store):
    """创建预热器实例。"""
    return VectorStoreWarmer(mock_vector_store)


class TestVectorWarmupMetrics:
    """测试 VectorWarmupMetrics。"""

    def test_metrics_initialization(self):
        """测试指标初始化。"""
        metrics = VectorWarmupMetrics(collection_name="test_collection")
        assert metrics.collection_name == "test_collection"
        assert metrics.warmup_duration_ms == 0.0
        assert metrics.verify_duration_ms is None
        assert metrics.speedup_ratio is None
        assert metrics.success is True
        assert metrics.error is None

    def test_metrics_to_dict(self):
        """测试指标导出。"""
        metrics = VectorWarmupMetrics(
            collection_name="test_collection",
            warmup_duration_ms=200.5,
            verify_duration_ms=48.3,
            speedup_ratio=4.15,
            success=True,
            error=None,
        )

        result = metrics.to_dict()

        assert result["collection_name"] == "test_collection"
        assert result["warmup_duration_ms"] == 200.5
        assert result["verify_duration_ms"] == 48.3
        assert result["speedup_ratio"] == 4.15
        assert result["success"] is True
        assert result["error"] is None

    def test_metrics_to_dict_with_error(self):
        """测试失败场景的指标导出。"""
        metrics = VectorWarmupMetrics(
            collection_name="test_collection",
            warmup_duration_ms=10.0,
            success=False,
            error="Collection does not exist",
        )

        result = metrics.to_dict()

        assert result["success"] is False
        assert result["error"] == "Collection does not exist"
        assert result["verify_duration_ms"] is None
        assert result["speedup_ratio"] is None


class TestDummyQueryStrategy:
    """测试 DummyQueryStrategy。"""

    @pytest.mark.asyncio
    async def test_generate_query_vector(self):
        """测试生成查询向量。"""
        strategy = DummyQueryStrategy()
        vector = await strategy.generate_query_vector(dimension=1536)

        assert len(vector) == 1536
        assert all(isinstance(v, float) for v in vector)

        norm = sum(x * x for x in vector) ** 0.5
        assert 0.9 < norm < 1.1

    @pytest.mark.asyncio
    async def test_generate_different_vectors(self):
        """测试生成不同的随机向量。"""
        strategy = DummyQueryStrategy()
        vector1 = await strategy.generate_query_vector(dimension=128)
        vector2 = await strategy.generate_query_vector(dimension=128)

        assert vector1 != vector2


class TestVectorStoreWarmer:
    """测试 VectorStoreWarmer。"""

    @pytest.mark.asyncio
    async def test_warmup_collection_success(self, warmer, mock_vector_store):
        """测试单collection预热成功。"""
        metrics = await warmer.warmup_collection("kb_docs", dimension=1536)

        assert metrics.success is True
        assert metrics.collection_name == "kb_docs"
        assert metrics.warmup_duration_ms > 0
        assert metrics.error is None

        mock_vector_store.collection_exists.assert_awaited_once_with("kb_docs")
        assert mock_vector_store.search.await_count == 1

    @pytest.mark.asyncio
    async def test_warmup_collection_not_exists(self, warmer, mock_vector_store):
        """测试collection不存在的场景。"""
        mock_vector_store.collection_exists.return_value = False

        metrics = await warmer.warmup_collection("nonexistent", dimension=1536)

        assert metrics.success is False
        assert metrics.error == "Collection does not exist"
        assert mock_vector_store.search.await_count == 0

    @pytest.mark.asyncio
    async def test_warmup_collection_search_failure(self, warmer, mock_vector_store):
        """测试查询失败的场景。"""
        mock_vector_store.search.side_effect = Exception("Search failed")

        metrics = await warmer.warmup_collection("kb_docs", dimension=1536)

        assert metrics.success is False
        assert "Search failed" in metrics.error
        assert metrics.warmup_duration_ms > 0

    @pytest.mark.asyncio
    async def test_warmup_with_verification_success(self, warmer, mock_vector_store):
        """测试带验证的预热成功场景。"""
        metrics = await warmer.warmup_with_verification("kb_docs", dimension=1536)

        assert metrics.success is True
        assert metrics.collection_name == "kb_docs"
        assert metrics.warmup_duration_ms > 0
        assert metrics.verify_duration_ms is not None
        assert metrics.verify_duration_ms > 0
        assert metrics.speedup_ratio is not None
        assert metrics.speedup_ratio > 0
        assert metrics.error is None

        mock_vector_store.collection_exists.assert_awaited_once_with("kb_docs")
        assert mock_vector_store.search.await_count == 2

    @pytest.mark.asyncio
    async def test_warmup_with_verification_speedup_ratio(self, warmer, mock_vector_store):
        """测试加速比计算。"""
        metrics = await warmer.warmup_with_verification("kb_docs", dimension=1536)

        assert metrics.success is True
        assert metrics.speedup_ratio is not None

        expected_ratio = metrics.warmup_duration_ms / metrics.verify_duration_ms
        assert abs(metrics.speedup_ratio - expected_ratio) < 0.01

    @pytest.mark.asyncio
    async def test_warmup_with_verification_not_exists(self, warmer, mock_vector_store):
        """测试带验证的预热-collection不存在。"""
        mock_vector_store.collection_exists.return_value = False

        metrics = await warmer.warmup_with_verification("nonexistent", dimension=1536)

        assert metrics.success is False
        assert metrics.error == "Collection does not exist"
        assert metrics.verify_duration_ms is None
        assert metrics.speedup_ratio is None
        assert mock_vector_store.search.await_count == 0

    @pytest.mark.asyncio
    async def test_warmup_with_verification_search_failure(self, warmer, mock_vector_store):
        """测试带验证的预热-查询失败。"""
        mock_vector_store.search.side_effect = Exception("Search failed")

        metrics = await warmer.warmup_with_verification("kb_docs", dimension=1536)

        assert metrics.success is False
        assert "Search failed" in metrics.error
        assert metrics.warmup_duration_ms > 0

    @pytest.mark.asyncio
    async def test_warmup_batch(self, warmer, mock_vector_store):
        """测试批量预热。"""
        collections = [("kb_docs", 1536), ("kb_code", 1536)]

        metrics_list = await warmer.warmup_batch(collections)

        assert len(metrics_list) == 2
        assert all(m.success for m in metrics_list)
        assert metrics_list[0].collection_name == "kb_docs"
        assert metrics_list[1].collection_name == "kb_code"
        assert mock_vector_store.collection_exists.await_count == 2
        assert mock_vector_store.search.await_count == 2

    @pytest.mark.asyncio
    async def test_warmup_batch_with_verification(self, warmer, mock_vector_store):
        """测试批量预热带验证。"""
        collections = [("kb_docs", 1536), ("kb_code", 1536)]

        metrics_list = await warmer.warmup_batch_with_verification(collections)

        assert len(metrics_list) == 2
        assert all(m.success for m in metrics_list)
        assert all(m.verify_duration_ms is not None for m in metrics_list)
        assert all(m.speedup_ratio is not None for m in metrics_list)
        assert all(m.speedup_ratio > 0 for m in metrics_list)
        assert metrics_list[0].collection_name == "kb_docs"
        assert metrics_list[1].collection_name == "kb_code"
        assert mock_vector_store.collection_exists.await_count == 2
        assert mock_vector_store.search.await_count == 4

    @pytest.mark.asyncio
    async def test_warmup_batch_with_verification_partial_failure(self, warmer, mock_vector_store):
        """测试批量预热带验证-部分失败。"""

        def side_effect_exists(collection: str):
            return collection == "kb_docs"

        mock_vector_store.collection_exists.side_effect = side_effect_exists

        collections = [("kb_docs", 1536), ("nonexistent", 1536)]

        metrics_list = await warmer.warmup_batch_with_verification(collections)

        assert len(metrics_list) == 2
        assert metrics_list[0].success is True
        assert metrics_list[0].speedup_ratio is not None
        assert metrics_list[1].success is False
        assert metrics_list[1].speedup_ratio is None

    @pytest.mark.asyncio
    async def test_warmup_custom_limit(self, warmer, mock_vector_store):
        """测试自定义limit参数。"""
        await warmer.warmup_collection("kb_docs", dimension=1536, limit=5)

        call_args = mock_vector_store.search.call_args
        assert call_args.kwargs["limit"] == 5
