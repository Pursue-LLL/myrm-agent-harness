# core/security/http/

## Overview
SSRF-protected outbound HTTP primitives shared by harness toolkits, agent pipeline, and server media download.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports secure fetch API. | — |
| secure_fetch.py | Core | DNS-pinned HTTP with manual redirect loop (`secure_get`, `secure_request`, `resolve_secure_http_target`). | ✅ |

## Key Dependencies

- `core/security/guards/ssrf.py` — `async_pin_url`, `SSRFSecurityError`
- `httpx` — HTTP client

## Consumers

- `agent/context_management/pipeline/processors/media_resolver.py`
- `agent/skills/discovery/installers/zip_installer.py`
- `agent/skills/discovery/helpers.py`
- `agent/hooks/executor.py`
- `toolkits/a2a/resolver.py`
- `toolkits/cron/delivery.py`
- `myrm-agent-server/app/ai_agents/media_tools/image_agent_tool.py`
- `toolkits/openapi_bridge/spec_parser.py`, `http_executor.py`
- `toolkits/wiki/wiki_agent_tools.py` (`_fetch_url_as_markdown`)
- `toolkits/llms/image/generator.py`, `models.py` (reference/result URL downloads)
- `toolkits/llms/video/video_engine.py` (`_resolve_media_sources` HTTP branch)
- `toolkits/llms/video/providers/google_provider.py`, `minimax_provider.py`, `qwen_provider.py` (API result download URLs)
- `myrm-agent-server/app/channels/media/downloader.py`, `image_enrichment.py`

Browser Playwright navigation uses `toolkits/browser/navigation_ssrf_guard.py` (`async_pin_url`, not httpx).
`http_fetcher.py` uses per-hop `async_pin_url` via scrapling (security-equivalent).
