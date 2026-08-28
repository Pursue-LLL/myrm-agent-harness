"""Search result processing, intent optimization, and citation resolution.

[INPUT]
- processing._explicit_params (POS: Agent explicit param normalizer)
- processing.search_results_processor (POS: Search result post-processor)

[OUTPUT]
- Re-exports: combine_search_results_unified, search_results_to_documents, apply_domain_diversity_sort, normalize_explicit_params, apply_tavily_site_constraint

[POS]
Subpackage entry for search post-processing and intent-aware parameter normalization.
"""

from myrm_agent_harness.toolkits.web_search.processing._explicit_params import (
    apply_tavily_site_constraint,
    normalize_explicit_params,
)
from myrm_agent_harness.toolkits.web_search.processing.search_results_processor import (
    apply_domain_diversity_sort,
    combine_search_results_unified,
    search_results_to_documents,
)

__all__ = [
    "apply_domain_diversity_sort",
    "apply_tavily_site_constraint",
    "combine_search_results_unified",
    "normalize_explicit_params",
    "search_results_to_documents",
]
