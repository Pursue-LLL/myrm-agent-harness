"""In-flight search request coalescing and dynamic freshness cache governor.

[INPUT]
- coalescing.search_coalescing (POS: Single-flight search API deduplication layer)
- coalescing.freshness_intent_types (POS: Freshness tiers and governor contracts)
- coalescing.query_freshness_detector (POS: Prompt and keyword freshness detection)
- coalescing.search_cache_governor (POS: Dynamic TTL and single-flight coordinator)

[OUTPUT]
- Re-exports: await_coalesced_search, bucket_search_limit, build_search_cache_key,
  normalize_search_query, slice_search_results, reset_search_coalescing_state_for_tests,
  QueryFreshnessTier, FreshnessDetectionResult, FreshnessGovernorConfig,
  QueryFreshnessDetector, SearchCacheGovernor, GovernedSearchReceipt
"""

from myrm_agent_harness.toolkits.web_search.coalescing.freshness_intent_types import (
    FreshnessDetectionResult,
    FreshnessGovernorConfig,
    QueryFreshnessTier,
)
from myrm_agent_harness.toolkits.web_search.coalescing.query_freshness_detector import (
    QueryFreshnessDetector,
)
from myrm_agent_harness.toolkits.web_search.coalescing.search_cache_governor import (
    GovernedSearchReceipt,
    SearchCacheGovernor,
)
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
    "QueryFreshnessTier",
    "FreshnessDetectionResult",
    "FreshnessGovernorConfig",
    "QueryFreshnessDetector",
    "SearchCacheGovernor",
    "GovernedSearchReceipt",
]
