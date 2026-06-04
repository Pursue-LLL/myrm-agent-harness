# web_fetch/

## Overview
Web fetch toolkit entry point. Re-exports the core crawl engine and result types.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Web fetch toolkit entry point. Re-exports the core crawl engine and result types. | ✅ |
| antibot_detector.py | Core | Anti-bot and error page detection for crawl results. | ✅ |
| http3_probe.py | Core | One-shot QUIC egress probe and L1 HTTP/3 retry metrics (`MYRM_HTTP3_RETRY`). | ✅ |
| binary_router.py | Core | Binary content detection (3-layer: Content-Type → Content-Disposition → Magic Bytes) and routing to file parsers. | ✅ |
| content_pruning.py | Core | Provides ContentPruningFilter. | ✅ |
| engine.py | Core | Core crawl engine. Orchestrates L1/L2/L3 fetchers with adaptive routing, binary content routing, and UI FallbackEvent emission. | ✅ |
| markdown_generator.py | Core | Markdown generator | ✅ |
| pipeline.py | Core | Content processing pipeline. Sits between the fetcher layer and the consumer layer. | ✅ |
| url_normalizer.py | Core | URL normalization: strips tracking params (HubSpot, Adobe, LinkedIn, Twitter, TikTok etc.). | ✅ |
| web_fetch_agent_tools.py | Core | Web fetch meta-tool | ✅ |

| Submodule | Description |
|-----------|-------------|
| fetchers/ | Fetchers submodule. HttpFetcher: L1-QUIC-Retry on 403/antibot/empty; skips HTTP/3 when proxy pool active. |
| router/ | unified adaptive router |

## Key Dependencies

- `utils`
- Core wheels: `beautifulsoup4`, `lxml` (see `content_pruning.py`, `tree_truncator.py`)
