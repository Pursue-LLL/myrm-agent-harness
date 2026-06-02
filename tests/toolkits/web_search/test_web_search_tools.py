"""Web Search Tools 单元测试

测试 web_search_tools 模块的核心功能：
- WebSearchTools 类的基本搜索
- 多查询并行搜索
- BM25 + Reranker 排序
- 异常处理
"""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest
from langchain_core.documents import Document

from myrm_agent_harness.toolkits.retriever.reranker import RerankerConfig
from myrm_agent_harness.toolkits.web_search.common import SearchResult
from myrm_agent_harness.toolkits.web_search.engine import WebSearchTools
from myrm_agent_harness.toolkits.web_search.exceptions import SearchAPIError
from myrm_agent_harness.toolkits.web_search.web_searcher import SearchServiceConfig


@pytest.mark.asyncio
class TestWebSearchToolsBasic:
    """WebSearchTools 基础功能测试"""

    async def test_initialization(self) -> None:
        """测试初始化"""
        config = SearchServiceConfig(
            search_service="perplexity",
            api_key="test-key",
        )

        tools = WebSearchTools(config=config)
        assert tools is not None
        assert tools._searcher is not None

    async def test_single_search(self) -> None:
        """测试单查询搜索"""
        config = SearchServiceConfig(
            search_service="perplexity",
            api_key="test-key",
        )
        tools = WebSearchTools(config=config)

        # Mock searcher
        mock_results = [
            SearchResult(
                title="Test Result",
                link="https://example.com",
                snippet="Test snippet content",
            )
        ]

        with patch.object(tools._searcher, "search", new_callable=AsyncMock, return_value=mock_results):
            results = await tools.search(query="test query", num_results=5)

            assert results is not None
            assert len(results) == 1
            assert results[0].title == "Test Result"

    async def test_fast_search_with_single_question(self) -> None:
        """测试单查询快速搜索（不触发 BM25）"""
        config = SearchServiceConfig(search_service="perplexity", api_key="test-key")
        tools = WebSearchTools(config=config)

        mock_results = [("query1", [Document(page_content="content", metadata={"url": "https://example.com"})], None)]

        with patch.object(
            tools._searcher, "multi_query_parallel_search", new_callable=AsyncMock, return_value=mock_results
        ):
            sources, formatted = await tools.fast_search_with_questions(
                questions=["test query"],
                search_results_per_query=10,
                top_k=5,
            )

            assert sources is not None
            assert formatted is not None
            assert isinstance(sources, list)
            assert isinstance(formatted, str)

    async def test_fast_search_with_multiple_questions_bm25(self) -> None:
        """测试多查询 BM25 融合排序"""
        config = SearchServiceConfig(search_service="perplexity", api_key="test-key")
        tools = WebSearchTools(config=config)

        mock_results = [
            (
                "query1",
                [
                    Document(page_content="Python programming", metadata={"url": "https://example.com/1"}),
                    Document(page_content="Java programming", metadata={"url": "https://example.com/2"}),
                ],
                None,
            ),
            (
                "query2",
                [
                    Document(page_content="Python tutorial", metadata={"url": "https://example.com/3"}),
                ],
                None,
            ),
        ]

        with patch.object(
            tools._searcher, "multi_query_parallel_search", new_callable=AsyncMock, return_value=mock_results
        ), patch.object(
            tools._retriever_manager,
            "bm25_retrieval_only",
            new_callable=AsyncMock,
            return_value=[Document(page_content="Python programming", metadata={"url": "https://example.com/1"})],
        ):
            sources, _formatted = await tools.fast_search_with_questions(
                questions=["python", "tutorial"],
                search_results_per_query=10,
                top_k=5,
            )

            assert sources is not None
            assert len(sources) >= 1

    async def test_fast_search_with_reranker(self) -> None:
        """测试多查询 Reranker 排序"""
        config = SearchServiceConfig(search_service="perplexity", api_key="test-key")
        reranker_cfg = RerankerConfig(model="cohere/rerank-v3.5", api_key="test-key")

        with patch("myrm_agent_harness.toolkits.retriever.reranker.get_reranker_service") as mock_get:
            mock_get.return_value = Mock()
            tools = WebSearchTools(config=config, reranker_config=reranker_cfg)

        mock_results = [
            ("query1", [Document(page_content="content1", metadata={"url": "https://example.com/1"})], None),
            ("query2", [Document(page_content="content2", metadata={"url": "https://example.com/2"})], None),
        ]

        with patch.object(
            tools._searcher, "multi_query_parallel_search", new_callable=AsyncMock, return_value=mock_results
        ), patch.object(
            tools._retriever_manager,
            "bm25_retrieval_with_mapping",
            new_callable=AsyncMock,
            return_value={"query1": [(Document(page_content="c1", metadata={}), 0.9)]},
        ), patch.object(
            tools._retriever_manager,
            "rerank_with_mapping",
            new_callable=AsyncMock,
            return_value=[Document(page_content="c1", metadata={})],
        ):
            sources, _formatted = await tools.fast_search_with_questions(
                questions=["q1", "q2"],
                search_results_per_query=10,
                top_k=5,
            )

            assert sources is not None


