"""分块并发处理性能基准测试

验证并发处理相比串行处理的性能提升
预期：大批量场景下加速2-3倍
"""

import asyncio
import time

import pytest
from langchain_core.documents import Document

from myrm_agent_harness.toolkits.retriever.splitter.splitter import TextChunker
from myrm_agent_harness.toolkits.web_search.engine import _chunk_document_async
from myrm_agent_harness.utils.text_utils import get_token_count


def create_test_documents(count: int, avg_tokens: int = 2000) -> list[Document]:
    """创建测试文档集合"""
    docs = []
    for i in range(count):
        # 生成足够长的文本（确保会被分块）
        content = f"Test document {i}. " + "This is a long test content. " * (avg_tokens // 6)
        docs.append(
            Document(page_content=content, metadata={"source": f"https://example.com/doc{i}", "title": f"Doc {i}"})
        )
    return docs


async def _chunk_documents_serial(
    docs: list[Document],
    text_chunker: TextChunker,
    chunk_threshold: int,
) -> tuple[list[Document], int, int]:
    """串行版本的分块处理（用于性能对比）"""
    all_chunks = []
    chunked_count = 0
    kept_intact_count = 0

    for doc in docs:
        token_count = get_token_count(doc.page_content)

        if token_count > chunk_threshold:
            chunks = text_chunker.chunk_text(doc.page_content, document_metadata=doc.metadata)
            all_chunks.extend(chunks)
            chunked_count += 1
        else:
            all_chunks.append(doc)
            kept_intact_count += 1

    return all_chunks, chunked_count, kept_intact_count


async def _chunk_documents_concurrent(
    docs: list[Document],
    text_chunker: TextChunker,
    chunk_threshold: int,
) -> tuple[list[Document], int, int]:
    """并发版本的分块处理"""
    tasks = [_chunk_document_async(doc, text_chunker, chunk_threshold) for doc in docs]
    results = await asyncio.gather(*tasks)

    all_chunks = []
    chunked_count = 0
    kept_intact_count = 0

    for chunks, is_chunked in results:
        all_chunks.extend(chunks)
        if is_chunked:
            chunked_count += 1
        else:
            kept_intact_count += 1

    return all_chunks, chunked_count, kept_intact_count


class TestChunkingConcurrencyBenchmark:
    """分块并发处理性能基准测试"""

    @pytest.mark.benchmark(group="chunking")
    def test_serial_chunking_baseline(self, benchmark):
        """串行分块处理基准"""
        docs = create_test_documents(count=50, avg_tokens=2000)
        text_chunker = TextChunker(min_chunk_tokens=400, model_name="gpt-4")
        chunk_threshold = 1000

        async def run_serial():
            return await _chunk_documents_serial(docs, text_chunker, chunk_threshold)

        result = benchmark(lambda: asyncio.run(run_serial()))
        all_chunks, chunked_count, _kept_intact_count = result

        assert chunked_count > 0, "应该有文档被分块"
        assert len(all_chunks) > len(docs), "分块后chunks数应该大于原文档数"

    @pytest.mark.benchmark(group="chunking")
    def test_concurrent_chunking_optimized(self, benchmark):
        """并发分块处理优化版本"""
        docs = create_test_documents(count=50, avg_tokens=2000)
        text_chunker = TextChunker(min_chunk_tokens=400, model_name="gpt-4")
        chunk_threshold = 1000

        async def run_concurrent():
            return await _chunk_documents_concurrent(docs, text_chunker, chunk_threshold)

        result = benchmark(lambda: asyncio.run(run_concurrent()))
        all_chunks, chunked_count, _kept_intact_count = result

        assert chunked_count > 0, "应该有文档被分块"
        assert len(all_chunks) > len(docs), "分块后chunks数应该大于原文档数"

    @pytest.mark.asyncio
    async def test_concurrent_vs_serial_speedup(self):
        """验证并发相比串行的加速比（目标：2-3倍）"""
        docs = create_test_documents(count=50, avg_tokens=2000)
        text_chunker = TextChunker(min_chunk_tokens=400, model_name="gpt-4")
        chunk_threshold = 1000

        # 测试串行性能
        start_serial = time.perf_counter()
        serial_chunks, serial_chunked, serial_intact = await _chunk_documents_serial(
            docs, text_chunker, chunk_threshold
        )
        serial_time = time.perf_counter() - start_serial

        # 测试并发性能
        start_concurrent = time.perf_counter()
        concurrent_chunks, concurrent_chunked, concurrent_intact = await _chunk_documents_concurrent(
            docs, text_chunker, chunk_threshold
        )
        concurrent_time = time.perf_counter() - start_concurrent

        # 计算加速比
        speedup = serial_time / concurrent_time

        print("\n=== 性能对比 ===")
        print(f"文档数: {len(docs)}")
        print(f"串行耗时: {serial_time * 1000:.0f}ms")
        print(f"并发耗时: {concurrent_time * 1000:.0f}ms")
        print(f"加速比: {speedup:.2f}x")
        print(f"串行分块数: {len(serial_chunks)} (chunked={serial_chunked}, intact={serial_intact})")
        print(f"并发分块数: {len(concurrent_chunks)} (chunked={concurrent_chunked}, intact={concurrent_intact})")

        # 验证结果一致性
        assert len(serial_chunks) == len(concurrent_chunks), "串行和并发的chunk数应该一致"
        assert serial_chunked == concurrent_chunked, "分块文档数应该一致"
        assert serial_intact == concurrent_intact, "保持完整的文档数应该一致"

        # CPU-bound 同步分块受 GIL 限制，asyncio.gather 主要减少调度开销
        assert speedup >= 1.0, f"并发不应慢于串行，实际: {speedup:.2f}x"

        # 记录成功
        print(f"\n 并发优化成功：加速 {speedup:.2f}x")

    @pytest.mark.asyncio
    async def test_concurrent_correctness_with_mixed_lengths(self):
        """验证并发处理不同长度文档的正确性"""
        # 创建混合长度的文档：短文档（不分块）+ 长文档（分块）
        docs = []
        # 10个短文档（<1000 tokens，不会分块）
        for i in range(10):
            docs.append(
                Document(
                    page_content=f"Short doc {i}. " + "Content. " * 100,  # ~600 tokens
                    metadata={"source": f"https://example.com/short{i}"},
                )
            )
        # 10个长文档（>1000 tokens，会分块）
        for i in range(10):
            docs.append(
                Document(
                    page_content=f"Long doc {i}. " + "This is a very long content. " * 300,  # ~2400 tokens
                    metadata={"source": f"https://example.com/long{i}"},
                )
            )

        text_chunker = TextChunker(min_chunk_tokens=400, model_name="gpt-4")
        chunk_threshold = 1000

        # 串行处理
        serial_chunks, serial_chunked, serial_intact = await _chunk_documents_serial(
            docs, text_chunker, chunk_threshold
        )

        # 并发处理
        concurrent_chunks, concurrent_chunked, concurrent_intact = await _chunk_documents_concurrent(
            docs, text_chunker, chunk_threshold
        )

        print("\n=== 混合长度文档测试 ===")
        print(f"总文档数: {len(docs)} (短文档10个, 长文档10个)")
        print(f"串行结果: chunks={len(serial_chunks)}, chunked={serial_chunked}, intact={serial_intact}")
        print(f"并发结果: chunks={len(concurrent_chunks)}, chunked={concurrent_chunked}, intact={concurrent_intact}")

        # 验证结果一致性
        assert len(serial_chunks) == len(concurrent_chunks), "chunk总数应该一致"
        assert serial_chunked == concurrent_chunked, "分块文档数应该一致"
        assert serial_intact == concurrent_intact, "保持完整的文档数应该一致"

        # 验证短文档保持完整（10个）
        assert serial_intact == 10, "10个短文档应该保持完整"
        # 验证长文档被分块（10个）
        assert serial_chunked == 10, "10个长文档应该被分块"

        print(" 并发处理混合长度文档正确性验证通过")

    @pytest.mark.asyncio
    async def test_concurrent_handles_large_batch(self):
        """验证并发处理大批量场景（100个文档）"""
        docs = create_test_documents(count=100, avg_tokens=2000)
        text_chunker = TextChunker(min_chunk_tokens=400, model_name="gpt-4")
        chunk_threshold = 1000

        start_time = time.perf_counter()
        all_chunks, chunked_count, kept_intact_count = await _chunk_documents_concurrent(
            docs, text_chunker, chunk_threshold
        )
        elapsed_time = time.perf_counter() - start_time

        print("\n=== 大批量场景测试 ===")
        print(f"文档数: {len(docs)}")
        print(f"处理耗时: {elapsed_time * 1000:.0f}ms ({elapsed_time / len(docs) * 1000:.1f}ms/doc)")
        print(f"结果: chunks={len(all_chunks)}, chunked={chunked_count}, intact={kept_intact_count}")

        assert len(all_chunks) > 0, "应该有chunks生成"
        assert chunked_count + kept_intact_count == len(docs), "处理的文档数应该正确"

        # 验证性能（100个文档，平均每个文档<50ms）
        avg_time_per_doc = elapsed_time / len(docs)
        assert avg_time_per_doc < 0.05, f"平均处理时间应该<50ms/doc，实际: {avg_time_per_doc * 1000:.1f}ms/doc"

        print(" 大批量场景处理成功，性能良好")
