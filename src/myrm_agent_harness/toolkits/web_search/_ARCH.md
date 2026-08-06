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
| _explicit_params.py | Core | Agent explicit param normalizer. Maps time_range to provider formats; Tavily site: → search_domain_filter. | ✅ |
| error_handling.py | Core | Search failure classification and ErrorContext construction. Quota/rate-limit SSOT (`is_quota_or_rate_limit_error`) — non-retryable + chain hop. | ✅ |
| exceptions.py | Core | Web Search exception hierarchy. All exceptions implement format_for_llm(). | ✅ |
| intent_optimizer.py | Core | Search intent detection and parameter optimization. Zero-LLM-cost keyword-based intent classifier; includes AUTHORITY→Volcengine AuthInfoLevel. | ✅ |
| litellm_search.py | Core | LiteLLM search adapter. Translates provider-agnostic search requests into LiteLLM API calls. | ✅ |
| metrics.py | Core | In-process counters for web search operations (thread-safe, optional observability hook). | ✅ |
| search_results_processor.py | Core | Search result post-processor. Two-layer deduplication (URL arbitration: same URL keeps longest content; content hash: mirror site dedup) + domain diversity sorting (same-domain decay). | ✅ |
| web_search_agent_tools.py | Core | Web search meta-tool. Integrates web search capability as a meta-tool (high frequency, 80%+ queries). Supports explicit search param: time_range. | ✅ |
| _web_search_tool_description.py | Core | LLM-visible `web_search_tool` description SSOT (English + Chinese; locale via `is_chinese`). Imported by `web_search_agent_tools.py` and static tests. | ✅ |
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
  → engine.fast_search_with_questions(questions, explicit_params?)
    → normalize_explicit_params(explicit_params, provider)  [Agent → provider format]
    → intent_optimizer.detect_search_intent(query) per query
    → intent_optimizer.resolve_search_params(intent, provider) per query
    → Fusion: explicit_params > intent_override > config.extra_params
    → IF provider=tavily AND query contains site: → map to search_domain_filter (LiteLLM)
    → IF all queries = PLATFORM_BILIBILI:
         bilibili_search.search_bilibili() → structured results
         (on failure → fallback: site:bilibili.com via generic search)
    → ELSE:
         WebSearcher.search(query, extra_params_override=fused_override)
         (when provider_chain set → chain.py search_provider_chain failover)
         LiteLLM → SearxNG API (with dynamic engines/categories/time_range)
    → combine_search_results_unified()  [two-layer dedup: URL arbitration + content hash]
    → apply_domain_diversity_sort()     [same-domain decay]
    → BM25 / Precision mode selection
    → enrich_sources_with_resolved_urls()  [wrapper URLs only: SSRF-safe HEAD; direct links passthrough]
```

## Three-Priority Parameter Fusion

Search parameters are merged with highest-priority-wins:
1. **Agent explicit_params** (highest) — from tool call (time_range)
2. **Intent optimizer auto-detection** — keyword-based regex classification
3. **config.extra_params** (lowest) — user/admin search service defaults

`normalize_explicit_params()` in `_explicit_params.py` converts unified Agent params to
provider-specific formats (e.g. "week" → "OneWeek" for Volcengine; Tavily maps
relative ranges to `days` and custom `YYYY-MM-DD..YYYY-MM-DD` spans to day count capped at 365).

When intent confidence is below threshold (0.6), no adjustment is made and
the search behaves identically to before (GENERAL intent = user's default config).
