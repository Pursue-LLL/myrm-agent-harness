# web_search/

## Overview
Web search toolkit entry point. Aggregates and re-exports search tools, result types,
and the intent-aware search parameter optimizer.

## Submodule Index

| Submodule | Role | Description |
|-----------|------|-------------|
| [core/](core/_ARCH.md) | Core | Shared types, exceptions, error handling, metrics |
| [providers/](providers/_ARCH.md) | Core | Provider adapters, WebSearcher orchestrator, failover chain |
| [processing/](processing/_ARCH.md) | Core | Result dedup/sort, intent optimizer, citation resolver, explicit params |
| [coalescing/](coalescing/_ARCH.md) | Core | Single-flight search API deduplication and LRU cache keys |
| [probe/](probe/_ARCH.md) | Core | SearXNG local discovery probes and region presets |

## Package Root Files

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Toolkit entry point; lazy re-exports WebSearchTools, LiteLLMSearch, SearchServiceConfig | ✅ |
| engine.py | Core | WebSearchTools wrapper: parallel search + dedup + BM25/precision modes | ✅ |
| web_search_agent_tools.py | Core | LangChain `web_search_tool` factory | ✅ |
| _web_search_tool_description.py | Core | LLM-visible tool description SSOT (EN/ZH) | ✅ |

## Package Root Files (facade only)

Root `.py` files are limited to orchestration facade and LangChain adapter; shared types live under `core/`.

## Key Dependencies

- `utils`
- `[retrieval]` extra — `engine.py` uses `TextChunker` from `toolkits/retriever/splitter/` for precision search chunking

## Intent-Aware Search Flow

```
User query → LLM Query Rewriting → questions: list[str]
  → engine.fast_search_with_questions(questions, explicit_params?)
    → processing._explicit_params.normalize_explicit_params(explicit_params, provider)
    → processing.intent_optimizer.detect_search_intent(query) per query
    → processing.intent_optimizer.resolve_search_params(intent, provider) per query
    → Fusion: explicit_params > intent_override > config.extra_params
    → IF provider=tavily AND query contains site: → map to search_domain_filter (LiteLLM)
    → IF all queries = PLATFORM_BILIBILI:
         providers.bilibili_search.search_bilibili() → structured results
         (on failure → fallback: site:bilibili.com via generic search)
    → ELSE:
         providers.WebSearcher.search(query, extra_params_override=fused_override)
         (when provider_chain set → providers.chain search_provider_chain failover)
         coalescing.await_coalesced_search deduplicates concurrent identical API keys
         (TTL cache skipped when the provider payload has no usable URL results)
    → processing.combine_search_results_unified()
    → processing.apply_domain_diversity_sort()
    → _drop_blocked_hostname_docs()
    → BM25 / Precision mode selection
    → processing.citation_resolver.enrich_sources_with_resolved_urls()
```

## Three-Priority Parameter Fusion

Search parameters are merged with highest-priority-wins:
1. **Agent explicit_params** (highest) — from tool call (time_range)
2. **Intent optimizer auto-detection** — keyword-based regex classification
3. **config.extra_params** (lowest) — user/admin search service defaults

`normalize_explicit_params()` in `processing/_explicit_params.py` converts unified Agent params to
provider-specific formats. When intent confidence is below threshold (0.6), search behaves as GENERAL intent.
