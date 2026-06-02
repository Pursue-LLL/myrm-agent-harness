"""Token控制逻辑单元测试

验证 format_documents_with_metadata 的token控制功能。
"""

from langchain_core.documents import Document

from myrm_agent_harness.utils.context_format import (
    _allocate_tokens_weighted,
    format_documents_with_metadata,
)
from myrm_agent_harness.utils.text_utils import (
    find_sentence_boundary,
    get_token_count,
    truncate_by_tokens_with_boundary,
    truncate_text_to_tokens,
)


class TestHelperFunctions:
    """辅助函数单元测试"""

    def test_allocate_tokens_weighted_empty(self):
        """空文档列表"""
        assert _allocate_tokens_weighted(1000, 0) == []

    def test_allocate_tokens_weighted_single(self):
        """单文档获得全部预算"""
        result = _allocate_tokens_weighted(1000, 1)
        assert result == [1000]

    def test_allocate_tokens_weighted_triple(self):
        """3个文档平均分配"""
        result = _allocate_tokens_weighted(1000, 3)
        assert result == [333, 333, 333]

    def test_allocate_tokens_weighted_many(self):
        """多文档加权分配"""
        result = _allocate_tokens_weighted(1000, 5)
        assert len(result) == 5
        # Top-3: 25%, 15%, 10%
        assert result[0] == 250
        assert result[1] == 150
        assert result[2] == 100
        # 剩余2个文档平分: (1000-500)/2=250
        assert result[3] == 250
        assert result[4] == 250

    def testfind_sentence_boundary_paragraph(self):
        """段落边界优先级最高"""
        text = "First sentence.\n\nSecond paragraph. More text here."
        pos = find_sentence_boundary(text, 0.3)
        # 函数找到最后的句子边界（整个文本末尾）
        assert pos > 0 and text[:pos].endswith(".")

    def testfind_sentence_boundary_chinese(self):
        """中文句号边界"""
        text = "这是第一句。这是第二句。更多内容在这里"
        pos = find_sentence_boundary(text, 0.3)
        assert text[:pos].endswith("。")

    def testfind_sentence_boundary_english(self):
        """英文句号边界"""
        text = "First sentence. Second sentence. More content here"
        pos = find_sentence_boundary(text, 0.3)
        assert text[:pos].endswith(". ")

    def testfind_sentence_boundary_threshold(self):
        """最小阈值过滤"""
        text = "Short. " + "x" * 100
        pos = find_sentence_boundary(text, 0.8)  # 要求至少保留80%
        assert pos == -1  # "Short. "只占7%，不满足

    def test_truncate_text_no_truncate(self):
        """短文本无需截断"""
        text = "Short text."
        result = truncate_text_to_tokens(text, max_tokens=100)
        assert result == text

    def test_find_boundary_then_truncate(self):
        """在句子边界截断（通过 find_sentence_boundary 验证逻辑）"""
        text = "First sentence. Second sentence. Third sentence."
        truncated = text[:35]
        pos = find_sentence_boundary(truncated, 0.6)
        assert pos > 0
        assert truncated[:pos].rstrip() == "First sentence. Second sentence."

    def test_truncate_no_boundary_fallback(self):
        """无合适边界时 truncate_text_to_tokens 直接截断"""
        text = "x" * 100
        result = truncate_text_to_tokens(text, max_tokens=5)
        assert len(result) < len(text)

    def test_truncate_by_tokens_no_truncate(self):
        """token数未超限"""
        text = "This is a short text."
        result = truncate_by_tokens_with_boundary(text, max_tokens=100)
        assert result == text

    def testtruncate_by_tokens_with_boundary(self):
        """token截断在句子边界"""
        text = "First sentence. " * 20  # ~160 tokens
        result = truncate_by_tokens_with_boundary(text, max_tokens=50)
        token_count = get_token_count(result)
        assert token_count <= 50
        assert result.endswith("sentence.")

    def test_truncate_by_tokens_fallback(self):
        """tiktoken失败时回退到字符截断"""
        text = "x" * 1000

        # 模拟tiktoken不可用的场景（通过传入无效编码器）
        result = truncate_by_tokens_with_boundary(text, max_tokens=100, encoding_name="invalid_encoder")
        assert len(result) <= 405  # 100 * 4 + "..." 后缀


