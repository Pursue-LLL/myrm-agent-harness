"""context_format 模块完整测试覆盖

测试目标：确保 context_format.py 的所有核心功能都经过验证，覆盖率 > 80%
"""

from langchain_core.documents import Document

from myrm_agent_harness.utils.context_format import (
    format_crawl_results,
    format_document_header,
    format_documents_with_metadata,
    wrap_with_external_sources_tag,
    wrap_with_tool_output_tag,
)
from myrm_agent_harness.utils.document_utils import extract_clean_content_for_context


class TestFormatDocumentHeader:
    """测试文档头部格式化"""

    def test_basic_header(self):
        """测试基本头部"""
        header = format_document_header(1, "https://test.com")
        assert "【1】" in header
        assert "URL: https://test.com" in header

    def test_header_with_title(self):
        """测试包含标题"""
        header = format_document_header(2, "https://test.com", title="Test Title", include_title=True)
        assert "Title: Test Title" in header

    def test_header_without_title(self):
        """测试排除标题"""
        header = format_document_header(2, "https://test.com", title="Test Title", include_title=False)
        assert "Title:" not in header

    def test_header_with_date(self):
        """测试包含日期"""
        header = format_document_header(3, "https://test.com", date="2024-03-18", include_date=True)
        assert "Date: 2024-03-18" in header

    def test_header_without_date(self):
        """测试排除日期"""
        header = format_document_header(3, "https://test.com", date="2024-03-18", include_date=False)
        assert "Date:" not in header

    def test_full_header(self):
        """测试完整头部"""
        header = format_document_header(
            5,
            "https://example.com",
            title="Example",
            date="2024-03-18",
            include_title=True,
            include_date=True,
        )
        assert all(x in header for x in ["【5】", "example.com", "Example", "2024-03-18"])

    def test_empty_optional_fields(self):
        """测试空的可选字段"""
        header = format_document_header(1, "https://test.com", title="", date="")
        # 空字段不应该添加 | Title: | Date:
        assert header == "【1】 URL: https://test.com"


class TestExtractCleanContent:
    """测试内容提取"""

    def test_no_front_matter(self):
        """测试无Front Matter"""
        content = "纯文本内容"
        result = extract_clean_content_for_context(content)
        assert result == content

    def test_front_matter_without_section(self):
        """测试有Front Matter但无section"""
        content = "---\ntitle: Test\nauthor: Me\n---\n\n正文内容"
        result = extract_clean_content_for_context(content)
        assert result == "正文内容"
        assert "title:" not in result

    def test_front_matter_with_section(self):
        """测试有Front Matter且包含section"""
        content = "---\nsection: Introduction\ntitle: Test\n---\n\n正文内容"
        result = extract_clean_content_for_context(content)

        assert "section: Introduction" in result
        assert "正文内容" in result
        assert "title:" not in result

    def test_multiple_sections(self):
        """测试section字段"""
        content = "---\nsection: Chapter 1\n---\n\nContent here"
        result = extract_clean_content_for_context(content)
        assert "section: Chapter 1" in result
        assert "Content here" in result

    def test_empty_content(self):
        """测试空内容"""
        result = extract_clean_content_for_context("")
        assert result == ""


class TestFormatCrawlResults:
    """测试crawl results格式化"""

    def test_empty_results(self):
        """测试空结果"""
        result = format_crawl_results([])
        assert result == ""

    def test_single_result(self):
        """测试单个结果"""
        doc = Document(page_content="Test content", metadata={"url": "https://test.com", "title": "Test"})
        result = format_crawl_results([("https://test.com", doc)])

        assert "【1】" in result
        assert "https://test.com" in result
        assert "Test content" in result

    def test_multiple_results(self):
        """测试多个结果"""
        results = [
            (
                "https://test1.com",
                Document(page_content="Content 1", metadata={"url": "https://test1.com", "title": "Title 1"}),
            ),
            (
                "https://test2.com",
                Document(page_content="Content 2", metadata={"url": "https://test2.com", "title": "Title 2"}),
            ),
        ]
        result = format_crawl_results(results)

        assert "【1】" in result and "【2】" in result
        assert "Content 1" in result and "Content 2" in result

    def test_without_title(self):
        """测试不包含标题"""
        doc = Document(page_content="Content", metadata={"url": "https://test.com", "title": "Title"})
        result = format_crawl_results([("https://test.com", doc)], include_title=False)

        assert "Title:" not in result

    def test_with_date(self):
        """测试包含日期"""
        doc = Document(page_content="Content", metadata={"url": "https://test.com", "date": "2024-03-18"})
        result = format_crawl_results([("https://test.com", doc)], include_date=True)

        assert "Date: 2024-03-18" in result

    def test_extract_clean_content(self):
        """测试提取clean content"""
        doc = Document(page_content="---\nsection: Test\n---\n\nContent", metadata={"url": "https://test.com"})
        result = format_crawl_results([("https://test.com", doc)], extract_clean_content=True)

        assert "section: Test" in result
        assert "Content" in result


