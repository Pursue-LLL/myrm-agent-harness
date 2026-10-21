"""并发安全测试（验证 asyncio.Lock 的正确性）"""

import asyncio

import pytest
from langchain_core.documents import Document

from myrm_agent_harness.toolkits.retriever import RetrieverManager


@pytest.fixture
def mock_documents():
    """生成测试文档"""
    return [
        Document(
            page_content=f"Test document {i} with some content about concurrent access.",
            metadata={"url": f"https://example.com/doc{i}", "title": f"Doc {i}"},
        )
        for i in range(100)
    ]


class TestConcurrentSafety:
    """并发安全测试套件"""

    @pytest.mark.asyncio
    async def test_concurrent_cache_read(self, mock_documents):
        """测试并发缓存读取（都命中缓存）"""
        manager = RetrieverManager()

        # 预热缓存
        await manager._get_cached_bm25_retriever(mock_documents)
        assert manager.bm25_cache_stats.misses == 1

        # 重置统计
        manager.bm25_cache_stats.hits = 0

        # 100个并发请求
        tasks = [manager._get_cached_bm25_retriever(mock_documents) for _ in range(100)]
        retrievers = await asyncio.gather(*tasks)

        # 验证：所有请求都命中缓存
        assert manager.bm25_cache_stats.hits == 100
        assert manager.bm25_cache_stats.misses == 1

        # 验证：返回的是同一个实例
        assert all(r is retrievers[0] for r in retrievers)

    @pytest.mark.asyncio
    async def test_concurrent_cache_write(self):
        """测试并发缓存写入（竞态条件测试）"""
        manager = RetrieverManager()

        # 创建多组不同的文档
        doc_sets = [
            [
                Document(page_content=f"Set {i} doc {j}", metadata={"url": f"https://test{i}.com/doc{j}"})
                for j in range(10)
            ]
            for i in range(20)
        ]

        # 并发构建索引
        tasks = [manager._get_cached_bm25_retriever(docs) for docs in doc_sets]
        await asyncio.gather(*tasks)

        # 验证：缓存大小正确（应该<=10，LRU淘汰）
        assert len(manager._bm25_cache) <= 10

        # 验证：统计一致性
        assert manager.bm25_cache_stats.hits + manager.bm25_cache_stats.misses == 20
        assert manager.bm25_cache_stats.evictions >= 10  # 至少淘汰了10个

    @pytest.mark.asyncio
    async def test_concurrent_mixed_operations(self, mock_documents):
        """测试混合并发操作（读写混合）"""
        manager = RetrieverManager()

        # 预热缓存
        await manager._get_cached_bm25_retriever(mock_documents)

        # 创建额外的文档集
        doc_sets = [
            [
                Document(page_content=f"Extra {i} doc {j}", metadata={"url": f"https://extra{i}.com/doc{j}"})
                for j in range(10)
            ]
            for i in range(5)
        ]

        # 混合操作：50个读 + 5个写
        read_tasks = [manager._get_cached_bm25_retriever(mock_documents) for _ in range(50)]
        write_tasks = [manager._get_cached_bm25_retriever(docs) for docs in doc_sets]

        all_tasks = read_tasks + write_tasks
        await asyncio.gather(*all_tasks)

        # 验证：无异常，统计正确
        assert manager.bm25_cache_stats.hits >= 50  # 至少50个缓存命中
        assert manager.bm25_cache_stats.total_requests == 56

    @pytest.mark.asyncio
    async def test_stress_test_1000_concurrent(self, mock_documents):
        """压力测试：1000个并发请求"""
        manager = RetrieverManager()

        # 预热
        await manager._get_cached_bm25_retriever(mock_documents)
        manager.bm25_cache_stats.hits = 0

        # 1000个并发请求
        tasks = [manager._get_cached_bm25_retriever(mock_documents) for _ in range(1000)]

        import time

        start = time.perf_counter()
        retrievers = await asyncio.gather(*tasks)
        elapsed_ms = (time.perf_counter() - start) * 1000

        # 验证正确性
        assert manager.bm25_cache_stats.hits == 1000
        assert all(r is retrievers[0] for r in retrievers)

        # 性能要求：1000个请求应在500ms内完成
        print(f"\n1000个并发请求耗时: {elapsed_ms:.2f}ms")
        assert elapsed_ms < 500, f"性能不足：{elapsed_ms:.2f}ms > 500ms"

    @pytest.mark.asyncio
    async def test_race_condition_detection(self):
        """竞态条件检测：多协程同时构建同一索引"""
        manager = RetrieverManager()

        # 使用相同的文档集
        docs = [
            Document(page_content=f"Same doc {i}", metadata={"url": f"https://same.com/doc{i}"}) for i in range(100)
        ]

        # 10个协程同时构建索引（理论上只应构建1次）
        tasks = [manager._get_cached_bm25_retriever(docs) for _ in range(10)]
        retrievers = await asyncio.gather(*tasks)

        # 验证：只构建了1次索引（1次miss，9次hit）
        assert manager.bm25_cache_stats.misses == 1, "索引被重复构建，存在竞态条件！"
        assert manager.bm25_cache_stats.hits == 9

        # 验证：返回同一实例
        assert all(r is retrievers[0] for r in retrievers)

    @pytest.mark.asyncio
    async def test_cache_consistency_under_load(self):
        """负载下的缓存一致性测试"""
        manager = RetrieverManager()

        # 创建10组文档
        doc_sets = {
            f"set{i}": [
                Document(page_content=f"Set {i} doc {j}", metadata={"url": f"https://set{i}.com/doc{j}"})
                for j in range(10)
            ]
            for i in range(10)
        }

        # 并发访问：每组文档被访问10次
        tasks = []
        for _ in range(10):
            for docs in doc_sets.values():
                tasks.append(manager._get_cached_bm25_retriever(docs))

        await asyncio.gather(*tasks)

        # 验证：缓存大小符合LRU限制
        assert len(manager._bm25_cache) <= 10

        # 验证：total_cached_docs与实际缓存一致
        actual_docs = sum(manager._bm25_cache_doc_counts.values())
        assert manager.bm25_cache_stats.total_cached_docs == actual_docs, "缓存统计不一致！"
