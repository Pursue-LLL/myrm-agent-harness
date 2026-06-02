"""WebSearcher — Multi-provider web search orchestrator.

Manages search provider configuration, query execution with retry,
result caching, and conversion to LangChain Documents.

[INPUT]
web_search.common::SearchResult (POS: Unified search result dataclass)
web_search.error_handling::build_search_error_context, is_retryable_search_error (POS: Search error classification)
web_search.exceptions::AllQueriesFailedError, ErrorContext, SearchAPIError, SearchConfigError (POS: Search exception types)
web_search.metrics::WebSearchMetrics, web_search_metrics (POS: Search telemetry)
web_search.search_results_processor::search_results_to_documents (POS: Search-result to Document converter)
web_search.litellm_search::LiteLLMSearch (POS: LiteLLM unified search client)
utils.lru_cache::LRUCache (POS: Generic TTL-based LRU cache)

[OUTPUT]
WebSearcher: Configurable multi-provider web search with caching, retry, and Document output
SearchServiceType: Literal type alias enumerating supported search providers

[POS]
Web search orchestrator. Provides a unified interface for querying multiple search
providers (Perplexity, Tavily, Exa, etc.) with caching, retry, and error handling.

"""

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Literal

from langchain_core.documents import Document
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from myrm_agent_harness.core.config.gateway import ToolGatewayConfig
from myrm_agent_harness.toolkits.web_search.common import SearchResult
from myrm_agent_harness.toolkits.web_search.error_handling import (
    build_search_error_context,
    is_retryable_search_error,
)
from myrm_agent_harness.toolkits.web_search.exceptions import (
    AllQueriesFailedError,
    ErrorContext,
    SearchAPIError,
    SearchConfigError,
)
from myrm_agent_harness.toolkits.web_search.metrics import WebSearchMetrics, web_search_metrics
from myrm_agent_harness.toolkits.web_search.search_results_processor import search_results_to_documents
from myrm_agent_harness.utils.lru_cache import LRUCache

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.web_search.litellm_search import LiteLLMSearch

_search_cache: LRUCache[list[SearchResult]] = LRUCache(maxsize=200, ttl=900, id="web_search_api_cache")

SearchServiceType = Literal[
    "perplexity",  # Perplexity AI Search
    "tavily",  # Tavily Search
    "exa_ai",  # Exa AI Search
    "parallel_ai",  # Parallel AI Search
    "google_pse",  # Google Programmable Search Engine
    "dataforseo",  # DataForSEO Search
    "firecrawl",  # Firecrawl Search
    "searxng",  # SearxNG Search (Self-hosted, via LiteLLM)
]

# Configure logging
logger = logging.getLogger(__name__)