@pytest.mark.asyncio
class TestWebSearcher:
    """WebSearcher 单元测试"""

    async def test_web_searcher_init(self) -> None:
        """测试 WebSearcher 初始化"""
        from myrm_agent_harness.toolkits.web_search.web_searcher import WebSearcher

        config = SearchServiceConfig(search_service="perplexity", api_key="key")
        searcher = WebSearcher(config=config)

        assert searcher.config == config
        assert searcher._search_service is None  # 延迟初始化

    async def test_multi_query_parallel_search(self) -> None:
        """测试多查询并行搜索"""
        from myrm_agent_harness.toolkits.web_search.web_searcher import WebSearcher

        config = SearchServiceConfig(search_service="perplexity", api_key="key")
        searcher = WebSearcher(config=config)

        # Mock search 方法
        mock_result = [SearchResult(title="T", link="https://e.com", snippet="S")]
        with patch.object(searcher, "search", new_callable=AsyncMock, return_value=mock_result):
            results = await searcher.multi_query_parallel_search(
                queries=["q1", "q2"],
                results_per_query=5,  # 修正参数名
            )

            assert len(results) == 2
            assert results[0][0] == "q1"
            assert results[1][0] == "q2"

    async def test_search_caching(self) -> None:
        """测试搜索缓存机制存在"""
        from myrm_agent_harness.toolkits.web_search.web_searcher import WebSearcher, _search_cache

        config = SearchServiceConfig(search_service="perplexity", api_key="key")
        WebSearcher(config=config)

        # 验证缓存对象存在
        assert _search_cache is not None
        assert _search_cache.maxsize == 200
        assert _search_cache.ttl == 900


