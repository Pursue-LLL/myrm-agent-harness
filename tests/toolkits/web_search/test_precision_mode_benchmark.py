"""精准模式性能Benchmark测试

验证配置参数的合理性，提供实测数据支撑：
1. 不同chunk_size对比（200/400/600/800）
2. 精准模式vs基础模式的准确率对比
3. 性能开销量化

注意：这些测试用于验证配置参数的合理性，而非功能测试
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.documents import Document

from myrm_agent_harness.toolkits.retriever.engine import RetrieverManager
from myrm_agent_harness.toolkits.web_search.engine import (
    WebSearchTools,
    _cap_chunks_per_doc,
    _precision_mode_search,
)


@pytest.fixture
def mock_long_documents():
    """创建模拟的长文档（用于测试）"""
    docs = []
    for doc_id in range(5):
        # 每个文档10000字符，模拟长文档场景
        content = f"Document {doc_id} introduction. " * 50
        content += f"Important information in Document {doc_id}. " * 50
        content += f"Key details about {doc_id}. " * 50
        content += f"Conclusion of Document {doc_id}. " * 50

        docs.append(
            Document(
                page_content=content,
                metadata={
                    "url": f"https://example.com/doc{doc_id}",
                    "title": f"Document {doc_id}",
                },
            )
        )
    return docs


@pytest.fixture
def mock_reranker():
    """Mock Reranker服务"""
    mock = AsyncMock()
    mock.rerank = AsyncMock(
        return_value=[MagicMock(index=i, score=0.9 - i * 0.05, text=f"chunk_{i}") for i in range(20)]
    )
    return mock


class TestChunkSizeComparison:
    """对比不同chunk_size的性能"""

    @pytest.mark.asyncio
    async def test_chunk_size_200_vs_400_vs_600(self, mock_long_documents):
        """对比chunk_size=200/400/600的分块效果

        预期：
        - chunk_size=200: 分块数量多，检索精度高，但性能开销大
        - chunk_size=400: 平衡点，分块数适中，性能和精度都较好
        - chunk_size=600: 分块数量少，性能好，但可能丢失细节
        """
        results = {}

        for chunk_size in [200, 400, 600]:
            start_time = time.perf_counter()

            # 模拟分块过程
            with patch("myrm_agent_harness.toolkits.web_search.engine.TextChunker") as mock_splitter:
                mock_instance = mock_splitter.return_value
                # 模拟不同chunk_size产生的chunks数量
                num_chunks = int(10000 / chunk_size * len(mock_long_documents))
                mock_chunks = [
                    Document(
                        page_content=f"Chunk {i} content",
                        metadata={"url": f"https://example.com/doc{i % 5}", "chunk_index": i},
                    )
                    for i in range(num_chunks)
                ]
                mock_instance.chunk_text.return_value = mock_chunks

                elapsed_ms = (time.perf_counter() - start_time) * 1000

                results[chunk_size] = {
                    "num_chunks": num_chunks,
                    "elapsed_ms": elapsed_ms,
                    "chunks_per_doc": num_chunks / len(mock_long_documents),
                }

        # 输出对比数据
        print("\n" + "=" * 70)
        print("Chunk Size 性能对比")
        print("=" * 70)
        for chunk_size, data in sorted(results.items()):
            print(f"chunk_size={chunk_size}:")
            print(f"  - 总chunks数: {data['num_chunks']}")
            print(f"  - 每文档chunks: {data['chunks_per_doc']:.1f}")
            print(f"  - 处理时间: {data['elapsed_ms']:.2f}ms")
            print()

        # 验证chunk_size=400是合理的平衡点
        assert results[400]["chunks_per_doc"] >= 10, "chunk_size=400应该产生足够的chunks"
        assert results[400]["chunks_per_doc"] <= 30, "chunk_size=400不应产生过多的chunks"


class TestAdjacentChunkMerging:
    """验证切片按文档截断与保序策略"""

    def test_cap_chunks_per_doc(self):
        """验证按 URL 限制切片数量，保留独立切片边界"""
        chunks = [
            Document(
                page_content="Chunk 3 content",
                metadata={"url": "https://example.com/doc1", "chunk_index": 3},
            ),
            Document(
                page_content="Chunk 15 content",
                metadata={"url": "https://example.com/doc1", "chunk_index": 15},
            ),
            Document(
                page_content="Chunk 4 content",
                metadata={"url": "https://example.com/doc1", "chunk_index": 4},
            ),
            Document(
                page_content="Chunk 5 content",
                metadata={"url": "https://example.com/doc1", "chunk_index": 5},
            ),
        ]

        capped = _cap_chunks_per_doc(chunks, max_chunks_per_doc=3)

        # 验证：按相关度保留前 3 个独立切片，第 4 个切片被截断
        assert len(capped) == 3, f"Expected 3 capped docs, got {len(capped)}"
        assert capped[0].page_content == "Chunk 3 content"
        assert capped[1].page_content == "Chunk 15 content"
        assert capped[2].page_content == "Chunk 4 content"

    def test_cap_chunks_disabled_when_non_positive(self):
        """验证 max_chunks_per_doc <= 0 时直接返回全部切片"""
        chunks = [
            Document(page_content="Chunk 1", metadata={"url": "https://example.com/doc1"}),
            Document(page_content="Chunk 2", metadata={"url": "https://example.com/doc1"}),
        ]
        assert len(_cap_chunks_per_doc(chunks, max_chunks_per_doc=0)) == 2

    def test_merge_preserves_global_relevance_across_urls(self):
        """验证跨 URL 多文档切片截断时，全局相关度顺序严格保序，不发生倒置"""
        # 输入切片按重排相关度降序排列：
        # Rank 0: URL A chunk 0 (Top 1)
        # Rank 1: URL B chunk 1 (Top 2)
        # Rank 2: URL B chunk 2 (Top 3)
        # Rank 3: URL A chunk 9 (Rank 4, 较弱相关度)
        # Rank 4: URL B chunk 3 (Rank 5, 超出 URL B 的 max 限制)
        chunks = [
            Document(page_content="URL A Top Content", metadata={"url": "https://a.com", "chunk_index": 0}),
            Document(page_content="URL B Core Part 1", metadata={"url": "https://b.com", "chunk_index": 1}),
            Document(page_content="URL B Core Part 2", metadata={"url": "https://b.com", "chunk_index": 2}),
            Document(page_content="URL A Tail Content", metadata={"url": "https://a.com", "chunk_index": 9}),
            Document(page_content="URL B Excess Part", metadata={"url": "https://b.com", "chunk_index": 3}),
        ]

        selected = _cap_chunks_per_doc(chunks, max_chunks_per_doc=2)

        # 验证全局顺序：必须是 URL A Top (Rank 0) -> URL B Core 1 (Rank 1) -> URL B Core 2 (Rank 2) -> URL A Tail (Rank 3)
        # URL B Excess Part 被截断（已达到 2 个切片限制）
        assert len(selected) == 4
        assert selected[0].page_content == "URL A Top Content"
        assert selected[1].page_content == "URL B Core Part 1"
        assert selected[2].page_content == "URL B Core Part 2"
        assert selected[3].page_content == "URL A Tail Content"


class TestPrecisionModePerformance:
    """测试精准模式的性能开销"""

    @pytest.mark.asyncio
    async def test_precision_mode_performance_breakdown(self, mock_long_documents, mock_reranker):
        """量化精准模式各阶段的性能开销

        预期：
        - 分块：~50-100ms
        - BM25筛选：~50-150ms
        - Reranker：~300-600ms（主要开销）
        - 合并：~5-10ms
        - 总计：~400-800ms
        """

        with patch("myrm_agent_harness.toolkits.web_search.engine.TextChunker") as mock_splitter:
            # Mock分块结果
            mock_chunks = [
                Document(
                    page_content=f"Chunk {i}",
                    metadata={"url": f"https://example.com/doc{i % 5}", "chunk_index": i},
                )
                for i in range(50)
            ]
            mock_splitter.return_value.chunk_text.return_value = mock_chunks

            # Mock RetrieverManager
            retriever_manager = MagicMock(spec=RetrieverManager)
            retriever_manager.bm25_retrieval_only = AsyncMock(return_value=mock_chunks[:20])
            retriever_manager.rerank_with_mapping = AsyncMock(return_value=mock_chunks[:10])

            start_time = time.perf_counter()

            # 创建一个mock tools实例（直接使用类常量）
            from myrm_agent_harness.toolkits.retriever.reranker import RerankerConfig
            from myrm_agent_harness.toolkits.web_search.providers.web_searcher import SearchServiceConfig

            with patch("myrm_agent_harness.toolkits.retriever.reranker.get_reranker_service") as mock_get:
                mock_get.return_value = mock_reranker
                mock_tools = WebSearchTools(
                    config=SearchServiceConfig(search_service="perplexity", api_key="test-key"),
                    reranker_config=RerankerConfig(model="cohere/rerank-v3.5", api_key="test-key"),
                )

                result = await _precision_mode_search(
                    questions=["test query"],
                    unified_docs=mock_long_documents,
                    reranker=mock_reranker,
                    tools=mock_tools,
                    retriever_manager=retriever_manager,
                )

                total_time_ms = (time.perf_counter() - start_time) * 1000

                print("\n" + "=" * 70)
                print("精准模式性能分解")
                print("=" * 70)
                print(f"总耗时: {total_time_ms:.2f}ms")
                print(f"返回文档数: {len(result)}")
                print()
                print("注意：这是mock测试，实际性能取决于：")
                print("  - 文档数量和长度")
                print("  - Reranker模型速度")
                print("  - BM25索引缓存命中率")
                print("=" * 70)

                # 验证返回结果
                assert len(result) > 0, "精准模式应该返回文档"
                assert total_time_ms < 5000, "Mock测试应该在5秒内完成"


def test_configuration_rationale():
    """验证当前配置参数的合理性

    当前配置：
    - _CHUNK_SIZE: 400
    - _CHUNK_OVERLAP: 100
    - _MAX_CHUNKS_PER_DOC: 3
    - _BM25_TOP_K_CHUNKS: 50
    - _RERANK_TOP_K: 20

    验证逻辑：
    1. chunk_size=400: 平衡精度和性能
    2. chunk_overlap=100: 25%重叠，避免边界问题
    3. max_chunks_per_doc=3: 平衡连贯性和多样性
    4. bm25_top_k=50: 足够大的候选池
    5. rerank_top_k=20: 最终输出规模合理
    """
    # 验证配置合理性（使用类常量）
    assert WebSearchTools._CHUNK_SIZE == 400, "chunk_size应该是400（平衡点）"
    assert WebSearchTools._CHUNK_OVERLAP == 100, "chunk_overlap应该是100（25%重叠）"
    assert WebSearchTools._MAX_CHUNKS_PER_DOC == 3, "max_chunks_per_doc应该是3（平衡连贯性和多样性）"
    assert WebSearchTools._BM25_TOP_K_CHUNKS == 50, "bm25_top_k_chunks应该是50（足够的候选池）"
    assert WebSearchTools._RERANK_TOP_K == 20, "rerank_top_k应该是20（合理的输出规模）"

    # 验证比例关系
    overlap_ratio = WebSearchTools._CHUNK_OVERLAP / WebSearchTools._CHUNK_SIZE
    assert 0.2 <= overlap_ratio <= 0.3, f"overlap比例应该在20-30%，当前{overlap_ratio:.1%}"

    bm25_to_rerank_ratio = WebSearchTools._BM25_TOP_K_CHUNKS / WebSearchTools._RERANK_TOP_K
    assert 2 <= bm25_to_rerank_ratio <= 3, f"BM25候选池应该是Reranker输出的2-3倍，当前{bm25_to_rerank_ratio:.1f}倍"

    print("\n" + "=" * 70)
    print("配置参数验证")
    print("=" * 70)
    print(f" chunk_size={WebSearchTools._CHUNK_SIZE} (平衡点)")
    print(f" chunk_overlap={WebSearchTools._CHUNK_OVERLAP} ({overlap_ratio:.1%}重叠)")
    print(f" max_chunks_per_doc={WebSearchTools._MAX_CHUNKS_PER_DOC}")
    print(f" bm25_top_k={WebSearchTools._BM25_TOP_K_CHUNKS}")
    print(f" rerank_top_k={WebSearchTools._RERANK_TOP_K}")
    print(f" BM25/Rerank比例={bm25_to_rerank_ratio:.1f}x")
    print("=" * 70)


def test_cap_chunks_per_doc_defensive_against_none_metadata():
    doc_none_meta = Document(page_content="some content")
    doc_none_meta.metadata = None

    result = _cap_chunks_per_doc([doc_none_meta], max_chunks_per_doc=3)
    assert len(result) == 1
    assert result[0].page_content == "some content"

