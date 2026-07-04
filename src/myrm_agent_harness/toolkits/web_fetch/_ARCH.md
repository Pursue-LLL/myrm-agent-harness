# web_fetch/

## Overview
Layered web crawl engine with L1 HTTP / L2 Browser / L3 Stealth fallback, adaptive routing, and deep_crawl async pipeline for full-site recursive crawling.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Entry point. Re-exports CrawlEngine, result types, and global instance. | ✅ |
| engine.py | Core | CrawlEngine — tiered fetcher pool with AdaptiveRouter, caching, and concurrent crawl_many. | ✅ |
| pipeline.py | Core | ContentPipeline — HTML to clean Markdown conversion. | ✅ |
| web_fetch_agent_tools.py | Core | LangChain @tool factory. Routes fetch_full_content / fetch_and_extract / deep_crawl / check_crawl_status / cancel_crawl. | ✅ |
| deep_crawl.py | Core | DeepCrawlPipeline — recursive site crawl via sitemap/link discovery, robots.txt compliance; sitemap fetch via `secure_get`. | ✅ |
| task_store.py | Core | CrawlTaskStore — SQLite WAL durable task queue for async crawl groups. | ✅ |
| task_executor.py | Core | CrawlTaskExecutor — background asyncio worker pool consuming tasks from store. | ✅ |
| rate_limiter.py | Core | DomainRateLimiter — per-domain request interval + concurrency control. | ✅ |
| robots_parser.py | Core | RobotsParser — fetches and parses robots.txt via `secure_get` for Allow/Disallow/Crawl-Delay/Sitemap. | ✅ |
| url_normalizer.py | Util | URL normalization for de-duplication. | ✅ |
| html_to_markdown.py | Util | HTML to Markdown conversion utilities. | ✅ |
| markdown_generator.py | Util | Markdown document generation helpers. | ✅ |
| content_pruning.py | Util | Content pruning and noise removal. | ✅ |
| antibot_detector.py | Util | Anti-bot detection heuristics. | ✅ |
| binary_router.py | Util | Binary content type routing. | ✅ |
| youtube_extractor.py | Util | YouTube transcript fast-path via `[web]` optional `youtube-transcript-api` + oEmbed metadata (title/author); HTML fallback when missing. | ✅ |
| http3_probe.py | Util | HTTP/3 protocol probe. | ✅ |

| Submodule | Description |
|-----------|-------------|
| fetchers/ | L1/L2/L3 fetcher implementations (HTTP, Browser, Stealth). |
| router/ | AdaptiveRouter — self-learning fetcher selection with cost/latency optimization. |
| escalation/ | L4 remote fetch hook — Protocol, ContextVar binding, metrics; vendors in server layer. |

## L4 Escalation (WFEL)

After local L1-L3 failure, `CrawlEngine._try_escalation` tries injected `FetchEscalationProvider`
chain (Jina then Firecrawl when enabled in server config). Providers bind per agent run via
`escalation/context.py` ContextVar — **not** global singleton mutation.

- `deep_crawl` / `CrawlTaskExecutor` calls `crawl(..., allow_escalation=False)` to block L4 cost.
- L2 Browser respects `get_bound_browser_launch_mode()` for extension CDP pages.

## Architecture: Deep Crawl Pipeline

```
Agent calls web_fetch(operation="deep_crawl", url=...)
    │
    ▼
DeepCrawlPipeline
    ├── RobotsParser → fetch robots.txt, extract rules + sitemaps
    ├── DomainRateLimiter → apply Crawl-Delay
    ├── Discover pages (sitemap.xml preferred, HTML link fallback)
    ├── CrawlTaskStore → persist tasks to SQLite WAL (with URL normalization)
    └── CrawlTaskExecutor → background async workers
            ├── CrawlEngine.crawl() per URL
            ├── Rate limiting via DomainRateLimiter
            ├── Write Markdown files to sandbox volume
            ├── Recursive link discovery (depth+1 tasks added on success)
            ├── Emit progress via dispatch_custom_event
            └── Generate _index.json on completion

Cancellation: cancel_crawl sets pending tasks to 'cancelled' → Executor
finds no pending tasks → naturally stops → generates _index.json with
completed pages only. Running tasks complete but do not enqueue new links
(is_group_cancelled guard in _discover_and_enqueue_links).

Crash recovery: On init, stale 'running' tasks reset to 'pending'.
```

## Key Dependencies

- `utils.event_utils` (dispatch_custom_event for progress)
- `toolkits.retriever` (for fetch_and_extract mode)
- `httpx` (robots.txt fetching, sitemap parsing)
- `[web]` optional: `scrapling` (L1 HTTP / L3 stealth fetchers), `youtube-transcript-api` (YouTube subtitle fast-path; HTML fallback when missing)
