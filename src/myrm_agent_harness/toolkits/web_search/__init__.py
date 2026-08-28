"""Web search toolkit.


[INPUT]
- core.common::SearchResult, Citation (POS: search result and citation data models)
- core.exceptions::AllQueriesFailedError, SearchAPIError, etc. (POS: web search error hierarchy)
- core.metrics::WebSearchMetrics, web_search_metrics (POS: search performance metrics)
- processing.search_results_processor::combine_search_results_unified, search_results_to_documents (POS: result processing utilities)

[OUTPUT]
- SearchResult, Citation, WebSearchTools, LiteLLMSearch, SearchServiceConfig: core search types and tools
- WebSearchMetrics, web_search_metrics: metrics collection
- Error types: AllQueriesFailedError, SearchAPIError, SearchConfigError, WebSearchError, ErrorContext
- combine_search_results_unified, search_results_to_documents: result processors

[POS]
Web search toolkit entry point. Aggregates and re-exports search tools, result types,
metrics, and error hierarchy for unified import.
"""

from typing import TYPE_CHECKING

from .core.common import Citation, SearchResult
from .core.exceptions import AllQueriesFailedError, ErrorContext, SearchAPIError, SearchConfigError, WebSearchError
from .core.metrics import WebSearchMetrics, web_search_metrics
from .processing.search_results_processor import (
    combine_search_results_unified,
    search_results_to_documents,
)

if TYPE_CHECKING:
    from .engine import WebSearchTools
    from .providers.litellm_search import LiteLLMSearch
    from .providers.web_searcher import SearchServiceConfig

__all__ = [
    "AllQueriesFailedError",
    "Citation",
    "ErrorContext",
    "LiteLLMSearch",
    "SearchAPIError",
    "SearchConfigError",
    "SearchResult",
    "SearchServiceConfig",
    "WebSearchError",
    "WebSearchMetrics",
    "WebSearchTools",
    "combine_search_results_unified",
    "search_results_to_documents",
    "web_search_metrics",
]

_LAZY_SYMBOLS = {"LiteLLMSearch", "SearchServiceConfig", "WebSearchTools"}

if __debug__:
    _extra = _LAZY_SYMBOLS - set(__all__)
    if _extra:
        raise RuntimeError(f"web_search: lazy symbols not in __all__: {_extra}")


def __getattr__(name: str):
    """Lazy load LiteLLMSearch, SearchServiceConfig, and WebSearchTools on first access."""
    if name in _LAZY_SYMBOLS:
        if name == "LiteLLMSearch":
            from .providers.litellm_search import LiteLLMSearch

            globals()[name] = LiteLLMSearch
            return LiteLLMSearch
        elif name == "SearchServiceConfig":
            from .providers.web_searcher import SearchServiceConfig

            globals()[name] = SearchServiceConfig
            return SearchServiceConfig
        elif name == "WebSearchTools":
            from .engine import WebSearchTools

            globals()[name] = WebSearchTools
            return WebSearchTools

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
