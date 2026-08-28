"""Shared types, errors, and metrics for web search.

[INPUT]
- core.common (POS: Search result and citation data models)
- core.exceptions (POS: Web search exception hierarchy)
- core.error_handling (POS: Search failure classification)
- core.metrics (POS: In-process search operation counters)

[OUTPUT]
- Re-exports: SearchResult, Citation, exception types, WebSearchMetrics, error helpers

[POS]
Subpackage entry for shared web search types, errors, and metrics.
"""

from myrm_agent_harness.toolkits.web_search.core.common import Citation, SearchResult
from myrm_agent_harness.toolkits.web_search.core.error_handling import (
    build_search_error_context,
    is_quota_or_rate_limit_error,
    is_retryable_search_error,
)
from myrm_agent_harness.toolkits.web_search.core.exceptions import (
    AllQueriesFailedError,
    ErrorContext,
    SearchAPIError,
    SearchConfigError,
    WebSearchError,
)
from myrm_agent_harness.toolkits.web_search.core.metrics import WebSearchMetrics, web_search_metrics

__all__ = [
    "AllQueriesFailedError",
    "Citation",
    "ErrorContext",
    "SearchAPIError",
    "SearchConfigError",
    "SearchResult",
    "WebSearchError",
    "WebSearchMetrics",
    "build_search_error_context",
    "is_quota_or_rate_limit_error",
    "is_retryable_search_error",
    "web_search_metrics",
]