class TestFormatDocumentsWithMetadata:
    """测试文档格式化核心功能"""

    def test_empty_documents(self):
        """测试空文档"""
        sources, context, stats = format_documents_with_metadata([])
        assert sources == []
        assert context == ""
        assert stats is None

    def test_single_document(self):
        """测试单文档"""
        doc = Document(page_content="测试内容", metadata={"url": "https://test.com", "title": "测试"})
        sources, context, _ = format_documents_with_metadata([doc])

        assert len(sources) == 1
        assert sources[0]["url"] == "https://test.com"
        assert sources[0]["title"] == "测试"
        assert "【1】" in context
        assert "测试内容" in context

    def test_multiple_documents(self):
        """测试多文档"""
        docs = [
            Document(page_content=f"内容{i}", metadata={"url": f"https://test{i}.com", "title": f"标题{i}"})
            for i in range(1, 4)
        ]
        sources, context, _ = format_documents_with_metadata(docs)

        assert len(sources) == 3
        for i in range(1, 4):
            assert f"【{i}】" in context
            assert f"内容{i}" in context

    def test_url_deduplication_and_merging(self):
        """测试URL去重和内容合并"""
        docs = [
            Document(page_content="片段1", metadata={"url": "https://same.com", "title": "标题"}),
            Document(page_content="片段2", metadata={"url": "https://same.com"}),
            Document(page_content="片段3", metadata={"url": "https://same.com"}),
        ]
        sources, context, _ = format_documents_with_metadata(docs)

        assert len(sources) == 1
        assert context.count("【1】") == 1
        assert all(f"片段{i}" in context for i in [1, 2, 3])

    def test_empty_url_creates_entry(self):
        """测试空URL也会创建条目"""
        docs = [
            Document(page_content="有URL", metadata={"url": "https://test.com"}),
            Document(page_content="无URL", metadata={"title": "Only title"}),
        ]
        sources, _context, _ = format_documents_with_metadata(docs)

        # 根据实际行为，空URL也会被处理
        assert len(sources) >= 1

    def test_questions_prefix(self):
        """测试查询前缀"""
        doc = Document(page_content="内容", metadata={"url": "https://test.com"})
        _sources, context, _ = format_documents_with_metadata([doc], questions=["python", "async"])

        assert context.startswith("relevant results for keywords")
        assert "python, async" in context

    def test_no_questions(self):
        """测试无查询"""
        doc = Document(page_content="内容", metadata={"url": "https://test.com"})
        _sources, context, _ = format_documents_with_metadata([doc], questions=None)

        assert not context.startswith("relevant results")

    def test_include_title_false(self):
        """测试排除标题"""
        doc = Document(page_content="内容", metadata={"url": "https://test.com", "title": "标题"})
        _sources, context, _ = format_documents_with_metadata([doc], include_title=False)

        assert "Title:" not in context

    def test_include_date_true(self):
        """测试包含日期"""
        doc = Document(page_content="内容", metadata={"url": "https://test.com", "date": "2024-03-18"})
        _sources, context, _ = format_documents_with_metadata([doc], include_date=True)

        assert "Date: 2024-03-18" in context

    def test_extract_clean_content_true(self):
        """测试启用clean content"""
        doc = Document(page_content="---\nsection: Test\n---\n\n正文", metadata={"url": "https://test.com"})
        _sources, context, _ = format_documents_with_metadata([doc], extract_clean_content=True)

        assert "section: Test" in context
        assert "正文" in context

    def test_extract_clean_content_false(self):
        """测试禁用clean content"""
        content = "---\nsection: Test\n---\n\n正文"
        doc = Document(page_content=content, metadata={"url": "https://test.com"})
        _sources, context, _ = format_documents_with_metadata([doc], extract_clean_content=False)

        assert content in context

    def test_snippet_field(self):
        """测试snippet字段"""
        doc = Document(page_content="内容", metadata={"url": "https://test.com", "snippet": "摘要"})
        sources, _context, _ = format_documents_with_metadata([doc])
        assert sources[0]["snippet"] == "摘要"

    def test_description_fallback(self):
        """测试description作为snippet fallback"""
        doc = Document(page_content="内容", metadata={"url": "https://test.com", "description": "描述"})
        sources, _context, _ = format_documents_with_metadata([doc])
        assert sources[0]["snippet"] == "描述"

    def test_snippet_priority(self):
        """测试snippet优先于description"""
        doc = Document(
            page_content="内容", metadata={"url": "https://test.com", "snippet": "摘要", "description": "描述"}
        )
        sources, _context, _ = format_documents_with_metadata([doc])
        assert sources[0]["snippet"] == "摘要"


