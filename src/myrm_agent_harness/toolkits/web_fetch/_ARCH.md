# web_fetch/

## Overview

Layered single-page web fetch engine with L1 HTTP / L2 Browser / L3 Stealth fallback, adaptive routing, optional L4 remote escalation, and UECD spill for large pages.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Entry point. Re-exports FetchEngine, result types, and global instance. | ✅ |
| engine.py | Core | FetchEngine — tiered fetcher pool entry (mixins: cache / fetch / escalation) | ✅ |
| engine_types.py | Core | CachedDocument, AccessStats, BackgroundTask, result aliases | ✅ |
| engine_cache_mixin.py | Core | Cache, coalescing, SWR background revalidation mixin | ✅ |
| engine_fetch_mixin.py | Core | L1/L2/L3 fetch, degradation, router feedback mixin | ✅ |
| engine_escalation_mixin.py | Core | L4 remote escalation + bilibili cookie loader mixin | ✅ |
| pipeline.py | Core | ContentPipeline — HTML to clean Markdown conversion. | ✅ |
| web_fetch_agent_tools.py | Core | LangChain @tool factory for fetch_full_content / fetch_and_extract. | ✅ |
| spill.py | Util | UECD wrapper — head/tail preview + evicted persist for fetch_full_content. | ✅ |
| content_sanitize.py | Util | Strip base64 image blobs from fetched markdown before model delivery. | ✅ |
| url_normalizer.py | Util | URL normalization for de-duplication. | ✅ |
| html_to_markdown.py | Util | HTML to Markdown conversion utilities. | ✅ |
| markdown_generator.py | Util | Markdown document generation helpers. | ✅ |
| content_pruning.py | Util | Content pruning and noise removal. | ✅ |
| antibot_detector.py | Util | Anti-bot detection heuristics. | ✅ |
| binary_router.py | Util | Binary content type routing. | ✅ |
| youtube_extractor.py | Util | YouTube transcript fast-path via `[web]` optional `youtube-transcript-api` + oEmbed metadata (title/author); HTML fallback when missing. | ✅ |
| bilibili_extractor.py | Util | Bilibili subtitle fast-path via public API + SessionVault cookie for AI subtitles; Browser fallback when unavailable. | ✅ |
| http3_probe.py | Util | HTTP/3 protocol probe. | ✅ |

| Submodule | Description |
|-----------|-------------|
| fetchers/ | L1/L2/L3 fetcher implementations (HTTP, Browser, Stealth). |
| router/ | AdaptiveRouter — self-learning fetcher selection with cost/latency optimization. |
| escalation/ | L4 remote fetch hook — Protocol, ContextVar binding, metrics; vendors in server layer. |

## L4 Escalation (WFEL)

After local L1-L3 failure, `FetchEngine._try_escalation` tries injected `FetchEscalationProvider`
chain (Jina then Firecrawl when enabled in server config). Providers bind per agent run via
`escalation/context.py` ContextVar — **not** global singleton mutation.

- L2 Browser respects `get_bound_browser_launch_mode()` for extension CDP pages.

## Key Dependencies

- `toolkits.retriever` (for fetch_and_extract mode)
- `httpx`
- `[web]` optional: `scrapling` (L1 HTTP / L3 stealth fetchers), `youtube-transcript-api` (YouTube subtitle fast-path; HTML fallback when missing)
