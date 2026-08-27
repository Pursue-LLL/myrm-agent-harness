# web_fetch/

## Overview

Layered single-page web fetch engine with L1 HTTP / L2 Browser / L3 Stealth fallback, adaptive routing, optional L4 remote escalation, and UECD spill for large pages.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Entry point. Re-exports FetchEngine, result types, and global instance. | ✅ |
| engine/ | Core | FetchEngine sub-package — tiered fetcher pool (base + cache/fetch/escalation mixins + shared types). See `engine/_ARCH.md`. | ✅ |
| pipeline.py | Core | ContentPipeline — HTML/JSON/XML to clean Markdown conversion. | ✅ |
| charset_detector.py | Util | Multi-tier charset detector (Header / Meta Tag / Chardet probe) for safe decoding. | ✅ |
| web_fetch_agent_tools.py | Core | LangChain @tool factory for fetch_full_content / fetch_and_extract. Accepts `blocked_hostnames` (host hits raise `ToolError` with `error_category=ToolErrorCategory.BENCHMARK_BLOCKED`) and `description_locale` (locale-aware LLM description). | ✅ |
| _web_fetch_tool_description.py | Core | LLM-visible `web_fetch_tool` description SSOT (English + Chinese; locale via `is_chinese`; extract-mode aware). Imported by `web_fetch_agent_tools.py` and static tests. | ✅ |
| spill.py | Util | UECD wrapper — head/tail preview + evicted persist for fetch_full_content. | ✅ |
| content_sanitize.py | Util | Strip base64 image blobs from fetched markdown before model delivery. | ✅ |
| url_normalizer.py | Util | URL normalization for de-duplication. | ✅ |
| html_to_markdown.py | Util | HTML to Markdown conversion utilities. | ✅ |
| markdown_generator.py | Util | Markdown document generation helpers. | ✅ |
| content_pruning.py | Util | Content pruning and noise removal. | ✅ |
| antibot_detector.py | Util | Anti-bot detection heuristics. | ✅ |
| binary_router.py | Util | Binary content type routing. | ✅ |
| http3_probe.py | Util | HTTP/3 protocol probe. | ✅ |

| Submodule | Description |
|-----------|-------------|
| engine/ | FetchEngine 执行引擎子包（base + cache/fetch/escalation mixin + types）。 |
| extractors/ | 三方内容提取 fast-path（WeChat / Bilibili / YouTube）。See `extractors/_ARCH.md`. |
| fetchers/ | L1/L2/L3 fetcher implementations (HTTP, Browser, Stealth). |
| router/ | AdaptiveRouter — self-learning fetcher selection with cost/latency optimization. |
| escalation/ | L4 remote fetch hook — Protocol, ContextVar binding, metrics; vendors in server layer. |

## L4 Escalation (WFEL)

After local L1-L3 failure, `FetchEngine._try_escalation` tries injected `FetchEscalationProvider`
chain (Jina then Firecrawl when enabled in server config). Providers bind per agent run via
`escalation/context.py` ContextVar — **not** global singleton mutation.

- L2 Browser respects `get_bound_browser_launch_mode()` for extension CDP pages.

## Tool routing (web_fetch vs browser)

When both tools are mounted: read-only pages → `web_fetch_tool` (CORE); interactive flows → browser tools (EXTENDED). Guidance lives in tool descriptions + Dynamic Hints (`browser/tools/navigate.py`), not System Prompt. Loop Guard provides symmetric fallback suggestions. See `toolkits/browser/BROWSER_SYSTEM.md` §web_fetch 与 browser 分工.

## Key Dependencies

- `toolkits.retriever` (for fetch_and_extract mode)
- `httpx`
- `[web]` optional: `scrapling` (L1 HTTP / L3 stealth fetchers), `youtube-transcript-api` (YouTube subtitle fast-path; HTML fallback when missing)