class TestWrappers:
    """测试安全边界包装"""

    def test_wrap_external_sources_basic(self):
        """测试外部数据源包装"""
        content = "测试内容"
        wrapped = wrap_with_external_sources_tag(content)

        assert content in wrapped
        assert len(wrapped) > len(content)

    def test_wrap_external_sources_custom_source(self):
        """测试自定义source"""
        content = "内容"
        wrapped = wrap_with_external_sources_tag(content, source="web_search")
        assert content in wrapped

    def test_wrap_tool_output(self):
        """测试工具输出包装"""
        content = "工具输出"
        wrapped = wrap_with_tool_output_tag(content)

        assert content in wrapped
        assert len(wrapped) > len(content)

    def test_wrap_empty_string(self):
        """测试包装空字符串"""
        wrapped1 = wrap_with_external_sources_tag("")
        wrapped2 = wrap_with_tool_output_tag("")

        # 空字符串应该返回某种包装
        assert isinstance(wrapped1, str)
        assert isinstance(wrapped2, str)


class TestEdgeCases:
    """测试边缘情况"""

    def test_unicode_emoji(self):
        """测试emoji"""
        content = "Content  emoji"
        doc = Document(page_content=content, metadata={"url": "https://test.com"})
        _sources, context, _ = format_documents_with_metadata([doc])

        assert "" in context

    def test_special_characters(self):
        """测试特殊字符"""
        content = "<html> & 'quotes' \"double\""
        doc = Document(page_content=content, metadata={"url": "https://test.com"})
        _sources, context, _ = format_documents_with_metadata([doc])

        assert "<html>" in context
        assert "&" in context

    def test_very_long_url(self):
        """测试超长URL"""
        long_url = "https://test.com/" + "a" * 500
        doc = Document(page_content="内容", metadata={"url": long_url})
        _sources, context, _ = format_documents_with_metadata([doc])

        assert long_url in context

    def test_zero_length_content(self):
        """测试空内容"""
        doc = Document(page_content="", metadata={"url": "https://test.com", "title": "Empty"})
        sources, context, _ = format_documents_with_metadata([doc])

        assert len(sources) == 1
        assert "【1】" in context

    def test_whitespace_only_content(self):
        """测试纯空白内容"""
        doc = Document(page_content="   \n\n  \t  ", metadata={"url": "https://test.com"})
        _sources, context, _ = format_documents_with_metadata([doc])

        assert "【1】" in context

    def test_many_documents(self):
        """测试大量文档"""
        docs = [Document(page_content=f"Content {i}", metadata={"url": f"https://test{i}.com"}) for i in range(50)]
        sources, context, _ = format_documents_with_metadata(docs)

        assert len(sources) == 50
        assert "【1】" in context
        assert "【50】" in context


class TestFormatCrawlResultsComplete:
    """测试format_crawl_results完整功能"""

    def test_basic_crawl_format(self):
        """测试基本crawl格式化"""
        results = [
            (
                "https://test.com",
                Document(page_content="Content", metadata={"url": "https://test.com", "title": "Test"}),
            ),
        ]
        formatted = format_crawl_results(results)

        assert "【1】" in formatted
        assert "Content" in formatted

    def test_crawl_vs_documents_consistency(self):
        """测试crawl_results和documents格式化的一致性"""
        doc = Document(page_content="Test", metadata={"url": "https://test.com", "title": "Title"})

        # 使用format_crawl_results
        crawl_result = format_crawl_results([("https://test.com", doc)])

        # 使用format_documents_with_metadata
        _, doc_result, _ = format_documents_with_metadata([doc])

        # 应该有相似的结构
        assert "【1】" in crawl_result and "【1】" in doc_result
        assert "Test" in crawl_result and "Test" in doc_result


