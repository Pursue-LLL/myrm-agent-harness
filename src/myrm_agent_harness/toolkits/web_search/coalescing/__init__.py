"""In-flight search request coalescing and cache-key helpers.

[INPUT]
- coalescing.search_coalescing (POS: Single-flight search API deduplication layer)

[OUTPUT]
- Re-exports: await_coalesced_search, bucket_search_limit, build_search_cache_key, normalize_search_query, slice_search_results, reset_search_coalescing_state_for_tests

[POS]
Subpackage entry for web search API coalescing and cache-key helpers.
"""

from myrm_agent_harness.toolkits.web_search.coalescing.search_coalescing import (
    await_coalesced_search,
    bucket_search_limit,
    build_search_cache_key,
    normalize_search_query,
    reset_search_coalescing_state_for_tests,
    slice_search_results,
)

__all__ = [
    "await_coalesced_search",
    "bucket_search_limit",
    "build_search_cache_key",
    "normalize_search_query",
    "reset_search_coalescing_state_for_tests",
    "slice_search_results",
]
