# coalescing/

## Overview
In-flight search request deduplication and LRU cache-key helpers for web search API calls.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports coalescing helpers and test reset hook | ✅ |
| search_coalescing.py | Core | Single-flight coalescing, limit bucketing, timeout retry, held-lock retention, orphaned-leader outcome consumption; skips TTL cache for empty/error-only payloads; key carries a non-reversible credential digest so a payload is never replayed for another key, account or endpoint | ✅ |

## Dependencies

- `utils.lru_cache`, `web_search.core.common`