class SearchServiceConfig(BaseModel):
    """Search service configuration model (supports runtime updates)"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    search_service: SearchServiceType = Field(..., description="Search service type")
    api_key: str | None = Field(default=None, description="API key (dynamically passed, supports multi-user)")
    api_base: str | None = Field(default=None, description="API base URL (for self-hosted services like SearxNG)")
    timeout_seconds: int | None = Field(default=20, description="Single search timeout (seconds)")
    extra_params: dict[str, object] | None = Field(
        default=None,
        description="Provider-specific parameters for LiteLLM search (categories, engines, language, etc.)",
    )
    search_max_retries: int = Field(
        default=2,
        ge=0,
        le=8,
        description="Number of retries after the first failed search attempt",
    )
    retry_backoff_base_seconds: float = Field(default=0.5, ge=0.0, le=60.0)
    retry_backoff_max_seconds: float = Field(default=8.0, ge=0.0, le=120.0)
    total_timeout_seconds: int | None = Field(
        default=None,
        description="Max wall-clock seconds for search() including retries; None derives from timeout and retry settings",
    )
    fallback_config: "SearchServiceConfig | None" = Field(
        default=None,
        description="Optional fallback search service config; triggered when primary service encounters non-retryable errors (quota exceeded, invalid API key)",
    )
    gateway_config: ToolGatewayConfig | None = Field(
        default=None,
        description="Optional gateway configuration for routing traffic through the Unified Tool Gateway",
    )


SearchServiceConfig.model_rebuild()


class WebSearcher:
    """Web search core implementation class, only responsible for basic search functionality"""

    def __init__(self, config: SearchServiceConfig, metrics: WebSearchMetrics | None = None):
        """Initialize search tool

        Args:
            config: Search service configuration
            metrics: Optional metrics sink (defaults to process-wide ``web_search_metrics``)
        """
        self.config = config
        self._search_service = None
        self._metrics = metrics if metrics is not None else web_search_metrics

    async def _get_search_service(self, bypass_gateway: bool = False) -> "LiteLLMSearch":
        """Get search service instance (LiteLLM-backed providers including SearXNG).

        Args:
            bypass_gateway: If True, force direct connection bypassing the gateway.

        Returns:
            Search service instance
        """
        # If we need to bypass gateway, we can't use the cached _search_service if it was using gateway
        if self._search_service is not None and not bypass_gateway:
            return self._search_service

        logger.warning(f"Initializing search service: {self.config.search_service} (bypass_gateway={bypass_gateway})")

        from myrm_agent_harness.toolkits.web_search.litellm_search import LiteLLMSearch

        if self.config.search_service == "searxng":
            api_base = self.config.api_base
            if not api_base:
                raise SearchConfigError(
                    "SearxNG search requires api_base in SearchServiceConfig "
                    "(configure via WebUI Settings)",
                    config_key="api_base",
                )
            api_key = self.config.api_key
        else:
            if not bypass_gateway and self.config.gateway_config and self.config.gateway_config.use_gateway:
                # Use gateway routing: override api_base and inject auth_token as api_key
                api_base = f"{self.config.gateway_config.gateway_url.rstrip('/')}/{self.config.search_service}"
                api_key = self.config.gateway_config.auth_token
            else:
                api_base = self.config.api_base
                api_key = self.config.api_key
                if not api_key:
                    raise SearchConfigError(
                        f"{self.config.search_service} search requires API key configuration",
                        config_key="api_key",
                    )

        service = LiteLLMSearch(
            search_provider=self.config.search_service,
            api_key=api_key,
            api_base=api_base,
            timeout_seconds=self.config.timeout_seconds,
        )

        if not bypass_gateway:
            self._search_service = service

        logger.warning(f"Search service {self.config.search_service} initialized successfully")
        return service

    def _compute_search_total_timeout_seconds(self) -> float:
        if self.config.total_timeout_seconds is not None:
            return float(self.config.total_timeout_seconds)
        per_attempt = float(self.config.timeout_seconds or 20)
        attempts = self.config.search_max_retries + 1
        backoff_sum = 0.0
        for i in range(self.config.search_max_retries):
            backoff_sum += min(
                self.config.retry_backoff_base_seconds * (2**i),
                self.config.retry_backoff_max_seconds,
            )
        return per_attempt * attempts + backoff_sum + 1.0

    async def search(
        self,
        query: str,
        num_results: int = 5,
        extra_params_override: dict[str, str] | None = None,
    ) -> list[SearchResult]:
        """Search using configured search engine

        Args:
            query: Search query
            num_results: Number of results to return
            extra_params_override: Optional per-query parameter override (e.g., from intent detection).
                                   Merged on top of config.extra_params when provided.

        Returns:
            List of search results
        """
        extra_params: dict[str, object] = dict(self.config.extra_params) if self.config.extra_params else {}
        if extra_params_override:
            extra_params.update(extra_params_override)

        if self.config.search_service == "searxng":
            if "language" not in extra_params:
                extra_params["language"] = "auto"
            if "categories" not in extra_params:
                extra_params["categories"] = "general"
            if "safesearch" not in extra_params:
                extra_params["safesearch"] = "0"

        extra_suffix = json.dumps(extra_params, sort_keys=True, default=str) if extra_params else ""
        cache_key = f"{self.config.search_service}:{query}:{num_results}:{extra_suffix}"

        cached_result = _search_cache.get(cache_key)
        if cached_result is not None:
            logger.info(f"Search cache hit: {query}")
            return cached_result

        provider = self.config.search_service
        max_attempts = self.config.search_max_retries + 1

        # Track if we are currently bypassing the gateway due to a fallback
        bypass_gateway = False

        for attempt in range(max_attempts):
            self._metrics.record_attempt()
            try:
                search_service = await self._get_search_service(bypass_gateway=bypass_gateway)
                if extra_params:
                    results = await search_service.search(query, num_results, **extra_params)
                else:
                    results = await search_service.search(query, num_results)
            except Exception as exc:
                # Gateway Flexible Fallback Logic
                if (
                    not bypass_gateway
                    and self.config.gateway_config
                    and self.config.gateway_config.use_gateway
                    and self.config.api_key  # Must have a local API key to fallback to
                ):
                    error_msg = self._extract_key_error(exc).lower()
                    # Fallback on gateway errors (502, 503, 504) or insufficient funds (402)
                    if "502" in error_msg or "503" in error_msg or "504" in error_msg or "402" in error_msg or "insufficient" in error_msg or "timeout" in error_msg:
                        logger.warning(
                            f"Gateway search failed ({error_msg}), falling back to direct provider API (BYOK)"
                        )
                        try:
                            from myrm_agent_harness.utils.event_utils import dispatch_custom_event
                            await dispatch_custom_event(
                                "agent_status",
                                {
                                    "event": "tool_fallback",
                                    "tool": "web_search_tool",
                                    "fallback_type": "gateway_failover",
                                    "message": f"统一网关异常，正在无缝回退至本地直连 ({provider})..."
                                }
                            )
                        except Exception:
                            pass
                        bypass_gateway = True
                        # Immediately retry this attempt with direct connection
                        continue

                if not is_retryable_search_error(exc) or attempt >= max_attempts - 1:
                    # Try fallback service if available and primary service failed with non-retryable error
                    if self.config.fallback_config is not None and not is_retryable_search_error(exc):
                        fallback_cfg = self.config.fallback_config
                        logger.warning(
                            f"Primary search service '{provider}' failed ({self._extract_key_error(exc)}), "
                            f"trying fallback service '{fallback_cfg.search_service}'"
                        )
                        try:
                            from myrm_agent_harness.utils.event_utils import dispatch_custom_event
                            await dispatch_custom_event(
                                "agent_status",
                                {
                                    "event": "tool_fallback",
                                    "tool": "web_search_tool",
                                    "fallback_type": "api_failover",
                                    "message": f"主搜索服务异常，正在无缝切换至备用引擎 ({fallback_cfg.search_service})..."
                                }
                            )
                        except Exception:
                            pass
                        self._metrics.record_fallback_triggered()

                        # Prevent infinite recursion by clearing fallback_config
                        fallback_cfg_copy = fallback_cfg.model_copy(update={"fallback_config": None})
                        fallback_searcher = WebSearcher(fallback_cfg_copy, metrics=self._metrics)
                        try:
                            fallback_results = await fallback_searcher.search(query, num_results)
                            self._metrics.record_fallback_success()
                            logger.warning(
                                f"Fallback search service '{fallback_cfg.search_service}' succeeded, "
                                f"returned {len(fallback_results)} results"
                            )
                            _search_cache.set(cache_key, fallback_results)
                            return fallback_results
                        except Exception as fallback_exc:
                            self._metrics.record_fallback_failure()
                            logger.warning(
                                f"Fallback search service '{fallback_cfg.search_service}' also failed: "
                                f"{self._extract_key_error(fallback_exc)}"
                            )

                    self._metrics.record_terminal_failure()
                    ctx = build_search_error_context(
                        exc,
                        query=query,
                        provider=provider,
                        attempt_index=attempt,
                    )
                    raise SearchAPIError(
                        f"Search request failed: {self._extract_key_error(exc)}",
                        context=ctx,
                    ) from exc
                self._metrics.record_retry_scheduled()
                delay = min(
                    self.config.retry_backoff_base_seconds * (2**attempt),
                    self.config.retry_backoff_max_seconds,
                )
                await asyncio.sleep(delay)
                continue

            self._metrics.record_success()
            _search_cache.set(cache_key, results)
            return results

    async def search_and_process(
        self,
        query: str,
        num_results: int,
        extra_params_override: dict[str, str] | None = None,
    ) -> tuple[str, list[Document], Exception | None]:
        """Execute single query and process results for compound search

        Args:
            query: Query string
            num_results: Number of results to return
            extra_params_override: Optional per-query parameter override from intent detection

        Returns:
            Query, documents list and possible exception
        """
        total_timeout = self._compute_search_total_timeout_seconds()
        try:
            logger.warning(f"Searching query: {query}")
            search_results = await asyncio.wait_for(
                self.search(query=query, num_results=num_results, extra_params_override=extra_params_override),
                timeout=total_timeout,
            )

            documents = search_results_to_documents(search_results)
            return query, documents, None
        except TimeoutError:
            ctx = ErrorContext(
                query=query,
                retryable=True,
                error_code="TimeoutError",
                metadata={
                    "provider": self.config.search_service,
                    "phase": "search_and_process",
                    "total_timeout_seconds": str(int(total_timeout)),
                },
            )
            err = SearchAPIError("Search exceeded total time budget (including retries)", context=ctx)
            logger.warning(f"Search '{query}' failed: {err.message}")
            return query, [], err
        except Exception as e:
            error_msg = self._extract_key_error(e)
            logger.warning(f"Search '{query}' failed: {error_msg}")
            return query, [], e

    def _extract_key_error(self, e: Exception) -> str:
        """Extract key error information from exception, filtering out redundant stack trace information

        Args:
            e: Exception object

        Returns:
            Concise error message string
        """
        error_str = str(e)
        error_lower = error_str.lower()

        # Semantic checks first — LiteLLM wraps provider errors inside generic
        # APIConnectionError, so content-based matching must precede class-name matching.
        if "exceeds" in error_lower and ("usage limit" in error_lower or "plan" in error_lower):
            return "Search service quota exceeded — upgrade your plan or use a different API key"
        if "invalid api key" in error_lower or "invalid_api_key" in error_lower:
            return "Search service authentication failed — invalid API key"
        if "rate limit" in error_lower or "429" in error_str:
            return "Search service rate limit exceeded (429 Too Many Requests)"
        if "401" in error_str or "unauthorized" in error_lower:
            return "Search service authentication failed (401 Unauthorized)"
        if "403" in error_str or "forbidden" in error_lower:
            return "Search service access denied (403 Forbidden)"
        if "502" in error_str:
            return "Search service unavailable (502 Bad Gateway)"
        if "503" in error_str:
            return "Search service temporarily unavailable (503 Service Unavailable)"
        if "504" in error_str:
            return "Search service timeout (504 Gateway Timeout)"

        # Generic connection / timeout errors (checked after semantic matches)
        if "connection refused" in error_lower:
            return "Cannot connect to search service"
        if "connectionerror" in error_lower and "apiconnectionerror" not in error_lower:
            return "Cannot connect to search service"
        if "timeouterror" in error_lower or "timed out" in error_lower:
            return "Search request timeout"

        if "jsondecode" in error_lower or "expecting value" in error_lower:
            return "Search service returned invalid response"

        error_type = type(e).__name__
        short_msg = error_str[:100] if len(error_str) > 100 else error_str
        return f"{error_type}: {short_msg}"

    async def multi_query_parallel_search(
        self,
        queries: list[str],
        results_per_query: int,
        per_query_overrides: list[dict[str, str] | None] | None = None,
    ) -> list[tuple[str, list[Document], Exception | None]]:
        """Multi-query parallel search

        Pure parallel search execution, returns raw results. Data processing handled by caller.

        Args:
            queries: List of queries
            results_per_query: Number of results per query
            per_query_overrides: Optional list of per-query extra_params overrides (from intent detection).
                                 Must match len(queries) if provided. None entries mean no override.

        Returns:
            Raw search results list: [(query, documents list, possible exception), ...]

        Raises:
            RuntimeError: When all search queries fail, raises concise error message
        """
        overrides = per_query_overrides or [None] * len(queries)
        tasks = [self.search_and_process(q, results_per_query, override) for q, override in zip(queries, overrides, strict=False)]
        results = await asyncio.gather(*tasks)

        # Check if there are successful queries
        successful_queries = [q for q, docs, err in results if err is None and docs]
        failed_queries = [(q, err) for q, _, err in results if err is not None]

        if successful_queries:
            return results

        if failed_queries:
            details = [(q, self._extract_key_error(err)) for q, err in failed_queries]
            primary_ctx = None
            for _, err in failed_queries:
                if isinstance(err, SearchAPIError):
                    primary_ctx = err.context
                    break
            first_error = failed_queries[0][1]
            key_error = self._extract_key_error(first_error)
            raise AllQueriesFailedError(
                f"Web search failed: {key_error}",
                failed_queries=details,
                primary_context=primary_ctx,
            )

        empty_queries = [q for q, docs, err in results if err is None and not docs]
        if empty_queries:
            raise AllQueriesFailedError(
                f"Web search returned 0 results for {len(empty_queries)} queries. "
                "The search service may be unreachable or returned an empty response.",
                failed_queries=[(q, "empty result set") for q in empty_queries],
            )

        raise AllQueriesFailedError("Web search failed: no queries were executed", failed_queries=[])
