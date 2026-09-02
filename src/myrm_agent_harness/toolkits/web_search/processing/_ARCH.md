# processing/

## Overview
Search result post-processing, intent detection, explicit parameter normalization, and citation resolution.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports result processors and explicit param normalizers | ✅ |
| search_results_processor.py | Core | Two-layer dedup, domain diversity sort, Document conversion | ✅ |
| citation_resolver.py | Core | SSRF-safe citation redirect resolution, tracking parameter stripping, and source normalization | ✅ |
| intent_optimizer.py | Core | Zero-LLM-cost keyword intent classifier and param resolver | ✅ |
| _explicit_params.py | Core | Agent explicit param normalizer (time_range, Tavily site: mapping) | ✅ |

## Dependencies

- `web_search.core.common`, `web_search.providers.web_searcher` (SearchServiceType only)
