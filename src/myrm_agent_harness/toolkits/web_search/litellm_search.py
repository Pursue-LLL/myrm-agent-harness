"""LiteLLM unified search client.

Wraps the LiteLLM `search()` API to provide a consistent interface for
multiple search providers (Perplexity, Tavily, Exa, Google PSE, etc.).

[INPUT]
litellm::search (POS: LiteLLM unified search API)
web_search.common::SearchResult (POS: Unified search result dataclass)

[OUTPUT]
LiteLLMSearch: Async search client supporting multiple providers via LiteLLM

[POS]
LiteLLM search adapter. Translates provider-agnostic search requests into LiteLLM
API calls and normalises responses into SearchResult objects.

"""

import asyncio
import logging

from litellm import search

from myrm_agent_harness.toolkits.web_search.common import SearchResult

logger = logging.getLogger(__name__)


class LiteLLMSearch:
    """LiteLLM统一SearchTool，Support多种Search提供商

    Support Search提供商：
    - perplexity: Perplexity AI Search
    - tavily: Tavily Search
    - exa_ai: Exa AI Search
    - parallel_ai: Parallel AI Search
    - google_pse: Google Programmable Search Engine
    - dataforseo: DataForSEO Search
    - firecrawl: Firecrawl Search
    - searxng: SearXNG Search ( need Configure api_base)
    """

    def __init__(
        self,
        search_provider: str,
        api_key: str | None = None,
        api_base: str | None = None,
        timeout_seconds: int | None = 20,
    ):
        """InitializeLiteLLMSearchTool

        Args:
            search_provider: Search提供商名称
            api_key: APIKey（Dynamic传入， not depends on环境变量）
            api_base: APIbasicURL（ for 自托管Service如SearxNG）
            timeout_seconds: Timeout时间（秒）
        """
        self.search_provider = search_provider
        self.api_key = api_key
        self.api_base = api_base
        self.timeout_seconds = timeout_seconds or 20

    async def search(self, query: str, num_results: int = 5, **kwargs) -> list[SearchResult]:
        """using LiteLLMPerform统一Search

        Args:
            query: SearchQuery
            num_results: ReturnResultCount
            **kwargs: 提供商特定Parameter，Support：

                通用Parameter（All提供商）：
                - search_domain_filter: List[str] - DomainFilterList
                - country: str - 国家代码Filter
                - max_tokens_per_page: int - 每页Maximum token 数

                Tavily 特定Parameter：
                - topic: str - Search主题 ('general', 'news', 'finance')
                - search_depth: str - SearchDepth ('basic', 'advanced')
                - include_answer: bool - Contains AI Generate 答案
                - include_raw_content: bool - Containsoriginal HTML Content

                Firecrawl 特定Parameter：
                - sources: List[str] - SearchmultipleData源 (如 ["web", "news"])
                - categories: List[Dict] - 分类Filter (如 [{"type": "github"}])
                - tbs: str - 基于时间 Search (如 "qdr:m" 表示过去一个月)
                - location: str - 地理Position定位
                - ignoreInvalidURLs: bool - ExcludesInvalid URL
                - scrapeOptions: Dict - 爬取选项

                SearxNG 特定Parameter：
                - categories: str - 逗号分隔 分类 (如 "general,science")
                - engines: str - 逗号分隔 Search引擎 (如 "google,duckduckgo,bing")
                - language: str - 语言代码 (如 "en", "zh")
                - pageno: int - 页码
                - time_range: str - 时间Filter ("day", "month", "year")

                Other提供商Parameter会Auto传递给 LiteLLM

        Returns:
            SearchResultList，统一 is SearchResultType
        """
        # BuildSearchParameter
        search_params = {
            "query": query,
            "search_provider": self.search_provider,
            "max_results": num_results,
            "timeout": self.timeout_seconds,
        }

        # Dynamic传入 API Key（Ifprovides）
        if self.api_key:
            search_params["api_key"] = self.api_key

        # 对于 SearxNG  etc.自托管Service，传入 api_base
        if self.api_base:
            search_params["api_base"] = self.api_base

        # MergeAll kwargs（提供商特定Parameter）
        # LiteLLM 会Auto将这些Parameter传递给相应 Search提供商
        search_params.update(kwargs)

        # litellm.search 可能Return协程 or SyncResult， need Process两种情况
        #  using asyncio.to_thread in 线程池 in Call，然后CheckReturn value
        async def _safe_call():
            result = await asyncio.to_thread(search, **search_params)
            # IfReturn 是协程（ not  should 发生，但以防万一）
            if asyncio.iscoroutine(result):
                result = await result
            return result

        response = await asyncio.wait_for(_safe_call(), timeout=self.timeout_seconds)

        # Convert is 统一  SearchResult Format
        # LiteLLM ReturnFormat: {"object": "search", "results": [{"title": ..., "url": ..., "snippet": ..., "date": ...}]}
        results = []
        # response 是 SearchResponse Object， has  results Property
        response_results = getattr(response, "results", [])

        # Ifresults是协程， need await
        if asyncio.iscoroutine(response_results):
            response_results = await response_results

        for result in response_results:
            result_dict = {
                "title": result.title if hasattr(result, "title") else "",
                "link": result.url if hasattr(result, "url") else "",
                "snippet": result.snippet if hasattr(result, "snippet") else "",
            }
            # 添加日期Field（IfExists）
            if hasattr(result, "date") and result.date:
                result_dict["date"] = result.date

            results.append(SearchResult.from_dict(result_dict))

        return results
