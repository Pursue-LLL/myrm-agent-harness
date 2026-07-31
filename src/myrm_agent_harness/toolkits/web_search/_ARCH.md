# web_search/

## Overview
Web search toolkit entry point. Aggregates and re-exports search tools, result types,
and the intent-aware search parameter optimizer.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Web search toolkit entry point. Aggregates and re-exports search tools, result types. | ✅ |
| common.py | Core | Provides SearchResult (title, link, snippet, summary, date, site_name, authority_description, engines, citations). | ✅ |
| engine.py | Core | Web search tools wrapper. Two modes: basic (BM25) and precision (BM25+Reranker+Autocut). Integrates intent detection. | ✅ |
| error_handling.py | Core | Search failure classification and ErrorContext construction. Quota/rate-limit SSOT (`is_quota_or_rate_limit_error`) — non-retryable + chain hop. | ✅ |
| exceptions.py | Core | Web Search exception hierarchy. All exceptions implement format_for_llm(). | ✅ |
| intent_optimizer.py | Core | Search intent detection and parameter optimization. Zero-LLM-cost keyword-based intent classifier that dynamically adjusts SearxNG/Tavily/Exa search parameters per query. | ✅ |
| litellm_search.py | Core | LiteLLM search adapter. Translates provider-agnostic search requests into LiteLLM API calls. | ✅ |
| metrics.py | Core | In-process counters for web search operations (thread-safe, optional observability hook). | ✅ |
| search_results_processor.py | Core | Search result post-processor. Two-layer deduplication (URL arbitration: same URL keeps longest content; content hash: mirror site dedup) + domain diversity sorting (same-domain decay). | ✅ |
| web_search_agent_tools.py | Core | Web search meta-tool. Integrates web search capability as a meta-tool (high frequency, 80%+ queries). | ✅ |
| citation_resolver.py | Core | SSRF-safe citation redirect resolution. Normalizes `metadata.sources` so `url` is the final clickable destination; preserves provider redirect in `redirect_url`. | ✅ |
| web_searcher.py | Core | Web search orchestrator. Unified interface for querying search providers with caching, retry, per-query parameter override, and optional priority provider chain (`provider_chain`). Dispatches native slugs (`volcengine_doubao`) or LiteLLM providers. | ✅ |
| volcengine_doubao_search.py | Core | Volcengine Search Infinity native adapter (API Key → Torchlight WebSearch). Preserves SiteName and AuthInfoDes from API response. | ✅ |
| chain.py | Core | Priority-ordered provider chain runner. Quota/rate-limit hops via `error_handling.is_quota_or_rate_limit_error`. 45s wall-clock budget and chain_hop metrics. | ✅ |
| bilibili_search.py | Core | Bilibili search fast-path. Direct API call to `api.bilibili.com/x/web-interface/search/all/v2`; zero-login, returns structured SearchResult with play count, author, duration. Returns None on failure to trigger fallback. | ✅ |
| constants.py | Core | Canonical SearXNG URLs and region presets for self-hosted search. | ✅ |
| local_probe.py | Core | HTTP probes for SearXNG endpoints (ping + HTML search verify). | ✅ |

## Key Dependencies

- `utils`
- `[retrieval]` extra — `engine.py` uses `TextChunker` from `toolkits/retriever/splitter/` for precision search chunking (`langchain-text-splitters` is not a core dep)

## Intent-Aware Search Flow

```
User query → LLM Query Rewriting → questions: list[str]
  → engine.fast_search_with_questions()
    → intent_optimizer.detect_search_intent(query) per query
    → IF all queries = PLATFORM_BILIBILI:
         bilibili_search.search_bilibili() → structured results
         (on failure → fallback: site:bilibili.com via generic search)
    → ELSE:
         intent_optimizer.resolve_search_params(intent, provider)
         WebSearcher.search(query, extra_params_override=override)
         (when provider_chain set → chain.py search_provider_chain failover)
         LiteLLM → SearxNG API (with dynamic engines/categories/time_range)
    → combine_search_results_unified()  [two-layer dedup: URL arbitration + content hash]
    → apply_domain_diversity_sort()     [same-domain decay]
    → BM25 / Precision mode selection
    → enrich_sources_with_resolved_urls()  [wrapper URLs only: SSRF-safe HEAD; direct links passthrough]
```

When intent confidence is below threshold (0.6), no adjustment is made and
the search behaves identically to before (GENERAL intent = user's default config).
