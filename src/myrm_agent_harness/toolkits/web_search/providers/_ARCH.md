# providers/

## Overview
Search provider adapters, orchestration, and priority-ordered failover chain.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports WebSearcher, SearchServiceConfig, LiteLLMSearch, search_provider_chain | ✅ |
| web_searcher.py | Core | Multi-provider search orchestrator with cache, coalescing, retry, and Document output; the search cache key carries the factory's `credential_scope_digest` of the credential the request is billed and answered under | ✅ |
| search_service_factory.py | Core | Builds the concrete search client (native or LiteLLM, direct or gateway-routed) from a provider config, rejects missing credentials up front, and is the sole owner of the credential identity: `describe_credential_scope` reports the scope the routing decision implies (gateway token endpoint plus the direct key a routed request can fall back to) and `credential_scope_digest` is the single digest the result cache and the quota cooldown both address | ✅ |
| litellm_search.py | Core | LiteLLM search adapter for provider-agnostic API calls | ✅ |
| volcengine_doubao_search.py | Core | Volcengine Search Infinity native adapter | ✅ |
| bilibili_search.py | Core | Bilibili search fast-path via public API | ✅ |
| github_code_search.py | Core | GitHub code search fast-path via public REST API with rate-limit circuit breaker | ✅ |
| chain.py | Core | Priority-ordered provider chain runner: any failed hop or empty result list advances to the next provider within a wall-clock budget (all providers empty ends as an empty answer, not an error), and every hop but the last yields after half of the remaining budget so a hung provider cannot starve the rest; quota and rate-limit failures cool the hop down under `quota_tracker_key` (provider slug plus credential fingerprint) whose depleted and rate-limited states both expire, so one exhausted account never benches a sibling key or a replacement key on the same slug | ✅ |

## Dependencies

- `web_search.core.common`, `web_search.core.error_handling`, `web_search.core.exceptions`
- `web_search.providers.search_service_factory` (credential identity of a hop: scope and digest)
- `web_search.processing`
