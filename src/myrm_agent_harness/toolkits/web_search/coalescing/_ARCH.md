# coalescing/

## Overview
In-flight search request deduplication and LRU cache-key helpers for web search API calls.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports coalescing helpers and test reset hook | ✅ |
| search_coalescing.py | Core | Single-flight coalescing, limit bucketing, timeout retry, held-lock retention; skips TTL cache for empty/error-only payloads | ✅ |

## Dependencies

- `utils.lru_cache`, `web_search.core.common`
