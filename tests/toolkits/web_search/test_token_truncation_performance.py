"""Token截断性能基准测试

验证 truncate_text_to_tokens 的性能特征。
"""

import time

from langchain_core.documents import Document

from myrm_agent_harness.utils.text_utils import truncate_text_to_tokens


class TestTokenTruncationPerformance:
    """Token截断性能测试"""

    def test_encoding_count_verification(self):
        """验证编码调用次数（通过计时验证）"""
        # 准备测试文本（1000字符，约250 tokens）
        text = "This is a test sentence for token truncation. " * 20

        # 测试：需要截断的情况（100 tokens）
        iterations = 100
        start = time.perf_counter()
        for _ in range(iterations):
            result = truncate_text_to_tokens(text, max_tokens=100)
        elapsed = time.perf_counter() - start

        avg_time_ms = (elapsed / iterations) * 1000

        # 验证结果正确性
        assert len(result) > 0
        assert len(result) < len(text)

        # 性能基准：单次截断应在合理时间内完成
        # 典型值：1-5ms（取决于机器性能）
        assert avg_time_ms < 20, f"Average time {avg_time_ms:.2f}ms exceeds threshold"

        print(f"\n Token truncation performance: {avg_time_ms:.2f}ms per call")

    def test_no_truncation_fast_path(self):
        """验证不需要截断时的快速路径"""
        text = "Short text."

        iterations = 1000
        start = time.perf_counter()
        for _ in range(iterations):
            result = truncate_text_to_tokens(text, max_tokens=100)
        elapsed = time.perf_counter() - start

        avg_time_ms = (elapsed / iterations) * 1000

        # 不需要截断时应该非常快（只需encode一次判断）
        assert avg_time_ms < 2, f"Fast path too slow: {avg_time_ms:.2f}ms"
        assert result == text

        print(f"\n Fast path (no truncation): {avg_time_ms:.2f}ms per call")

    def test_large_text_truncation(self):
        """测试大文本截断性能"""
        # 10000字符（约2500 tokens）
        text = "This is a very long document with many sentences. " * 200

        start = time.perf_counter()
        result = truncate_text_to_tokens(text, max_tokens=500)
        elapsed = time.perf_counter() - start

        elapsed_ms = elapsed * 1000

        # 大文本截断应在合理时间内完成
        assert elapsed_ms < 50, f"Large text truncation too slow: {elapsed_ms:.2f}ms"
        assert len(result) < len(text)

        print(f"\n Large text truncation (10K chars -> 500 tokens): {elapsed_ms:.2f}ms")

    def test_batch_truncation_performance(self):
        """测试批量截断性能（模拟实际使用场景）"""
        # 模拟10个搜索结果文档
        docs = [
            Document(
                page_content="This is search result content. " * 50,
                metadata={"url": f"https://example.com/{i}"},
            )
            for i in range(10)
        ]

        start = time.perf_counter()
        results = []
        for doc in docs:
            truncated = truncate_text_to_tokens(doc.page_content, max_tokens=100)
            results.append(truncated)
        elapsed = time.perf_counter() - start

        total_ms = elapsed * 1000
        per_doc_ms = total_ms / len(docs)

        # 批量处理应保持高效
        assert total_ms < 100, f"Batch truncation too slow: {total_ms:.2f}ms"
        assert len(results) == 10

        print(f"\n Batch truncation (10 docs): {total_ms:.2f}ms total, {per_doc_ms:.2f}ms per doc")

    def test_encoding_consistency(self):
        """验证编码一致性（相同输入产生相同输出）"""
        text = "Consistency test. " * 100

        # 多次调用应产生完全相同的结果
        results = [truncate_text_to_tokens(text, max_tokens=100) for _ in range(10)]

        # 所有结果应完全一致
        assert all(r == results[0] for r in results), "Inconsistent truncation results"
        assert len(results[0]) > 0

        print("\n Encoding consistency verified (10 iterations)")
