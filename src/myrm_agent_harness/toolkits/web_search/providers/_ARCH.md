# providers/

## Overview
Search provider adapters, orchestration, and priority-ordered failover chain.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports WebSearcher, SearchServiceConfig, LiteLLMSearch, search_provider_chain | ✅ |
| web_searcher.py | Core | Multi-provider search orchestrator with cache, coalescing, retry, and Document output | ✅ |
| litellm_search.py | Core | LiteLLM search adapter for provider-agnostic API calls | ✅ |
| volcengine_doubao_search.py | Core | Volcengine Search Infinity native adapter | ✅ |
| bilibili_search.py | Core | Bilibili search fast-path via public API | ✅ |
| github_code_search.py | Core | GitHub code search fast-path via public REST API with rate-limit circuit breaker | ✅ |
| chain.py | Core | Priority-ordered provider chain runner with quota/rate-limit hop | ✅ |

## Dependencies

- `web_search.core.common`, `web_search.core.error_handling`, `web_search.core.exceptions`, `web_search.core.metrics`
- `web_search.coalescing`, `web_search.processing`
