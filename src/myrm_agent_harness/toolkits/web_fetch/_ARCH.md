# web_fetch/

## Overview

Layered single-page web fetch engine with L1 HTTP / L2 Browser / L3 Stealth fallback, adaptive routing, optional L4 remote escalation, and UECD spill for large pages.

## Submodule Index

| Submodule | Role | Description |
|-----------|------|-------------|
| [engine/](engine/_ARCH.md) | Core | FetchEngine tiered fetcher pool |
| [processing/](processing/_ARCH.md) | Core | Post-fetch pipeline, markdown, spill, anti-bot |
| [probe/](probe/_ARCH.md) | Util | HTTP/3 probe and charset detection |
| [extractors/](extractors/_ARCH.md) | Core | WeChat / Bilibili / YouTube fast-paths |
| [fetchers/](fetchers/_ARCH.md) | Core | L1/L2/L3 fetcher implementations |
| [router/](router/_ARCH.md) | Core | AdaptiveRouter self-learning selection |
| [escalation/](escalation/_ARCH.md) | Core | L4 remote fetch hook |

## Package Root Files (facade only)

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports FetchEngine and result types | ✅ |
| web_fetch_agent_tools.py | Core | LangChain web_fetch_tool factory | ✅ |
| _web_fetch_tool_description.py | Core | LLM-visible tool description SSOT (EN/ZH) | ✅ |

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
- `[web]` optional: `scrapling`, `youtube-transcript-api`