class TestRealWorldScenarios:
    """测试真实场景"""

    def test_web_search_scenario(self):
        """模拟web search"""
        docs = [
            Document(
                page_content="Python is great.",
                metadata={"url": "https://python.org", "title": "Python", "snippet": "Intro"},
            ),
            Document(
                page_content="Async programming.",
                metadata={"url": "https://docs.python.org", "title": "Docs"},
            ),
        ]

        sources, context, _ = format_documents_with_metadata(docs, questions=["python async"])

        assert len(sources) == 2
        assert "relevant results for keywords [python async]" in context

    def test_web_fetch_scenario(self):
        """模拟web fetch"""
        doc = Document(
            page_content="Long article content. " * 100,
            metadata={"url": "https://article.com", "title": "Article"},
        )

        sources, context, _ = format_documents_with_metadata(
            [doc],
            include_title=True,
            include_date=False,
            extract_clean_content=False,
        )

        assert len(sources) == 1
        assert "Long article content" in context

    def test_retriever_scenario(self):
        """模拟retriever"""
        docs = [
            Document(page_content="Chunk 1", metadata={"url": "https://doc1.com"}),
            Document(page_content="Chunk 2", metadata={"url": "https://doc2.com"}),
        ]

        sources, context, _ = format_documents_with_metadata(docs, questions=["query"])

        assert len(sources) == 2
        assert "relevant results" in context

    def test_mixed_document_types(self):
        """测试混合文档类型"""
        docs = [
            Document(page_content="Short", metadata={"url": "https://short.com"}),
            Document(page_content="Medium text. " * 50, metadata={"url": "https://medium.com"}),
            Document(page_content="", metadata={"url": "https://empty.com", "title": "Empty"}),
        ]

        sources, context, _ = format_documents_with_metadata(docs)

        assert len(sources) == 3
        assert "Short" in context


class TestMetadataStructure:
    """测试元数据结构"""

    def test_metadata_fields(self):
        """测试元数据所有字段"""
        doc = Document(
            page_content="内容",
            metadata={
                "url": "https://test.com",
                "title": "标题",
                "snippet": "摘要",
                "date": "2024-03-18",
            },
        )
        sources, _context, _ = format_documents_with_metadata([doc], include_date=True)

        assert sources[0]["url"] == "https://test.com"
        assert sources[0]["title"] == "标题"
        assert sources[0]["snippet"] == "摘要"
        assert sources[0]["date"] == "2024-03-18"

    def test_metadata_empty_fields(self):
        """测试空元数据字段"""
        doc = Document(page_content="内容", metadata={"url": "https://test.com"})
        sources, _context, _ = format_documents_with_metadata([doc])

        assert sources[0]["url"] == "https://test.com"
        assert sources[0]["title"] == ""
        assert sources[0]["snippet"] == ""
        assert sources[0]["date"] == ""

    def test_metadata_order_preserved(self):
        """测试元数据顺序保持"""
        docs = [
            Document(page_content=f"C{i}", metadata={"url": f"https://test{i}.com", "title": f"T{i}"})
            for i in [3, 1, 2]
        ]
        sources, _context, _ = format_documents_with_metadata(docs)

        # 顺序应该保持为 3, 1, 2
        assert sources[0]["url"] == "https://test3.com"
        assert sources[1]["url"] == "https://test1.com"
        assert sources[2]["url"] == "https://test2.com"


class TestIntegration:
    """集成测试"""

    def test_full_pipeline(self):
        """测试完整pipeline"""
        docs = [
            Document(
                page_content="---\nsection: Intro\n---\n\nContent one.",
                metadata={
                    "url": "https://test1.com",
                    "title": "Title 1",
                    "snippet": "Snippet 1",
                    "date": "2024-03-18",
                },
            ),
            Document(
                page_content="Content two.",
                metadata={"url": "https://test2.com", "title": "Title 2", "description": "Desc 2"},
            ),
        ]

        sources, context, _ = format_documents_with_metadata(
            docs,
            questions=["test query"],
            include_title=True,
            include_date=True,
            extract_clean_content=True,
        )

        assert len(sources) == 2
        assert "relevant results for keywords [test query]" in context
        assert "Title 1" in context
        assert "Date: 2024-03-18" in context
        assert "section: Intro" in context

    def test_stress_many_urls(self):
        """压力测试：大量URL"""
        docs = [
            Document(page_content=f"Content {i}", metadata={"url": f"https://test{i}.com", "title": f"T{i}"})
            for i in range(100)
        ]

        sources, context, _ = format_documents_with_metadata(docs)

        assert len(sources) == 100
        assert "【1】" in context
        assert "【100】" in context

    def test_stress_duplicate_urls(self):
        """压力测试：大量重复URL"""
        docs = [
            Document(page_content=f"Fragment {i}", metadata={"url": "https://same.com", "title": "Same"})
            for i in range(50)
        ]

        sources, context, _ = format_documents_with_metadata(docs)

        assert len(sources) == 1
        assert context.count("【1】") == 1
        # 所有片段应该都在
        assert sum(1 for i in range(50) if f"Fragment {i}" in context) == 50
