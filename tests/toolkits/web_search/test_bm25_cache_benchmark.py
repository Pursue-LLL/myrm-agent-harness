"""BM25 缓存性能基准测试（测试 RetrieverManager 的缓存功能）"""

import time

import pytest
from langchain_core.documents import Document

from myrm_agent_harness.toolkits.retriever.engine import RetrieverManager


@pytest.fixture
def retriever_manager():
    """创建 RetrieverManager 实例"""
    return RetrieverManager()


@pytest.fixture
def mock_documents():
    """生成测试文档"""
    return [
        Document(
            page_content=f"This is test document {i} about artificial intelligence and machine learning. "
            f"It contains information about neural networks, deep learning, and natural language processing. " * 3,
            metadata={"url": f"https://example.com/doc{i}", "title": f"Document {i}"},
        )
        for i in range(50)
    ]


class TestBM25CacheBenchmark:
    """BM25 缓存性能基准测试（测试 RetrieverManager 的缓存功能）"""

    async def test_cache_performance_improvement(self, retriever_manager, mock_documents):
        """验证缓存对性能的提升"""
        queries = ["artificial intelligence", "machine learning", "deep learning"]

        # 清空缓存统计
        retriever_manager.bm25_cache_stats.hits = 0
        retriever_manager.bm25_cache_stats.misses = 0

        # 第一次调用：构建索引
        start_time = time.perf_counter()
        retriever1 = await retriever_manager._get_cached_bm25_retriever(mock_documents)
        first_build_time = (time.perf_counter() - start_time) * 1000

        # 执行搜索
        results1 = retriever1.search(queries[0], 10)
        assert retriever_manager.bm25_cache_stats.misses == 1, "应该未命中缓存"
        assert retriever_manager.bm25_cache_stats.hits == 0

        # 第二次调用：使用缓存
        start_time = time.perf_counter()
        retriever2 = await retriever_manager._get_cached_bm25_retriever(mock_documents)
        cached_build_time = (time.perf_counter() - start_time) * 1000

        # 执行搜索验证功能一致
        results2 = retriever2.search(queries[0], 10)

        print(f"\n首次构建索引耗时: {first_build_time:.2f}ms")
        print(f"缓存命中耗时: {cached_build_time:.2f}ms")
        print(f"性能提升: {first_build_time / cached_build_time:.1f}x")
        print(f"缓存命中率: {retriever_manager.bm25_cache_stats.hit_rate:.1%}")

        # 验证：缓存命中应该快至少 10 倍
        assert cached_build_time < first_build_time / 10, (
            f"缓存性能提升不足：首次 {first_build_time:.2f}ms, "
            f"缓存 {cached_build_time:.2f}ms, 提升 {first_build_time / cached_build_time:.1f}x"
        )

        # 验证缓存统计
        assert retriever_manager.bm25_cache_stats.hits == 1, "应该命中缓存1次"
        assert retriever_manager.bm25_cache_stats.misses == 1, "应该未命中缓存1次"
        assert retriever_manager.bm25_cache_stats.hit_rate == 0.5, "命中率应该是50%"

        # 验证结果一致性
        assert retriever1 is retriever2, "应返回相同的缓存实例"
        assert results1 == results2, "搜索结果应保持一致"

    async def test_cache_lru_eviction(self, retriever_manager, mock_documents):
        """验证 LRU 缓存淘汰策略"""
        # 清空缓存
        retriever_manager._bm25_cache.clear()
        retriever_manager._bm25_cache_order.clear()
        retriever_manager.bm25_cache_stats.evictions = 0

        # 创建 11 组不同的文档（超过默认缓存大小 10）
        docs_sets = [
            [
                Document(
                    page_content=f"Set {i} doc {j} unique content", metadata={"url": f"https://test{i}.com/doc{j}"}
                )
                for j in range(10)
            ]
            for i in range(11)
        ]

        # 填充缓存到上限
        for i in range(10):
            await retriever_manager._get_cached_bm25_retriever(docs_sets[i])
            assert len(retriever_manager._bm25_cache) == i + 1

        # 添加第11个，应触发淘汰
        await retriever_manager._get_cached_bm25_retriever(docs_sets[10])
        assert len(retriever_manager._bm25_cache) == 10, "缓存大小应保持在上限"
        assert retriever_manager.bm25_cache_stats.evictions == 1, "应该有1次淘汰"

        # 验证第1组（最早的）被淘汰，访问它应该重新构建
        cache_stats_before = retriever_manager.bm25_cache_stats.misses
        await retriever_manager._get_cached_bm25_retriever(docs_sets[0])
        assert retriever_manager.bm25_cache_stats.misses == cache_stats_before + 1, "第1组应该被淘汰，重新构建"

    @pytest.mark.asyncio
    async def test_full_search_with_cache(self, retriever_manager, mock_documents):
        """测试完整搜索流程中的缓存效果"""
        queries = ["query1", "query2"]

        # 清空缓存统计
        retriever_manager._bm25_cache.clear()
        retriever_manager._bm25_cache_order.clear()
        retriever_manager.bm25_cache_stats.hits = 0
        retriever_manager.bm25_cache_stats.misses = 0

        # 第一次搜索：构建索引
        start_time = time.perf_counter()
        results1 = await retriever_manager.bm25_retrieval_only(queries, mock_documents, 10)
        first_time = (time.perf_counter() - start_time) * 1000

        # 第二次搜索：使用缓存
        start_time = time.perf_counter()
        results2 = await retriever_manager.bm25_retrieval_only(queries, mock_documents, 10)
        cached_time = (time.perf_counter() - start_time) * 1000

        print(f"\n首次 BM25 搜索耗时: {first_time:.2f}ms")
        print(f"缓存后搜索耗时: {cached_time:.2f}ms")
        print(f"性能提升: {first_time / cached_time:.1f}x")
        print(f"缓存命中率: {retriever_manager.bm25_cache_stats.hit_rate:.1%}")

        # 验证缓存有效
        assert cached_time < first_time, "缓存后应该更快"
        assert len(results1) == len(results2), "结果数量应一致"
        assert retriever_manager.bm25_cache_stats.hits >= 1, "应该至少有1次命中"