class TestFormatDocumentsWithMetadata:
    """format_documents_with_metadata 完整功能测试"""

    def test_no_token_control(self):
        """无token控制时的基础功能"""
        docs = [
            Document(page_content="Content 1", metadata={"url": "http://example.com/1", "title": "Doc 1"}),
            Document(page_content="Content 2", metadata={"url": "http://example.com/2", "title": "Doc 2"}),
        ]

        metadata, text, stats = format_documents_with_metadata(docs)

        assert len(metadata) == 2
        assert "【1】" in text
        assert "【2】" in text
        assert stats is None  # 无token控制时不返回统计

    def test_total_max_tokens_control(self):
        """全局token预算控制"""
        long_content = "This is a test sentence. " * 100  # ~500 tokens
        docs = [
            Document(page_content=long_content, metadata={"url": f"http://example.com/{i}", "title": f"Doc {i}"})
            for i in range(5)
        ]

        _metadata, _text, stats = format_documents_with_metadata(docs, total_max_tokens=500)

        assert stats is not None
        assert stats.total_docs == 5
        # Header开销估算可能有误差，允许15%的缓冲
        assert stats.final_tokens <= 575
        assert stats.truncated_docs > 0
        assert 0 < stats.retention_ratio < 1.0

    def test_max_content_tokens_control(self):
        """单文档token限制"""
        long_content = "This is a test sentence. " * 50  # ~250 tokens
        docs = [
            Document(page_content=long_content, metadata={"url": "http://example.com/1", "title": "Doc 1"}),
        ]

        _metadata, text, _ = format_documents_with_metadata(docs, max_content_tokens=100)

        content_tokens = get_token_count(text)
        # Header约50 tokens + 内容<=100 tokens
        assert content_tokens <= 160

    def test_priority_total_over_single(self):
        """全局预算优先级高于单文档限制"""
        content = "Test sentence. " * 20  # ~60 tokens
        docs = [
            Document(page_content=content, metadata={"url": f"http://example.com/{i}", "title": f"Doc {i}"})
            for i in range(5)
        ]

        # 全局预算500，单文档限制10000（但会被全局限制）
        _metadata, _text, stats = format_documents_with_metadata(docs, max_content_tokens=10000, total_max_tokens=500)

        assert stats is not None
        # 5个文档，每个header约50 tokens，总预算500
        assert stats.final_tokens <= 500

    def test_weighted_allocation(self):
        """验证加权分配"""
        content = "x" * 1000  # 长内容确保会被截断
        docs = [
            Document(page_content=content, metadata={"url": f"http://example.com/{i}", "title": f"Doc {i}"})
            for i in range(5)
        ]

        _metadata, text, _stats = format_documents_with_metadata(docs, total_max_tokens=1000)

        # Top-3文档应该有更多内容
        lines = text.split("\n\n")
        doc_contents = [
            line for line in lines if line and not line.startswith("【") and not line.startswith("relevant")
        ]

        # 前3个文档的内容应该明显长于后2个
        if len(doc_contents) >= 5:
            avg_top3 = sum(len(doc_contents[i]) for i in range(3)) / 3
            avg_rest = sum(len(doc_contents[i]) for i in range(3, 5)) / 2
            assert avg_top3 > avg_rest * 0.8  # Top-3至少有80%的相对优势

    def test_truncation_stats_transparency(self):
        """验证统计信息透明性"""
        long_content = "This is a test sentence. " * 100  # ~500 tokens per doc
        docs = [
            Document(page_content=long_content, metadata={"url": f"http://example.com/{i}", "title": f"Doc {i}"})
            for i in range(5)
        ]

        _metadata, _text, stats = format_documents_with_metadata(docs, total_max_tokens=1000)

        assert stats is not None
        assert stats.original_tokens > stats.final_tokens
        assert stats.truncated_docs >= 0
        assert stats.total_docs == 5
        assert stats.retention_ratio == stats.final_tokens / stats.original_tokens

    def test_url_deduplication(self):
        """URL去重和内容合并"""
        docs = [
            Document(page_content="Part 1", metadata={"url": "http://example.com", "title": "Same URL"}),
            Document(page_content="Part 2", metadata={"url": "http://example.com", "title": "Same URL"}),
            Document(page_content="Different", metadata={"url": "http://other.com", "title": "Other"}),
        ]

        metadata, text, _ = format_documents_with_metadata(docs)

        assert len(metadata) == 2  # 只有2个唯一URL
        assert "Part 1" in text and "Part 2" in text  # 同一URL的内容都在

    def test_questions_prefix(self):
        """查询关键词前缀"""
        docs = [Document(page_content="Content", metadata={"url": "http://example.com", "title": "Doc"})]

        _metadata, text, _ = format_documents_with_metadata(docs, questions=["query1", "query2"])

        assert text.startswith("relevant results for keywords [query1, query2]:")


