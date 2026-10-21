"""Shared types and errors for web search.

[INPUT]
- core.common (POS: Search result and citation data models)
- core.exceptions (POS: Web search exception hierarchy)
- core.error_handling (POS: Search failure classification)

[OUTPUT]
- Re-exports: SearchResult, Citation, exception types, error helpers

[POS]
Subpackage entry for shared web search types and errors.
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

__all__ = [
    "AllQueriesFailedError",
    "Citation",
    "ErrorContext",
    "SearchAPIError",
    "SearchConfigError",
    "SearchResult",
    "WebSearchError",
    "build_search_error_context",
    "is_quota_or_rate_limit_error",
    "is_retryable_search_error",
]