@pytest.mark.asyncio
class TestSearchResultsProcessor:
    """SearchResultsProcessor 单元测试"""

    async def test_search_results_to_documents(self) -> None:
        """测试 SearchResult 转 Document"""
        from myrm_agent_harness.toolkits.web_search.search_results_processor import (
            search_results_to_documents,
        )

        results = [
            SearchResult(
                title="Title 1",
                link="https://example.com/1",
                snippet="Snippet 1 content here",
            ),
            SearchResult(
                title="Title 2",
                link="https://example.com/2",
                snippet="Snippet 2 content here",
            ),
        ]

        docs = search_results_to_documents(results)

        assert len(docs) == 2
        assert docs[0].page_content == "Snippet 1 content here"
        assert docs[0].metadata["title"] == "Title 1"
        assert docs[0].metadata["url"] == "https://example.com/1"

    async def test_combine_search_results_unified(self) -> None:
        """测试搜索结果合并和去重"""
        from myrm_agent_harness.toolkits.web_search.search_results_processor import (
            combine_search_results_unified,
        )

        search_results = [
            (
                "query1",
                [
                    Document(page_content="content1", metadata={"url": "https://example.com/1"}),
                    Document(page_content="content2", metadata={"url": "https://example.com/2"}),
                ],
                None,
            ),
            (
                "query2",
                [
                    Document(page_content="content1", metadata={"url": "https://example.com/1"}),  # 重复
                    Document(page_content="content3", metadata={"url": "https://example.com/3"}),
                ],
                None,
            ),
        ]

        sources, unified_docs = combine_search_results_unified(search_results)

        # 验证去重
        assert len(unified_docs) == 3  # 应该去除重复的 URL
        assert len(sources) > 0

    async def test_combine_with_exceptions(self) -> None:
        """测试包含异常的搜索结果处理"""
        from myrm_agent_harness.toolkits.web_search.search_results_processor import (
            combine_search_results_unified,
        )

        search_results = [
            ("query1", [Document(page_content="c1", metadata={"url": "https://e.com/1"})], None),
            ("query2", [], Exception("Search failed")),
        ]

        _sources, unified_docs = combine_search_results_unified(search_results)

        # 应该包含成功的结果，忽略失败的
        assert len(unified_docs) >= 1

    async def test_combine_all_zero_results_raises_with_context(self) -> None:
        """全零结果时 SearchAPIError 应携带统计 metadata"""
        from myrm_agent_harness.toolkits.web_search.search_results_processor import (
            combine_search_results_unified,
        )

        search_results = [
            ("q1", [], None),
            ("q2", [], None),
        ]

        with pytest.raises(SearchAPIError) as exc_info:
            combine_search_results_unified(search_results)

        assert exc_info.value.context.metadata.get("total_queries") == "2"
        assert exc_info.value.context.metadata.get("zero_result_queries") == "2"


@pytest.mark.asyncio
class TestLiteLLMSearch:
    """LiteLLM Search 单元测试"""

    async def test_litellm_search_init(self) -> None:
        """测试 LiteLLM 搜索初始化"""
        from myrm_agent_harness.toolkits.web_search.litellm_search import LiteLLMSearch

        engine = LiteLLMSearch(
            search_provider="perplexity",
            api_key="test-key",
        )

        assert engine is not None
        assert engine.search_provider == "perplexity"

    async def test_litellm_search_execution(self) -> None:
        """测试搜索执行（Mock 返回 SearchResult）"""
        from myrm_agent_harness.toolkits.web_search.litellm_search import LiteLLMSearch

        engine = LiteLLMSearch(search_provider="perplexity", api_key="test-key")

        # Mock 返回 SearchResult 对象列表
        [SearchResult(title="R1", link="https://e.com/1", snippet="S1")]

        with patch(
            "myrm_agent_harness.toolkits.web_search.litellm_search.search",
            new_callable=AsyncMock,
            return_value={"results": [{"title": "R1", "link": "https://e.com/1", "snippet": "S1"}]},
        ):
            results = await engine.search(query="test query", num_results=5)

            # litellm.search 返回的是字典，engine.search 会转换为 SearchResult
            assert results is not None
            assert isinstance(results, list)

    async def test_litellm_searxng_url_override(self) -> None:
        """测试 SearXNG 自定义 URL"""
        from myrm_agent_harness.toolkits.web_search.litellm_search import LiteLLMSearch

        engine = LiteLLMSearch(
            search_provider="searxng",
            api_base="http://custom-searxng:8080",
        )

        assert engine.api_base == "http://custom-searxng:8080"


@pytest.mark.asyncio
class TestCommonUtilities:
    """Common 工具函数测试"""

    async def test_search_result_model(self) -> None:
        """测试 SearchResult Pydantic 模型"""
        from myrm_agent_harness.toolkits.web_search.common import SearchResult

        result = SearchResult(
            title="Test Title",
            link="https://example.com",
            snippet="Test snippet",
        )

        assert result.title == "Test Title"
        assert result.link == "https://example.com"
        assert result.url == "https://example.com"  # url 是 link 的属性别名
        assert result.snippet == "Test snippet"

    async def test_search_result_dict_conversion(self) -> None:
        """测试 SearchResult 字典转换"""
        from myrm_agent_harness.toolkits.web_search.common import SearchResult

        result = SearchResult(
            title="Title",
            link="https://example.com",
            snippet="Snippet",
        )

        result_dict = result.model_dump()

        assert result_dict["title"] == "Title"
        assert result_dict["link"] == "https://example.com"