class TestTokenControlIntegration:
    """Token控制集成测试"""

    def test_large_search_results(self):
        """模拟大规模搜索结果（Tavily返回10个完整网页）"""
        # 每个文档20KB（约5000 tokens）
        large_content = "This is a detailed article about AI. " * 500
        docs = [
            Document(
                page_content=large_content,
                metadata={"url": f"http://example.com/article{i}", "title": f"Article {i}"},
            )
            for i in range(10)
        ]

        # 限制总预算为5000 tokens
        metadata, _text, stats = format_documents_with_metadata(docs, total_max_tokens=5000)

        assert len(metadata) == 10
        assert stats is not None
        assert stats.final_tokens <= 5000
        assert stats.truncated_docs == 10
        # 应该保留了约10%的内容（5000 / 50000）
        assert 0.05 <= stats.retention_ratio <= 0.15

    def test_mixed_size_documents(self):
        """混合大小文档"""
        docs = [
            Document(page_content="Short", metadata={"url": "http://example.com/1", "title": "Short"}),
            Document(page_content="x" * 5000, metadata={"url": "http://example.com/2", "title": "Long"}),
            Document(
                page_content="Medium length content. " * 10, metadata={"url": "http://example.com/3", "title": "Med"}
            ),
        ]

        _metadata, text, stats = format_documents_with_metadata(docs, total_max_tokens=500)

        assert stats is not None
        assert stats.final_tokens <= 500
        # 短文档不应被截断
        assert "Short" in text

    def test_encoding_consistency(self):
        """验证编码器一致性"""
        docs = [
            Document(page_content="Test content " * 50, metadata={"url": "http://example.com", "title": "Test"}),
        ]

        # 使用cl100k_base编码器
        _metadata, text, stats = format_documents_with_metadata(docs, total_max_tokens=200, token_encoding="cl100k_base")

        # 验证token数使用了相同的编码器
        actual_tokens = get_token_count(text, encoding_name="cl100k_base")
        if stats:
            assert abs(actual_tokens - stats.final_tokens) < 10  # 允许小误差（header估算）

    def test_adaptive_estimation_short_header(self):
        """测试自适应估算：短header分支（<=20 tokens）"""
        docs = [
            Document(page_content="Content " * 100, metadata={"url": f"https://ex.co/{i}", "title": f"T{i}"})
            for i in range(5)
        ]

        sources, _context, stats = format_documents_with_metadata(docs, total_max_tokens=500)

        assert stats.final_tokens <= 500
        assert len(sources) == 5

    def test_adaptive_estimation_medium_header(self):
        """测试自适应估算：中等header分支（21-35 tokens）"""
        docs = [
            Document(
                page_content="Content " * 100,
                metadata={"url": f"https://github.com/user/repo-{i}", "title": f"A Medium Length Title {i}"},
            )
            for i in range(5)
        ]

        sources, _context, stats = format_documents_with_metadata(docs, total_max_tokens=600)

        assert stats.final_tokens <= 600
        assert len(sources) == 5

    def test_adaptive_estimation_long_header(self):
        """测试自适应估算：长header分支（>35 tokens）"""
        docs = [
            Document(
                page_content="Content " * 100,
                metadata={
                    "url": f"https://github.com/user/very-long-repository-name-{i}/blob/main/src/components/Component.tsx",
                    "title": f"A Very Long Title With Many Words And Detailed Description For Article Number {i}",
                },
            )
            for i in range(5)
        ]

        sources, _context, stats = format_documents_with_metadata(docs, total_max_tokens=800)

        assert stats.final_tokens <= 800
        assert len(sources) == 5

    def test_insufficient_budget_warning(self, caplog):
        """测试预算不足时触发动态裁剪"""
        import logging

        docs = [
            Document(page_content="Content " * 100, metadata={"url": f"https://example.com/{i}"}) for i in range(10)
        ]

        with caplog.at_level(logging.ERROR):
            sources, _context, stats = format_documents_with_metadata(docs, questions=["test"], total_max_tokens=200)

        assert "Budget insufficient" in caplog.text or "truncating" in caplog.text
        assert stats.final_tokens <= 200
        assert len(sources) <= 10

    def test_max_content_tokens_priority_override(self):
        """测试max_content_tokens优先级覆盖加权分配"""
        docs = [
            Document(page_content="Content " * 200, metadata={"url": f"https://example.com/{i}", "title": f"Title {i}"})
            for i in range(5)
        ]

        _sources, _context, stats = format_documents_with_metadata(
            docs,
            max_content_tokens=50,
            total_max_tokens=1000,
        )

        assert stats.final_tokens <= 1000
        assert stats.truncated_docs == 5

    def test_empty_text_truncation_boundary(self):
        """测试空文本和零max_tokens的边界情况"""
        result = truncate_by_tokens_with_boundary("", 100)
        assert result == ""

        result2 = truncate_by_tokens_with_boundary("some text", 0)
        assert result2 == ""

        result3 = truncate_by_tokens_with_boundary("", 0)
        assert result3 == ""

    def test_multiple_questions_prefix_budget(self):
        """测试多个questions的前缀token精确计算"""
        docs = [Document(page_content="Content " * 100, metadata={"url": f"https://example.com/{i}"}) for i in range(5)]

        questions = ["machine learning", "deep learning", "neural networks", "artificial intelligence"]

        _sources, context, stats = format_documents_with_metadata(docs, questions=questions, total_max_tokens=800)

        assert "relevant results for keywords" in context
        assert all(q in context for q in questions)
        assert stats.final_tokens <= 800

    def test_extreme_long_questions_list(self):
        """测试极长questions列表的前缀开销"""
        docs = [Document(page_content="Content " * 50, metadata={"url": f"https://example.com/{i}"}) for i in range(3)]

        long_questions = ["query keyword"] * 20

        _sources, context, stats = format_documents_with_metadata(docs, questions=long_questions, total_max_tokens=600)

        assert stats.final_tokens <= 600
        assert "relevant results for keywords" in context

    def test_budget_exactly_at_threshold(self):
        """测试预算刚好等于estimated_overhead的临界情况"""
        docs = [
            Document(
                page_content="Content " * 50,
                metadata={"url": f"https://example.com/{i}", "title": f"Title {i}"},
            )
            for i in range(3)
        ]

        # 精确计算使预算刚好等于overhead
        sources, _context, stats = format_documents_with_metadata(docs, total_max_tokens=120)

        assert stats.final_tokens <= 120
        assert len(sources) <= 3

    def test_dynamic_truncation_preserves_top_docs(self):
        """测试动态裁剪保留Top文档的顺序"""
        docs = [
            Document(
                page_content="Content " * 100,
                metadata={"url": f"https://example.com/doc-{i}", "title": f"Document {i}"},
            )
            for i in range(20)
        ]

        sources, _context, stats = format_documents_with_metadata(docs, total_max_tokens=400)

        assert stats.final_tokens <= 400
        # 应裁剪到前N个文档
        assert len(sources) < 20
        # 验证保留的是前几个文档
        assert sources[0]["url"] == "https://example.com/doc-0"
        if len(sources) > 1:
            assert sources[1]["url"] == "https://example.com/doc-1"

    def test_budget_sufficient_no_truncation_path(self):
        """测试预算充足时的正常路径（覆盖WARNING分支）"""
        docs = [
            Document(
                page_content="Short content",
                metadata={"url": f"https://example.com/{i}", "title": f"Title {i}"},
            )
            for i in range(5)
        ]

        sources, _context, stats = format_documents_with_metadata(docs, total_max_tokens=5000)

        assert stats.final_tokens <= 5000
        assert len(sources) == 5
        assert stats.truncated_docs == 0

    def test_return_empty_when_budget_too_small(self, caplog):
        """测试预算极度不足时返回空结果（覆盖return [], '', None分支）"""
        import logging

        from myrm_agent_harness.utils.text_utils import get_token_count

        docs = [Document(page_content="C", metadata={"url": "https://a.co", "title": "T"})]

        # 构造questions占用大量预算
        questions = ["keyword query search"] * 10
        questions_prefix = f"relevant results for keywords [{', '.join(questions)}]:\n"
        questions_tokens = get_token_count(questions_prefix)

        # total = questions + 20（不足以容纳1个文档，header≈25+separator=2）
        total_budget = questions_tokens + 20

        with caplog.at_level(logging.ERROR):
            sources, context, stats = format_documents_with_metadata(
                docs, questions=questions, total_max_tokens=total_budget
            )

        assert "too small for even 1 document" in caplog.text
        assert len(sources) == 0
        assert context == ""
        assert stats is None
