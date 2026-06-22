# web_search/

## Overview
Web search toolkit entry point. Aggregates and re-exports search tools, result types,
and the intent-aware search parameter optimizer.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Web search toolkit entry point. Aggregates and re-exports search tools, result types. | ✅ |
| common.py | Core | Provides SearchResult. | ✅ |
| engine.py | Core | Web search tools wrapper. Two modes: basic (BM25) and precision (BM25+Reranker+Autocut). Integrates intent detection. | ✅ |
| error_handling.py | Core | Search failure classification and ErrorContext construction. | ✅ |
| exceptions.py | Core | Web Search exception hierarchy. All exceptions implement format_for_llm(). | ✅ |
| intent_optimizer.py | Core | Search intent detection and parameter optimization. Zero-LLM-cost keyword-based intent classifier that dynamically adjusts SearxNG/Tavily/Exa search parameters per query. | ✅ |
| litellm_search.py | Core | LiteLLM search adapter. Translates provider-agnostic search requests into LiteLLM API calls. | ✅ |
| metrics.py | Core | In-process counters for web search operations (thread-safe, optional observability hook). | ✅ |
| search_results_processor.py | Core | Search result post-processor. Sits between raw search API responses and the consumer. | ✅ |
| web_search_agent_tools.py | Core | Web search meta-tool. Integrates web search capability as a meta-tool (high frequency, 80%+ queries). | ✅ |
| web_searcher.py | Core | Web search orchestrator. Unified interface for querying multiple search providers with caching, retry, per-query parameter override, and Try-Catch Flexible Fallback. | ✅ |
| constants.py | Core | Canonical SearXNG URLs and region presets for self-hosted search. | ✅ |
| local_probe.py | Core | HTTP probes for SearXNG endpoints (ping + HTML search verify). | ✅ |

## Key Dependencies

- `utils`

## Intent-Aware Search Flow

```
User query → LLM Query Rewriting → questions: list[str]
  → engine.fast_search_with_questions()
    → intent_optimizer.detect_search_intent(query) per query
    → intent_optimizer.resolve_search_params(intent, provider)
    → WebSearcher.search(query, extra_params_override=override)
    → LiteLLM → SearxNG API (with dynamic engines/categories/time_range)
```

When intent confidence is below threshold (0.6), no adjustment is made and
the search behaves identically to before (GENERAL intent = user's default config).
