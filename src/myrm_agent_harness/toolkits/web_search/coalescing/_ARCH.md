# coalescing/

## Overview
In-flight search request deduplication and LRU cache-key helpers for web search API calls.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports coalescing helpers and test reset hook | ✅ |
| search_coalescing.py | Core | Single-flight coalescing, limit bucketing, timeout retry, held-lock retention; skips TTL cache for empty/error-only payloads | ✅ |
| freshness_intent_types.py | Types | Data models and intent types for Dynamic Query Freshness and Cache Governance. | ✅ |
| query_freshness_detector.py | Core | Query freshness detector for web search and request caching. | ✅ |
| search_cache_governor.py | Core | Dynamic query freshness and search cache governor. | ✅ |

## Dependencies

- `utils.lru_cache`, `web_search.core.common`
